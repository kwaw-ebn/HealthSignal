import hashlib
import json
import math
import secrets
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .auth import allow, current_user
from .database import (
    AuditLog,
    CareEpisode,
    CareEvent,
    Facility,
    LaboratoryTest,
    LocationAccessGrant,
    MedicationOrder,
    WardAdmission,
    AncVisit,
    InventoryItem,
    InsuranceClaim,
    RevenueTransaction,
    ServiceCharge,
    NetworkReferral,
    NetworkReferralEvent,
    ReferralAccessGrant,
    Patient,
    User,
    get_db,
)

router = APIRouter(prefix="/api/v1/care-network", tags=["Care Network"])

CARE_ROLES = {"administrator", "clinician", "nutritionist_dietitian", "opd_nurse", "records_officer", "laboratory_officer", "pharmacist", "ward_nurse", "midwife", "theatre_staff", "stores_officer", "revenue_officer", "accountant", "insurance_officer", "data_officer"}
CLINICAL_ROLES = {"administrator", "clinician", "nutritionist_dietitian"}
REFERRAL_STATES = {"sent", "accepted", "arrived", "in_care", "completed", "redirected"}
WARDS = {"Female Ward", "Male Ward", "Children's Ward", "Emergency", "Maternity Ward", "Male Surgical Ward", "Female Surgical Ward", "Theatre", "ICU", "NICU"}
DEPARTMENTS = {"Records", "OPD", "Consulting Room", "Laboratory", "Pharmacy", "RCH", "ANC", "Stores", "Revenue", "Accounts", "Finance"} | WARDS
SHAREABLE_SCOPES = {"demographics", "care_summary", "allergies", "vitals", "laboratory", "medications"}
REFERRAL_ACCESS_ROLES = {"administrator", "clinician", "nutritionist_dietitian"}


def clean(value, limit=3000):
    return str(value or "").strip()[:limit]


def month_window(month):
    start=datetime.fromisoformat(month+"-01")
    end=datetime(start.year+1,1,1) if start.month==12 else datetime(start.year,start.month+1,1)
    return start,end


def require_care_role(user):
    if user.role not in CARE_ROLES:
        raise HTTPException(403, "Your role does not have access to hospital operations")


def facility_for(user):
    facility = clean(user.facility, 160)
    if not facility and user.role == "administrator":
        facility = "HealthSignal Demonstration Hospital"
    if not facility:
        raise HTTPException(422, "Your account must be assigned to a facility")
    return facility


def distance_metres(lat1, lon1, lat2, lon2):
    """Great-circle distance between two coordinate pairs."""
    radius = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def care_user(x_care_access: str | None = Header(None), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Require a current location grant when the assigned facility enables geofencing."""
    require_care_role(user); facility = facility_for(user)
    config = db.scalar(select(Facility).where(Facility.name == facility, Facility.active.is_(True)))
    if not config or not config.geofence_enabled:
        return user
    if not x_care_access:
        raise HTTPException(403, "Verify your workplace location before using Care Network", headers={"X-Care-Location":"required"})
    grant_hash = hashlib.sha256(x_care_access.encode()).hexdigest()
    grant = db.scalar(select(LocationAccessGrant).where(LocationAccessGrant.grant_hash == grant_hash, LocationAccessGrant.username == user.username, LocationAccessGrant.facility == facility, LocationAccessGrant.revoked.is_(False)))
    if not grant or grant.expires_at <= datetime.utcnow():
        raise HTTPException(403, "Your workplace location verification has expired", headers={"X-Care-Location":"required"})
    return user


def care_allow(*roles):
    def check(user: User = Depends(care_user)):
        if user.role not in roles:
            raise HTTPException(403, "Your role cannot perform this Care Network action")
        return user
    return check


def audit(db, user, action, target_type, target_id, details=""):
    db.add(AuditLog(actor=user.username, action=action, target_type=target_type, target_id=target_id, details=details))


def episode_json(row):
    return {
        "episode_id": row.episode_id,
        "patient_code": row.patient_code,
        "facility": row.facility,
        "visit_date": row.visit_date,
        "visit_type": row.visit_type,
        "status": row.status,
        "chief_complaint": row.chief_complaint,
        "assigned_department": row.assigned_department,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
    }


def add_charge(db, episode, user, service_area, description, payload, source_type, source_id=None):
    """Create a ledger line when a price is supplied; routing follows coverage, not payment method."""
    try:
        amount = float(payload.get("charge_amount") or 0)
    except (TypeError, ValueError):
        raise HTTPException(422, "Service charge must be a valid amount")
    if amount < 0: raise HTTPException(422, "Service charge cannot be negative")
    if amount == 0: return None
    insured = db.scalar(select(InsuranceClaim).where(InsuranceClaim.episode_id == episode.episode_id))
    covered = bool(insured and payload.get("insurance_covered") is True)
    row = ServiceCharge(
        charge_id=str(uuid.uuid4()), episode_id=episode.episode_id, patient_code=episode.patient_code,
        facility=episode.facility, service_area=service_area, description=clean(description, 200), amount=amount,
        payer="insurance" if covered else "patient", insurance_covered=covered,
        status="insurance_pending" if covered else "patient_due", source_type=source_type,
        source_id=source_id, created_by=user.username,
    )
    db.add(row)
    return row


def bill_snapshot(db, episode):
    charges = db.scalars(select(ServiceCharge).where(ServiceCharge.episode_id == episode.episode_id).order_by(ServiceCharge.created_at)).all()
    patient_total = sum(x.amount for x in charges if x.payer == "patient")
    insurance_total = sum(x.amount for x in charges if x.payer == "insurance")
    patient_paid = sum(x.amount for x in charges if x.payer == "patient" and x.status == "paid")
    insurance_ready = all(x.status in {"claimed", "paid", "waived"} for x in charges if x.payer == "insurance")
    patient_ready = all(x.status in {"paid", "waived"} for x in charges if x.payer == "patient")
    return {
        "episode_id": episode.episode_id, "patient_code": episode.patient_code, "visit_type": episode.visit_type,
        "episode_status": episode.status, "financially_cleared": bool(charges) and patient_ready and insurance_ready,
        "patient_total": round(patient_total, 2), "patient_paid": round(patient_paid, 2),
        "patient_balance": round(patient_total - patient_paid, 2), "insurance_total": round(insurance_total, 2),
        "charges": [{"charge_id":x.charge_id,"service_area":x.service_area,"description":x.description,"amount":x.amount,"payer":x.payer,"insurance_covered":x.insurance_covered,"status":x.status,"created_at":x.created_at.isoformat()} for x in charges],
    }


def claim_snapshot(db, claim):
    episode = db.scalar(select(CareEpisode).where(CareEpisode.episode_id == claim.episode_id))
    events = db.scalars(select(CareEvent).where(CareEvent.episode_id == claim.episode_id).order_by(CareEvent.created_at)).all()
    tests = db.scalars(select(LaboratoryTest).where(LaboratoryTest.encounter_id == claim.episode_id)).all()
    medicines = db.scalars(select(MedicationOrder).where(MedicationOrder.episode_id == claim.episode_id)).all()
    admission = db.scalar(select(WardAdmission).where(WardAdmission.episode_id == claim.episode_id).order_by(WardAdmission.admitted_at.desc()))
    manual = json.loads(claim.manual_entries_json or "[]")
    service_types = ["Outpatient"]
    if admission: service_types.append("Inpatient")
    if tests: service_types.append("Diagnostic")
    if medicines: service_types.append("Pharmacy")
    diagnoses = [{"description": e.summary, "source": "Consulting Room"} for e in events if e.event_type == "consultation"]
    procedures = [{"description": e.summary, "source": e.department} for e in events if e.event_type in {"ward_admission", "ward_discharge", "procedure", "theatre_procedure"}]
    investigations = [{"description": t.test_name, "result": t.result, "unit": t.result_unit or "", "source": "Laboratory"} for t in tests]
    medication_entries = [{"description": m.medicine, "instructions": m.instructions, "status": m.status, "source": "Pharmacy"} for m in medicines]
    covered_charges = db.scalars(select(ServiceCharge).where(ServiceCharge.episode_id == claim.episode_id, ServiceCharge.payer == "insurance").order_by(ServiceCharge.created_at)).all()
    for entry in manual:
        {"procedure": procedures, "diagnosis": diagnoses, "investigation": investigations, "medicine": medication_entries}.get(entry.get("type"), []).append(entry)
    dates = sorted({e.created_at.date().isoformat() for e in events})[:4]
    return {"claim_id": claim.claim_id, "episode_id": claim.episode_id, "patient_code": claim.patient_code, "facility": claim.facility, "member_number": claim.member_number, "ccc_number": claim.ccc_number, "surname": claim.surname, "other_names": claim.other_names, "gender": claim.gender, "date_of_birth": claim.date_of_birth, "folder_number": claim.folder_number, "visit_date": episode.visit_date if episode else None, "visit_type": episode.visit_type if episode else None, "service_types": service_types, "attendance_type": claim.attendance_type, "service_outcome": claim.service_outcome, "specialty": claim.specialty, "service_dates": dates, "referring_facility": claim.referring_facility, "referral_code": claim.referral_code, "physician_name_id": claim.physician_name_id, "pre_authorization_codes": claim.pre_authorization_codes, "principal_gdrg": claim.principal_gdrg, "procedures": procedures, "diagnoses": diagnoses, "investigations": investigations, "medicines": medication_entries, "covered_charges":[{"charge_id":x.charge_id,"service_area":x.service_area,"description":x.description,"amount":x.amount,"status":x.status} for x in covered_charges], "claim_total":round(sum(x.amount for x in covered_charges),2), "status": claim.status, "validation_errors": json.loads(claim.validation_json or "[]"), "updated_at": claim.updated_at.isoformat()}


def validate_claim(snapshot):
    errors=[]
    for field, label in (("member_number","Member/HIN number"),("ccc_number","CCC number"),("surname","Surname"),("gender","Gender"),("physician_name_id","Physician name/ID")):
        if not snapshot.get(field): errors.append(f"{label} is required")
    if not snapshot.get("diagnoses"): errors.append("At least one diagnosis is required")
    if not snapshot.get("service_types"): errors.append("At least one service type is required")
    return errors


def referral_json(row, include_summary=False):
    data = {
        "referral_id": row.referral_id,
        "episode_id": row.episode_id,
        "patient_code": row.patient_code,
        "source_facility": row.source_facility,
        "destination_facility": row.destination_facility,
        "reason": row.reason,
        "urgency": row.urgency,
        "status": row.status,
        "consent_confirmed": row.consent_confirmed,
        "consent_type": row.consent_type,
        "consent_scopes": json.loads(row.consent_scope_json or '[]'),
        "consent_revoked": bool(row.consent_revoked_at),
        "receiving_department": row.receiving_department,
        "access_count": row.access_count or 0,
        "accepted_by": row.accepted_by,
        "feedback": row.feedback,
        "expires_at": row.expires_at.isoformat(),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
    }
    if include_summary:
        data["clinical_summary"] = row.clinical_summary
    return data


def referral_packet(db, row, user, reason, emergency=False):
    scopes = {"demographics", "care_summary", "allergies"} if emergency else set(json.loads(row.consent_scope_json or '[]'))
    patient = db.scalar(select(Patient).where(Patient.patient_code == row.patient_code))
    events = db.scalars(select(CareEvent).where(CareEvent.episode_id == row.episode_id, CareEvent.facility == row.source_facility).order_by(CareEvent.created_at)).all()
    packet = {"referral": referral_json(row, "care_summary" in scopes), "shared_scopes": sorted(scopes), "emergency_access": emergency}
    if "demographics" in scopes:
        packet["patient"] = {"patient_code": row.patient_code, "sex": patient.sex if patient else None, "age": patient.approximate_age if patient else None}
    else:
        packet["patient"] = {"patient_code": row.patient_code}
    if "vitals" in scopes:
        packet["vitals"] = [{"summary": e.summary, "recorded_at": e.created_at.isoformat()} for e in events if e.event_type == "triage"][-1:]
    if "allergies" in scopes:
        allergies=[]
        for e in events:
            if e.event_type == "consultation":
                data=json.loads(e.clinical_data_json or '{}')
                if data.get("allergies"): allergies.append(data["allergies"])
        packet["allergies"] = allergies[-1:] or ["Not recorded"]
    if "laboratory" in scopes:
        labs=db.scalars(select(LaboratoryTest).where(LaboratoryTest.encounter_id == row.episode_id).order_by(LaboratoryTest.tested_at)).all()
        packet["laboratory_results"]=[{"test_name":x.test_name,"result":x.result,"unit":x.result_unit,"tested_at":x.tested_at.isoformat()} for x in labs]
        if not packet["laboratory_results"]:
            packet["laboratory_results"]=[{"test_name":e.summary,"result":"See handover","unit":"","tested_at":e.created_at.isoformat()} for e in events if e.event_type == "laboratory_result"]
    if "medications" in scopes:
        meds=db.scalars(select(MedicationOrder).where(MedicationOrder.episode_id == row.episode_id).order_by(MedicationOrder.created_at)).all()
        packet["medications"]=[{"medicine":x.medicine,"instructions":x.instructions,"status":x.status} for x in meds]
    raw=secrets.token_urlsafe(32); expires=datetime.utcnow()+timedelta(minutes=30)
    db.add(ReferralAccessGrant(grant_hash=hashlib.sha256(raw.encode()).hexdigest(),referral_id=row.referral_id,username=user.username,facility=facility_for(user),department=row.receiving_department,purpose="emergency_treatment" if emergency else "referral_treatment",access_reason=reason,emergency=emergency,expires_at=expires))
    row.access_count=(row.access_count or 0)+1; row.last_accessed_at=datetime.utcnow()
    packet["access_session"]={"token":raw,"expires_at":expires.isoformat(),"notice":"Access is limited to this referral package and is fully audited."}
    return packet


def require_local_episode(db, episode_id, user):
    episode = db.scalar(select(CareEpisode).where(CareEpisode.episode_id == episode_id))
    if not episode:
        raise HTTPException(404, "Care episode not found")
    if user.role != "administrator" and episode.facility.casefold() != facility_for(user).casefold():
        raise HTTPException(403, "This care episode belongs to another facility")
    return episode


@router.get("/security")
def location_security(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user)
    config = db.scalar(select(Facility).where(Facility.name == facility, Facility.active.is_(True)))
    return {
        "facility": facility,
        "configured": bool(config and config.latitude is not None and config.longitude is not None),
        "geofence_enabled": bool(config and config.geofence_enabled),
        "allowed_radius_m": config.allowed_radius_m if config else 250,
        "grant_minutes": 20,
        "administrator": user.role == "administrator",
        "notice": "Presentation control only. Production use requires additional device, MFA and network security.",
    }


@router.put("/security/config")
def configure_location_security(payload: dict, user: User = Depends(allow("administrator")), db: Session = Depends(get_db)):
    name = clean(payload.get("facility"), 160) or facility_for(user)
    try:
        latitude, longitude = float(payload.get("latitude")), float(payload.get("longitude"))
        radius = int(payload.get("allowed_radius_m", 250))
    except (TypeError, ValueError):
        raise HTTPException(422, "Valid facility coordinates and radius are required")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or not 50 <= radius <= 5000:
        raise HTTPException(422, "Coordinates or radius are outside the permitted range")
    row = db.scalar(select(Facility).where(Facility.name == name))
    if not row:
        row = Facility(facility_id=str(uuid.uuid4()), name=name, facility_type=clean(payload.get("facility_type"), 60) or "Hospital", district=clean(payload.get("district"), 120) or clean(user.district, 120) or "Not assigned", region=clean(payload.get("region"), 120) or clean(user.region, 120) or "Not assigned", created_by=user.username)
        db.add(row)
    row.latitude=latitude; row.longitude=longitude; row.allowed_radius_m=radius; row.geofence_enabled=payload.get("geofence_enabled") is True; row.active=True
    audit(db, user, "care_geofence_configured", "facility", row.facility_id, f"enabled={row.geofence_enabled}; radius={radius}m")
    db.commit()
    return {"message":"Facility location security updated","facility":name,"geofence_enabled":row.geofence_enabled,"allowed_radius_m":radius}


@router.post("/security/verify")
def verify_workplace_location(payload: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user)
    config = db.scalar(select(Facility).where(Facility.name == facility, Facility.active.is_(True)))
    if not config or not config.geofence_enabled:
        audit(db, user, "care_location_not_required", "facility", facility, "Geofence disabled"); db.commit()
        return {"verified":True,"restricted":False,"facility":facility,"message":"Location restriction is not enabled for this facility"}
    if config.latitude is None or config.longitude is None:
        raise HTTPException(409, "The administrator must configure facility coordinates")
    try:
        latitude, longitude = float(payload.get("latitude")), float(payload.get("longitude"))
        accuracy = float(payload.get("accuracy_m")) if payload.get("accuracy_m") is not None else None
    except (TypeError, ValueError):
        raise HTTPException(422, "Valid device coordinates are required")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise HTTPException(422, "Invalid device coordinates")
    distance = round(distance_metres(latitude, longitude, config.latitude, config.longitude), 1)
    accuracy_limit = max(config.allowed_radius_m, 500)
    if accuracy is not None and (accuracy < 0 or accuracy > accuracy_limit):
        audit(db, user, "care_location_denied", "facility", facility, f"accuracy={accuracy:.1f}m"); db.commit()
        raise HTTPException(403, f"Location accuracy is too low ({accuracy:.0f} m). Move near a window or use a GPS enabled device")
    if distance > config.allowed_radius_m:
        audit(db, user, "care_location_denied", "facility", facility, f"distance={distance}m; radius={config.allowed_radius_m}m"); db.commit()
        raise HTTPException(403, f"You are approximately {distance:.0f} metres from the approved facility area")
    raw_grant = secrets.token_urlsafe(32); grant_hash = hashlib.sha256(raw_grant.encode()).hexdigest(); expires = datetime.utcnow()+timedelta(minutes=20)
    db.add(LocationAccessGrant(grant_hash=grant_hash,username=user.username,facility=facility,latitude=latitude,longitude=longitude,accuracy_m=accuracy,distance_m=distance,expires_at=expires))
    audit(db, user, "care_location_verified", "facility", facility, f"distance={distance}m; accuracy={accuracy}m"); db.commit()
    return {"verified":True,"restricted":True,"facility":facility,"distance_m":distance,"allowed_radius_m":config.allowed_radius_m,"expires_at":expires.isoformat(),"care_access_token":raw_grant}


@router.get("/overview")
def overview(user: User = Depends(care_user), db: Session = Depends(get_db)):
    require_care_role(user)
    facility = facility_for(user)
    episodes = db.scalars(select(CareEpisode).where(CareEpisode.facility == facility).order_by(CareEpisode.created_at.desc()).limit(200)).all()
    referrals = db.scalars(select(NetworkReferral).where(or_(NetworkReferral.source_facility == facility, NetworkReferral.destination_facility == facility)).order_by(NetworkReferral.created_at.desc()).limit(100)).all()
    role_department = {"opd_nurse":"OPD", "laboratory_officer":"Laboratory", "pharmacist":"Pharmacy"}.get(user.role)
    if role_department: episodes = [row for row in episodes if row.assigned_department == role_department]
    if user.role == "records_officer": episodes = [row for row in episodes if row.created_by == user.username]
    queues = {}
    for row in episodes:
        if row.status not in {"completed", "cancelled"}:
            queues[row.assigned_department] = queues.get(row.assigned_department, 0) + 1
    return {
        "facility": facility,
        "active_episodes": sum(1 for row in episodes if row.status not in {"completed", "cancelled"}),
        "incoming_referrals": sum(1 for row in referrals if row.destination_facility == facility and row.status == "sent"),
        "open_referrals": sum(1 for row in referrals if row.status not in {"completed", "redirected"}),
        "department_queues": [{"department": key, "count": value} for key, value in sorted(queues.items())],
        "recent_episodes": [episode_json(row) for row in episodes[:12]],
    }


@router.post("/facilities", status_code=201)
def create_facility(payload: dict, user: User = Depends(allow("administrator")), db: Session = Depends(get_db)):
    name, district, region = clean(payload.get("name"), 160), clean(payload.get("district"), 120), clean(payload.get("region"), 120)
    if not all((name, district, region)):
        raise HTTPException(422, "Facility name, district and region are required")
    existing = db.scalar(select(Facility).where(Facility.name == name))
    if existing:
        raise HTTPException(409, "Facility already exists")
    row = Facility(facility_id=str(uuid.uuid4()), name=name, facility_type=clean(payload.get("facility_type"), 60) or "Hospital", district=district, region=region, created_by=user.username)
    db.add(row); audit(db, user, "facility_created", "facility", row.facility_id, name); db.commit()
    return {"facility_id": row.facility_id, "name": row.name}


@router.get("/facilities")
def list_facilities(user: User = Depends(care_user), db: Session = Depends(get_db)):
    require_care_role(user)
    rows = db.scalars(select(Facility).where(Facility.active.is_(True)).order_by(Facility.name)).all()
    names = {row.name for row in rows}
    account_facilities = db.scalars(select(User.facility).where(User.facility.is_not(None), User.status == "approved")).all()
    result = [{"facility_id": row.facility_id, "name": row.name, "facility_type": row.facility_type, "district": row.district, "region": row.region} for row in rows]
    for name in sorted({clean(x, 160) for x in account_facilities if clean(x, 160)} - names):
        result.append({"facility_id": None, "name": name, "facility_type": "Registered facility", "district": "", "region": ""})
    return result


@router.post("/episodes", status_code=201)
def register_episode(payload: dict, user: User = Depends(care_allow("administrator", "records_officer")), db: Session = Depends(get_db)):
    facility = facility_for(user)
    patient_code = clean(payload.get("patient_code"), 64).upper()
    if not patient_code:
        patient_code = "HS-" + secrets.token_hex(4).upper()
    patient = db.scalar(select(Patient).where(Patient.patient_code == patient_code))
    if not patient:
        sex, age = clean(payload.get("sex"), 20), payload.get("age")
        if sex not in {"Female", "Male", "Other", "Not recorded"} or not isinstance(age, int) or not 0 <= age <= 120:
            raise HTTPException(422, "A valid age and sex are required for a new patient")
        patient = Patient(patient_code=patient_code, sex=sex, approximate_age=age, home_community=clean(payload.get("community"), 120), district=user.district, region=user.region, created_by=user.username)
        db.add(patient)
    episode = CareEpisode(
        episode_id=str(uuid.uuid4()), patient_code=patient_code, facility=facility,
        visit_date=clean(payload.get("visit_date"), 10) or datetime.utcnow().date().isoformat(),
        visit_type=clean(payload.get("visit_type"), 40) or "OPD", status="registered",
        chief_complaint=clean(payload.get("chief_complaint")), assigned_department="OPD", created_by=user.username,
    )
    db.add(episode)
    member_number = clean(payload.get("insurance_number"), 80)
    if member_number:
        claim = InsuranceClaim(
            claim_id=str(uuid.uuid4()), episode_id=episode.episode_id, patient_code=patient_code,
            facility=facility, member_number=member_number, ccc_number=clean(payload.get("ccc_number"), 80) or None,
            surname=clean(payload.get("surname"), 120), other_names=clean(payload.get("other_names"), 180),
            gender=clean(payload.get("sex"), 20) or "Not recorded", date_of_birth=clean(payload.get("date_of_birth"), 10) or None,
            folder_number=clean(payload.get("folder_number"), 80) or None,
            attendance_type=clean(payload.get("attendance_type"), 40) or "Emergency/Acute Episode", created_by=user.username,
        )
        db.add(claim)
    db.add(CareEvent(event_id=str(uuid.uuid4()), episode_id=episode.episode_id, patient_code=patient_code, facility=facility, department="Records", event_type="registered", summary="Patient registered for care", clinical_data_json="{}", created_by=user.username))
    add_charge(db, episode, user, "Records", clean(payload.get("charge_description"),200) or "Registration / records", payload, "registration", episode.episode_id)
    audit(db, user, "care_episode_registered", "care_episode", episode.episode_id, facility); db.commit()
    result=episode_json(episode);result["insurance_claim_created"]=bool(member_number)
    return result


@router.get("/episodes")
def list_episodes(department: str | None = None, status: str | None = None, user: User = Depends(care_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user)
    stmt = select(CareEpisode).where(CareEpisode.facility == facility).order_by(CareEpisode.created_at.desc()).limit(300)
    role_department = {"opd_nurse":"OPD", "laboratory_officer":"Laboratory", "pharmacist":"Pharmacy"}.get(user.role)
    if role_department: stmt = stmt.where(CareEpisode.assigned_department == role_department)
    if user.role == "records_officer": stmt = stmt.where(CareEpisode.created_by == user.username)
    if department: stmt = stmt.where(CareEpisode.assigned_department == department)
    if status: stmt = stmt.where(CareEpisode.status == status)
    return [episode_json(row) for row in db.scalars(stmt).all()]


@router.post("/episodes/{episode_id}/triage", status_code=201)
def add_triage(episode_id: str, payload: dict, user: User = Depends(care_allow("administrator", "opd_nurse")), db: Session = Depends(get_db)):
    episode = require_local_episode(db, episode_id, user)
    vitals = {key: payload.get(key) for key in ("temperature_c", "pulse", "respiratory_rate", "oxygen_saturation", "systolic", "diastolic", "weight_kg", "height_cm")}
    if not any(value is not None and value != "" for value in vitals.values()):
        raise HTTPException(422, "Record at least one vital sign")
    if vitals.get("weight_kg") and vitals.get("height_cm"):
        vitals["bmi"] = round(float(vitals["weight_kg"]) / (float(vitals["height_cm"]) / 100) ** 2, 1)
    episode.status = "triaged"; episode.assigned_department = "Consulting Room"; episode.updated_at = datetime.utcnow()
    event = CareEvent(event_id=str(uuid.uuid4()), episode_id=episode.episode_id, patient_code=episode.patient_code, facility=episode.facility, department="OPD", event_type="triage", summary=clean(payload.get("notes")) or "Vital signs recorded", clinical_data_json=json.dumps(vitals), created_by=user.username)
    db.add(event); audit(db, user, "opd_triage_recorded", "care_episode", episode_id); db.commit()
    return {"message": "Triage saved and patient sent to Consulting Room", "bmi": vitals.get("bmi"), "status": episode.status}


@router.post("/episodes/{episode_id}/consultation", status_code=201)
def add_consultation(episode_id: str, payload: dict, user: User = Depends(care_allow("administrator", "clinician", "nutritionist_dietitian")), db: Session = Depends(get_db)):
    episode = require_local_episode(db, episode_id, user)
    assessment = clean(payload.get("assessment")); plan = clean(payload.get("plan")); disposition = clean(payload.get("disposition"), 60) or "Laboratory"
    if len(assessment) < 3 or len(plan) < 3 or disposition not in DEPARTMENTS | {"Completed", "Admit"}:
        raise HTTPException(422, "Assessment, plan and a valid next department are required")
    data = {"assessment": assessment, "plan": plan, "allergies": clean(payload.get("allergies"), 500), "disposition": disposition}
    if disposition == "Admit":
        ward=clean(payload.get("ward"),80)
        if ward not in WARDS: raise HTTPException(422,"Select the ward for admission")
        if db.scalar(select(WardAdmission).where(WardAdmission.episode_id==episode.episode_id,WardAdmission.status=="admitted")): raise HTTPException(409,"Patient already has an active ward admission")
        admission=WardAdmission(admission_id=str(uuid.uuid4()),episode_id=episode.episode_id,patient_code=episode.patient_code,facility=episode.facility,ward=ward,bed_number=clean(payload.get("bed_number"),30) or None,admission_reason=assessment,admitted_by=user.username)
        db.add(admission);episode.visit_type="Inpatient";episode.status="admitted";episode.assigned_department=ward
        claim=db.scalar(select(InsuranceClaim).where(InsuranceClaim.episode_id==episode.episode_id))
        if claim: claim.attendance_type="Inpatient";claim.status="draft";claim.updated_at=datetime.utcnow()
        db.add(CareEvent(event_id=str(uuid.uuid4()),episode_id=episode.episode_id,patient_code=episode.patient_code,facility=episode.facility,department=ward,event_type="ward_admission",summary=assessment,clinical_data_json=json.dumps({"bed_number":admission.bed_number}),created_by=user.username))
    else:
        episode.status = "in_care" if disposition != "Completed" else "awaiting_clearance"; episode.assigned_department = disposition if disposition != "Completed" else "Revenue"
    episode.updated_at = datetime.utcnow()
    db.add(CareEvent(event_id=str(uuid.uuid4()), episode_id=episode.episode_id, patient_code=episode.patient_code, facility=episode.facility, department="Consulting Room", event_type="consultation", summary=assessment, clinical_data_json=json.dumps(data), created_by=user.username))
    add_charge(db,episode,user,"Consulting Room",clean(payload.get("charge_description"),200) or "Consultation",payload,"consultation")
    audit(db, user, "consultation_recorded", "care_episode", episode_id, disposition); db.commit()
    return {"message": "Consultation saved", "status": episode.status, "next_department": disposition}


@router.post("/episodes/{episode_id}/laboratory", status_code=201)
def add_lab_result(episode_id: str, payload: dict, user: User = Depends(care_allow("administrator", "laboratory_officer")), db: Session = Depends(get_db)):
    episode = require_local_episode(db, episode_id, user)
    test_name, result = clean(payload.get("test_name"), 100), clean(payload.get("result"), 120)
    if not test_name or not result: raise HTTPException(422, "Test name and result are required")
    db.add(LaboratoryTest(test_id=str(uuid.uuid4()), encounter_id=episode.episode_id, patient_code=episode.patient_code, test_name=test_name, result=result, result_unit=clean(payload.get("unit"), 40) or None, created_by=user.username))
    episode.status = "in_care"; episode.assigned_department = clean(payload.get("next_department"), 60) or "Consulting Room"; episode.updated_at = datetime.utcnow()
    db.add(CareEvent(event_id=str(uuid.uuid4()), episode_id=episode.episode_id, patient_code=episode.patient_code, facility=episode.facility, department="Laboratory", event_type="result_available", summary=f"{test_name}: {result}", clinical_data_json=json.dumps({"test_name": test_name, "result": result, "unit": clean(payload.get("unit"), 40)}), created_by=user.username))
    add_charge(db,episode,user,"Laboratory",clean(payload.get("charge_description"),200) or test_name,payload,"laboratory",test_name)
    audit(db, user, "laboratory_result_recorded", "care_episode", episode_id, test_name); db.commit()
    return {"message": "Laboratory result saved", "next_department": episode.assigned_department}


@router.post("/episodes/{episode_id}/medications", status_code=201)
def prescribe(episode_id: str, payload: dict, user: User = Depends(care_allow("administrator", "clinician", "nutritionist_dietitian", "ward_nurse", "midwife")), db: Session = Depends(get_db)):
    episode = require_local_episode(db, episode_id, user); medicine, instructions = clean(payload.get("medicine"), 160), clean(payload.get("instructions"))
    if not medicine or not instructions: raise HTTPException(422, "Medicine and instructions are required")
    row = MedicationOrder(order_id=str(uuid.uuid4()), episode_id=episode_id, patient_code=episode.patient_code, facility=episode.facility, medicine=medicine, instructions=instructions, prescribed_by=user.username)
    db.add(row); episode.assigned_department = "Pharmacy"; episode.status = "in_care"; episode.updated_at = datetime.utcnow()
    db.add(CareEvent(event_id=str(uuid.uuid4()), episode_id=episode_id, patient_code=episode.patient_code, facility=episode.facility, department="Consulting Room", event_type="medication_prescribed", summary=medicine, clinical_data_json=json.dumps({"instructions": instructions}), created_by=user.username))
    add_charge(db,episode,user,"Pharmacy",clean(payload.get("charge_description"),200) or medicine,payload,"medication",row.order_id)
    audit(db, user, "medication_prescribed", "medication_order", row.order_id, medicine); db.commit()
    return {"order_id": row.order_id, "status": row.status}


@router.get("/medications")
def list_medications(user: User = Depends(care_allow("administrator", "pharmacist")), db: Session = Depends(get_db)):
    facility = facility_for(user)
    rows = db.scalars(select(MedicationOrder).where(MedicationOrder.facility == facility).order_by(MedicationOrder.created_at.desc()).limit(200)).all()
    return [{"order_id": row.order_id, "episode_id": row.episode_id, "patient_code": row.patient_code, "medicine": row.medicine, "instructions": row.instructions, "status": row.status, "prescribed_by": row.prescribed_by} for row in rows]


@router.patch("/medications/{order_id}/dispense")
def dispense(order_id: str, user: User = Depends(care_allow("administrator", "pharmacist")), db: Session = Depends(get_db)):
    row = db.scalar(select(MedicationOrder).where(MedicationOrder.order_id == order_id))
    if not row: raise HTTPException(404, "Medication order not found")
    if user.role != "administrator" and row.facility.casefold() != facility_for(user).casefold(): raise HTTPException(403, "This order belongs to another facility")
    row.status = "dispensed"; row.dispensed_by = user.username; row.dispensed_at = datetime.utcnow()
    episode = db.scalar(select(CareEpisode).where(CareEpisode.episode_id == row.episode_id))
    if episode: episode.status = "awaiting_clearance"; episode.assigned_department = "Revenue"; episode.updated_at = datetime.utcnow()
    db.add(CareEvent(event_id=str(uuid.uuid4()), episode_id=row.episode_id, patient_code=row.patient_code, facility=row.facility, department="Pharmacy", event_type="medication_dispensed", summary=row.medicine, clinical_data_json="{}", created_by=user.username))
    audit(db, user, "medication_dispensed", "medication_order", order_id, row.medicine); db.commit()
    return {"order_id": order_id, "status": row.status}


@router.get("/wards")
def list_wards(user: User = Depends(care_allow("administrator", "clinician", "ward_nurse", "midwife", "theatre_staff")), db: Session = Depends(get_db)):
    facility=facility_for(user)
    rows=db.scalars(select(WardAdmission).where(WardAdmission.facility==facility,WardAdmission.status=="admitted").order_by(WardAdmission.admitted_at.desc())).all()
    return {"wards":[{"ward":ward,"occupied":sum(1 for row in rows if row.ward==ward)} for ward in sorted(WARDS)],"admissions":[{"admission_id":r.admission_id,"episode_id":r.episode_id,"patient_code":r.patient_code,"ward":r.ward,"bed_number":r.bed_number,"reason":r.admission_reason,"status":r.status,"admitted_at":r.admitted_at.isoformat()} for r in rows]}


@router.post("/wards/admissions",status_code=201)
def admit_patient(payload:dict,user:User=Depends(care_allow("administrator","clinician","ward_nurse","midwife","theatre_staff")),db:Session=Depends(get_db)):
    episode=require_local_episode(db,clean(payload.get("episode_id"),36),user); ward=clean(payload.get("ward"),80); reason=clean(payload.get("admission_reason"))
    if ward not in WARDS or len(reason)<3: raise HTTPException(422,"Select a valid ward and record the admission reason")
    active=db.scalar(select(WardAdmission).where(WardAdmission.episode_id==episode.episode_id,WardAdmission.status=="admitted"))
    if active: raise HTTPException(409,"This care episode already has an active ward admission")
    row=WardAdmission(admission_id=str(uuid.uuid4()),episode_id=episode.episode_id,patient_code=episode.patient_code,facility=episode.facility,ward=ward,bed_number=clean(payload.get("bed_number"),30) or None,admission_reason=reason,admitted_by=user.username)
    db.add(row);episode.status="admitted";episode.assigned_department=ward;episode.updated_at=datetime.utcnow()
    episode.visit_type="Inpatient";claim=db.scalar(select(InsuranceClaim).where(InsuranceClaim.episode_id==episode.episode_id))
    if claim: claim.attendance_type="Inpatient";claim.status="draft";claim.updated_at=datetime.utcnow()
    add_charge(db,episode,user,ward,clean(payload.get("charge_description"),200) or f"Admission - {ward}",payload,"ward_admission",row.admission_id)
    db.add(CareEvent(event_id=str(uuid.uuid4()),episode_id=episode.episode_id,patient_code=episode.patient_code,facility=episode.facility,department=ward,event_type="ward_admission",summary=reason,clinical_data_json=json.dumps({"bed_number":row.bed_number}),created_by=user.username));audit(db,user,"ward_admission_created","ward_admission",row.admission_id,ward);db.commit()
    return {"admission_id":row.admission_id,"patient_code":row.patient_code,"ward":ward,"status":row.status}


@router.patch("/wards/admissions/{admission_id}/discharge")
def discharge_patient(admission_id:str,payload:dict,user:User=Depends(care_allow("administrator","clinician","ward_nurse","midwife")),db:Session=Depends(get_db)):
    row=db.scalar(select(WardAdmission).where(WardAdmission.admission_id==admission_id));summary=clean(payload.get("discharge_summary"))
    if not row: raise HTTPException(404,"Ward admission not found")
    if user.role!="administrator" and row.facility.casefold()!=facility_for(user).casefold(): raise HTTPException(403,"This admission belongs to another facility")
    if len(summary)<5: raise HTTPException(422,"Record a discharge or transfer summary")
    row.status="discharged";row.discharge_summary=summary;row.discharged_at=datetime.utcnow();episode=db.scalar(select(CareEpisode).where(CareEpisode.episode_id==row.episode_id))
    if episode: episode.status="awaiting_clearance";episode.assigned_department="Revenue";episode.updated_at=datetime.utcnow()
    audit(db,user,"ward_discharge_recorded","ward_admission",admission_id,row.ward);db.commit();return {"admission_id":admission_id,"status":"discharged"}


@router.get("/anc")
def list_anc(user:User=Depends(care_allow("administrator","clinician","midwife","nutritionist_dietitian")),db:Session=Depends(get_db)):
    facility=facility_for(user);rows=db.scalars(select(AncVisit).where(AncVisit.facility==facility).order_by(AncVisit.created_at.desc()).limit(100)).all()
    return [{"anc_id":r.anc_id,"patient_code":r.patient_code,"gestational_age_weeks":r.gestational_age_weeks,"blood_pressure":f"{r.systolic}/{r.diastolic}" if r.systolic and r.diastolic else None,"haemoglobin_g_dl":r.haemoglobin_g_dl,"next_visit_date":r.next_visit_date,"created_at":r.created_at.isoformat()} for r in rows]


@router.post("/anc",status_code=201)
def record_anc(payload:dict,user:User=Depends(care_allow("administrator","clinician","midwife","nutritionist_dietitian")),db:Session=Depends(get_db)):
    episode=require_local_episode(db,clean(payload.get("episode_id"),36),user);plan=clean(payload.get("plan"))
    if len(plan)<3: raise HTTPException(422,"Record the ANC assessment plan")
    row=AncVisit(anc_id=str(uuid.uuid4()),episode_id=episode.episode_id,patient_code=episode.patient_code,facility=episode.facility,gestational_age_weeks=payload.get("gestational_age_weeks"),gravida=payload.get("gravida"),parity=payload.get("parity"),systolic=payload.get("systolic"),diastolic=payload.get("diastolic"),haemoglobin_g_dl=payload.get("haemoglobin_g_dl"),fetal_heart_rate=payload.get("fetal_heart_rate"),danger_signs=clean(payload.get("danger_signs")),plan=plan,next_visit_date=clean(payload.get("next_visit_date"),10) or None,recorded_by=user.username)
    db.add(row);episode.assigned_department="ANC";episode.status="in_care";episode.updated_at=datetime.utcnow();audit(db,user,"anc_visit_recorded","anc_visit",row.anc_id);db.commit();return {"anc_id":row.anc_id,"patient_code":row.patient_code,"status":"recorded"}


@router.get("/stores")
def list_inventory(user:User=Depends(care_allow("administrator","stores_officer","pharmacist","accountant")),db:Session=Depends(get_db)):
    rows=db.scalars(select(InventoryItem).where(InventoryItem.facility==facility_for(user)).order_by(InventoryItem.item_name)).all()
    return [{"item_id":r.item_id,"item_name":r.item_name,"category":r.category,"quantity":r.quantity,"reorder_level":r.reorder_level,"unit":r.unit,"batch_number":r.batch_number,"expiry_date":r.expiry_date,"low_stock":r.quantity<=r.reorder_level} for r in rows]


@router.post("/stores",status_code=201)
def save_inventory(payload:dict,user:User=Depends(care_allow("administrator","stores_officer")),db:Session=Depends(get_db)):
    name=clean(payload.get("item_name"),160);category=clean(payload.get("category"),80);quantity=payload.get("quantity");reorder=payload.get("reorder_level",0)
    if not name or not category or not isinstance(quantity,int) or quantity<0 or not isinstance(reorder,int) or reorder<0: raise HTTPException(422,"Enter a valid item, category, quantity and reorder level")
    row=InventoryItem(item_id=str(uuid.uuid4()),facility=facility_for(user),item_name=name,category=category,quantity=quantity,reorder_level=reorder,unit=clean(payload.get("unit"),40) or "unit",batch_number=clean(payload.get("batch_number"),80) or None,expiry_date=clean(payload.get("expiry_date"),10) or None,updated_by=user.username)
    db.add(row);audit(db,user,"inventory_item_created","inventory_item",row.item_id,name);db.commit();return {"item_id":row.item_id,"status":"saved"}


@router.get("/finance/transactions")
def list_revenue(user:User=Depends(care_allow("administrator","revenue_officer","accountant")),db:Session=Depends(get_db)):
    rows=db.scalars(select(RevenueTransaction).where(RevenueTransaction.facility==facility_for(user)).order_by(RevenueTransaction.created_at.desc()).limit(300)).all()
    return [{"transaction_id":r.transaction_id,"receipt_number":r.receipt_number,"patient_code":r.patient_code,"service":r.service,"amount":r.amount,"payment_method":r.payment_method,"status":r.status,"collected_by":r.collected_by,"created_at":r.created_at.isoformat()} for r in rows]


@router.post("/finance/transactions",status_code=201)
def collect_revenue(payload:dict,user:User=Depends(care_allow("administrator","revenue_officer")),db:Session=Depends(get_db)):
    service=clean(payload.get("service"),160);method=clean(payload.get("payment_method"),40)
    try: amount=float(payload.get("amount"))
    except (TypeError,ValueError): raise HTTPException(422,"Enter a valid amount")
    if not service or amount<=0 or method not in {"Cash","Mobile Money","Card","Bank","Insurance","Other"}: raise HTTPException(422,"Enter a valid service, positive amount and payment method")
    receipt="HSR-"+datetime.utcnow().strftime("%Y%m%d")+"-"+secrets.token_hex(3).upper();row=RevenueTransaction(transaction_id=str(uuid.uuid4()),receipt_number=receipt,episode_id=clean(payload.get("episode_id"),36) or None,patient_code=clean(payload.get("patient_code"),64).upper() or None,facility=facility_for(user),service=service,amount=amount,payment_method=method,collected_by=user.username,notes=clean(payload.get("notes")))
    db.add(row);audit(db,user,"revenue_collected","revenue_transaction",row.transaction_id,f"{receipt}; amount={amount:.2f}");db.commit();return {"transaction_id":row.transaction_id,"receipt_number":receipt,"status":"paid","amount":amount}


@router.get("/finance/summary")
def finance_summary(user:User=Depends(care_allow("administrator","accountant")),db:Session=Depends(get_db)):
    rows=db.scalars(select(RevenueTransaction).where(RevenueTransaction.facility==facility_for(user),RevenueTransaction.status=="paid")).all();by_method={}
    for r in rows: by_method[r.payment_method]=round(by_method.get(r.payment_method,0)+r.amount,2)
    return {"transaction_count":len(rows),"total_revenue":round(sum(r.amount for r in rows),2),"by_payment_method":[{"method":k,"amount":v} for k,v in sorted(by_method.items())]}


@router.get("/billing/episodes/{episode_id}")
def get_episode_bill(episode_id:str,user:User=Depends(care_allow("administrator","records_officer","revenue_officer","accountant","insurance_officer","clinician","ward_nurse","pharmacist")),db:Session=Depends(get_db)):
    episode=require_local_episode(db,episode_id,user);return bill_snapshot(db,episode)


@router.post("/billing/charges",status_code=201)
def create_service_charge(payload:dict,user:User=Depends(care_allow("administrator","records_officer","clinician","laboratory_officer","pharmacist","ward_nurse","midwife","theatre_staff","revenue_officer")),db:Session=Depends(get_db)):
    episode=require_local_episode(db,clean(payload.get("episode_id"),36),user)
    area,description=clean(payload.get("service_area"),80),clean(payload.get("description"),200)
    if area not in DEPARTMENTS or len(description)<2: raise HTTPException(422,"Choose a valid service area and description")
    row=add_charge(db,episode,user,area,description,payload,"manual")
    if not row: raise HTTPException(422,"Charge amount must be greater than zero")
    audit(db,user,"service_charge_created","service_charge",row.charge_id,f"{area}; GHS {row.amount:.2f}; {row.payer}");db.commit()
    return {"charge_id":row.charge_id,"status":row.status,"payer":row.payer,"amount":row.amount}


@router.post("/billing/episodes/{episode_id}/pay")
def pay_episode_bill(episode_id:str,payload:dict,user:User=Depends(care_allow("administrator","revenue_officer")),db:Session=Depends(get_db)):
    episode=require_local_episode(db,episode_id,user)
    method=clean(payload.get("payment_method"),40)
    if method not in {"Cash","Mobile Money","Card","Bank","Other"}: raise HTTPException(422,"Select a valid patient payment method")
    due=db.scalars(select(ServiceCharge).where(ServiceCharge.episode_id==episode_id,ServiceCharge.payer=="patient",ServiceCharge.status=="patient_due").order_by(ServiceCharge.created_at)).all()
    if not due: raise HTTPException(409,"This episode has no outstanding patient charges")
    total=round(sum(x.amount for x in due),2);receipt="HSR-"+datetime.utcnow().strftime("%Y%m%d")+"-"+secrets.token_hex(3).upper()
    for charge in due: charge.status="paid";charge.settled_at=datetime.utcnow()
    db.add(RevenueTransaction(transaction_id=str(uuid.uuid4()),receipt_number=receipt,episode_id=episode_id,patient_code=episode.patient_code,facility=episode.facility,service="Episode bill",amount=total,payment_method=method,collected_by=user.username,notes=clean(payload.get("notes"))))
    audit(db,user,"episode_bill_paid","care_episode",episode_id,f"{receipt}; GHS {total:.2f}");db.commit()
    return {"receipt_number":receipt,"amount":total,"status":"paid","bill":bill_snapshot(db,episode)}


@router.post("/billing/episodes/{episode_id}/clear")
def clear_episode(episode_id:str,user:User=Depends(care_allow("administrator","revenue_officer","insurance_officer")),db:Session=Depends(get_db)):
    episode=require_local_episode(db,episode_id,user);bill=bill_snapshot(db,episode)
    if not bill["financially_cleared"]: raise HTTPException(409,"Outstanding patient payment or insurance claim items remain")
    episode.status="completed";episode.assigned_department="Completed";episode.updated_at=datetime.utcnow()
    db.add(CareEvent(event_id=str(uuid.uuid4()),episode_id=episode_id,patient_code=episode.patient_code,facility=episode.facility,department="Revenue",event_type="financial_clearance",summary="Episode financially cleared",clinical_data_json="{}",created_by=user.username))
    audit(db,user,"episode_financially_cleared","care_episode",episode_id);db.commit();return {"episode_id":episode_id,"status":"completed","financially_cleared":True}


@router.get("/reports/monthly")
def monthly_hospital_report(month:str=Query(...,pattern=r"^\d{4}-\d{2}$"),user:User=Depends(care_allow("administrator","data_officer","accountant")),db:Session=Depends(get_db)):
    facility=facility_for(user);start,end=month_window(month);episodes=db.scalars(select(CareEpisode).where(CareEpisode.facility==facility,CareEpisode.visit_date.like(f"{month}%"))).all()
    ids=[x.episode_id for x in episodes];admissions=db.scalars(select(WardAdmission).where(WardAdmission.facility==facility,WardAdmission.admitted_at>=start,WardAdmission.admitted_at<end)).all()
    events=db.scalars(select(CareEvent).where(CareEvent.facility==facility,CareEvent.created_at>=start,CareEvent.created_at<end)).all()
    by_type={};by_status={};by_ward={}
    for x in episodes: by_type[x.visit_type]=by_type.get(x.visit_type,0)+1;by_status[x.status]=by_status.get(x.status,0)+1
    for x in admissions:
        if x.episode_id in ids: by_ward[x.ward]=by_ward.get(x.ward,0)+1
    return {"month":month,"facility":facility,"total_visits":len(episodes),"by_visit_type":by_type,"by_status":by_status,"ward_admissions":by_ward,"laboratory_results":sum(e.event_type=="result_available" for e in events if e.episode_id in ids),"prescriptions":sum(e.event_type=="medication_prescribed" for e in events if e.episode_id in ids),"completed":sum(x.status=="completed" for x in episodes)}


@router.get("/reports/financial")
def monthly_financial_report(month:str=Query(...,pattern=r"^\d{4}-\d{2}$"),user:User=Depends(care_allow("administrator","accountant","revenue_officer")),db:Session=Depends(get_db)):
    facility=facility_for(user);start,end=month_window(month);rows=db.scalars(select(ServiceCharge).where(ServiceCharge.facility==facility,ServiceCharge.created_at>=start,ServiceCharge.created_at<end)).all();paid=db.scalars(select(RevenueTransaction).where(RevenueTransaction.facility==facility,RevenueTransaction.created_at>=start,RevenueTransaction.created_at<end)).all()
    return {"month":month,"facility":facility,"billed":round(sum(x.amount for x in rows),2),"patient_billed":round(sum(x.amount for x in rows if x.payer=="patient"),2),"insurance_billed":round(sum(x.amount for x in rows if x.payer=="insurance"),2),"patient_collected":round(sum(x.amount for x in paid if x.payment_method!="Insurance"),2),"insurance_claimed":round(sum(x.amount for x in rows if x.payer=="insurance" and x.status=="claimed"),2),"outstanding":round(sum(x.amount for x in rows if x.status in {"patient_due","insurance_pending"}),2),"transactions":len(paid)}


@router.get("/reports/system-usage")
def system_usage_report(month:str=Query(...,pattern=r"^\d{4}-\d{2}$"),user:User=Depends(care_allow("administrator","data_officer")),db:Session=Depends(get_db)):
    start,end=month_window(month);facility=facility_for(user);facility_users=set(db.scalars(select(User.username).where(User.facility==facility)).all());facility_users.add(user.username);rows=db.scalars(select(AuditLog).where(AuditLog.created_at>=start,AuditLog.created_at<end,AuditLog.actor.in_(facility_users)).order_by(AuditLog.created_at.desc()).limit(5000)).all();usage={}
    for x in rows:
        item=usage.setdefault(x.actor,{"total_actions":0,"actions":{}});item["total_actions"]+=1;item["actions"][x.action]=item["actions"].get(x.action,0)+1
    return {"month":month,"users":[{"username":name,**data} for name,data in sorted(usage.items())]}


@router.get("/insurance/claims")
def list_insurance_claims(user:User=Depends(care_allow("administrator","records_officer","insurance_officer","accountant")),db:Session=Depends(get_db)):
    rows=db.scalars(select(InsuranceClaim).where(InsuranceClaim.facility==facility_for(user)).order_by(InsuranceClaim.created_at.desc()).limit(300)).all()
    return [{"claim_id":r.claim_id,"episode_id":r.episode_id,"patient_code":r.patient_code,"member_number":r.member_number,"ccc_number":r.ccc_number,"status":r.status,"created_at":r.created_at.isoformat(),"updated_at":r.updated_at.isoformat()} for r in rows]


@router.get("/insurance/claims/{claim_id}")
def get_insurance_claim(claim_id:str,user:User=Depends(care_allow("administrator","records_officer","insurance_officer","accountant")),db:Session=Depends(get_db)):
    row=db.scalar(select(InsuranceClaim).where(InsuranceClaim.claim_id==claim_id))
    if not row: raise HTTPException(404,"Insurance claim not found")
    if user.role!="administrator" and row.facility.casefold()!=facility_for(user).casefold(): raise HTTPException(403,"This claim belongs to another facility")
    audit(db,user,"insurance_claim_viewed","insurance_claim",claim_id);db.commit();return claim_snapshot(db,row)


@router.patch("/insurance/claims/{claim_id}")
def update_insurance_claim(claim_id:str,payload:dict,user:User=Depends(care_allow("administrator","insurance_officer")),db:Session=Depends(get_db)):
    row=db.scalar(select(InsuranceClaim).where(InsuranceClaim.claim_id==claim_id))
    if not row: raise HTTPException(404,"Insurance claim not found")
    if user.role!="administrator" and row.facility.casefold()!=facility_for(user).casefold(): raise HTTPException(403,"This claim belongs to another facility")
    fields={"member_number":80,"ccc_number":80,"surname":120,"other_names":180,"gender":20,"date_of_birth":10,"folder_number":80,"attendance_type":40,"specialty":20,"service_outcome":40,"referring_facility":160,"referral_code":80,"physician_name_id":160,"pre_authorization_codes":500,"principal_gdrg":80}
    for field,limit in fields.items():
        if field in payload: setattr(row,field,clean(payload.get(field),limit) or None)
    if "manual_entries" in payload:
        entries=payload.get("manual_entries")
        if not isinstance(entries,list) or len(entries)>100: raise HTTPException(422,"Manual claim entries must be a list of no more than 100 items")
        allowed={"procedure","diagnosis","investigation","medicine"};normalized=[]
        for entry in entries:
            if not isinstance(entry,dict) or entry.get("type") not in allowed or len(clean(entry.get("description"),300))<2: raise HTTPException(422,"Each claim entry requires a valid type and description")
            normalized.append({"type":entry["type"],"code":clean(entry.get("code"),80),"description":clean(entry.get("description"),300),"quantity":entry.get("quantity"),"unit_cost":entry.get("unit_cost"),"source":"Insurance desk"})
        row.manual_entries_json=json.dumps(normalized)
    row.status="draft";row.validation_json="[]";row.updated_at=datetime.utcnow();audit(db,user,"insurance_claim_updated","insurance_claim",claim_id);db.commit();return claim_snapshot(db,row)


@router.post("/insurance/claims/{claim_id}/validate")
def validate_insurance_claim(claim_id:str,user:User=Depends(care_allow("administrator","insurance_officer")),db:Session=Depends(get_db)):
    row=db.scalar(select(InsuranceClaim).where(InsuranceClaim.claim_id==claim_id))
    if not row: raise HTTPException(404,"Insurance claim not found")
    if user.role!="administrator" and row.facility.casefold()!=facility_for(user).casefold(): raise HTTPException(403,"This claim belongs to another facility")
    snapshot=claim_snapshot(db,row);errors=validate_claim(snapshot);row.validation_json=json.dumps(errors);row.status="needs_correction" if errors else "ready_for_export";row.reviewed_by=user.username;row.updated_at=datetime.utcnow();audit(db,user,"insurance_claim_validated","insurance_claim",claim_id,f"errors={len(errors)}");db.commit();return {"claim_id":claim_id,"status":row.status,"errors":errors}


@router.get("/insurance/claims/{claim_id}/xml")
def export_insurance_claim_xml(claim_id:str,user:User=Depends(care_allow("administrator","insurance_officer")),db:Session=Depends(get_db)):
    row=db.scalar(select(InsuranceClaim).where(InsuranceClaim.claim_id==claim_id))
    if not row: raise HTTPException(404,"Insurance claim not found")
    if user.role!="administrator" and row.facility.casefold()!=facility_for(user).casefold(): raise HTTPException(403,"This claim belongs to another facility")
    snapshot=claim_snapshot(db,row);errors=validate_claim(snapshot)
    if errors: raise HTTPException(422,"Validate and correct the claim before XML export: "+"; ".join(errors))
    root=ET.Element("HealthSignalNHISClaim",{"interface":"NHIA-standardized-eclaims","schemaStatus":"MVP-pending-NHIA-certification"})
    def add(parent,name,value): ET.SubElement(parent,name).text=str(value or "")
    provider=ET.SubElement(root,"Provider");add(provider,"FacilityName",snapshot["facility"])
    member=ET.SubElement(root,"MemberDetails")
    for tag,key in (("MemberNoHIN","member_number"),("CCCNo","ccc_number"),("Surname","surname"),("OtherNames","other_names"),("Gender","gender"),("DateOfBirth","date_of_birth"),("FolderNo","folder_number")): add(member,tag,snapshot.get(key))
    service=ET.SubElement(root,"Service");add(service,"VisitDate",snapshot.get("visit_date"));add(service,"AttendanceType",snapshot.get("attendance_type"));add(service,"Outcome",snapshot.get("service_outcome"));add(service,"Specialty",snapshot.get("specialty"));add(service,"PrincipalGDRG",snapshot.get("principal_gdrg"))
    types=ET.SubElement(service,"ServiceTypes")
    for value in snapshot["service_types"]: add(types,"Type",value)
    dates=ET.SubElement(service,"DatesOfService")
    for value in snapshot["service_dates"]: add(dates,"Date",value)
    referral=ET.SubElement(root,"ReferralInfo");add(referral,"ReferringFacility",snapshot.get("referring_facility"));add(referral,"ReferralCodeCCC",snapshot.get("referral_code"))
    authorization=ET.SubElement(root,"AuthorizationCodes");add(authorization,"PhysicianNameID",snapshot.get("physician_name_id"));add(authorization,"PreAuthorizationCodes",snapshot.get("pre_authorization_codes"))
    for section,key in (("Procedures","procedures"),("Diagnoses","diagnoses"),("Investigations","investigations"),("Medicines","medicines")):
        parent=ET.SubElement(root,section)
        for item in snapshot[key]:
            entry=ET.SubElement(parent,section[:-1] if section.endswith("s") else "Entry")
            for field,value in item.items(): add(entry,field.replace("_","").title(),value)
    ET.indent(root);content=ET.tostring(root,encoding="utf-8",xml_declaration=True)
    for charge in db.scalars(select(ServiceCharge).where(ServiceCharge.episode_id==row.episode_id,ServiceCharge.payer=="insurance",ServiceCharge.status=="insurance_pending")).all(): charge.status="claimed";charge.settled_at=datetime.utcnow()
    row.status="exported";row.updated_at=datetime.utcnow();audit(db,user,"insurance_claim_xml_exported","insurance_claim",claim_id,"Pending official NHIA schema certification");db.commit()
    return Response(content=content,media_type="application/xml",headers={"Content-Disposition":f'attachment; filename="healthsignal-claim-{claim_id[:8]}.xml"'})


@router.post("/referrals", status_code=201)
def create_network_referral(payload: dict, user: User = Depends(care_allow("administrator", "clinician", "nutritionist_dietitian")), db: Session = Depends(get_db)):
    episode = require_local_episode(db, clean(payload.get("episode_id"), 36), user)
    destination, reason, summary = clean(payload.get("destination_facility"), 160), clean(payload.get("reason")), clean(payload.get("clinical_summary"))
    urgency = clean(payload.get("urgency"), 20) or "routine"
    if not destination or destination.casefold() == episode.facility.casefold(): raise HTTPException(422, "Choose a different receiving facility")
    if len(reason) < 3 or len(summary) < 10: raise HTTPException(422, "Referral reason and clinical summary are required")
    if urgency not in {"routine", "urgent", "emergency"}: raise HTTPException(422, "Invalid referral urgency")
    if payload.get("consent_confirmed") is not True: raise HTTPException(422, "Patient consent or an approved lawful basis must be confirmed")
    scopes={clean(x,40) for x in payload.get("consent_scopes", [])} & SHAREABLE_SCOPES
    if "care_summary" not in scopes: scopes.add("care_summary")
    consent_type=clean(payload.get("consent_type"),40) or "patient"
    if consent_type not in {"patient","guardian","lawful_basis"}: raise HTTPException(422,"Invalid consent type")
    receiving_department=clean(payload.get("receiving_department"),60) or "Consulting Room"
    if receiving_department not in DEPARTMENTS: raise HTTPException(422,"Invalid receiving department")
    try: validity_hours=int(payload.get("validity_hours",168))
    except (TypeError,ValueError): raise HTTPException(422,"Invalid referral validity")
    if validity_hours not in {24,72,168}: raise HTTPException(422,"Referral validity must be 24 hours, 72 hours or 7 days")
    access_code = secrets.token_hex(3).upper()
    row = NetworkReferral(referral_id=str(uuid.uuid4()), episode_id=episode.episode_id, patient_code=episode.patient_code, source_facility=episode.facility, destination_facility=destination, access_code_hash=hashlib.sha256(access_code.encode()).hexdigest(), reason=reason, urgency=urgency, clinical_summary=summary, status="sent", consent_confirmed=True, consent_type=consent_type, consent_scope_json=json.dumps(sorted(scopes)), consent_recorded_at=datetime.utcnow(), receiving_department=receiving_department, expires_at=datetime.utcnow()+timedelta(hours=validity_hours), created_by=user.username)
    db.add(row); db.add(NetworkReferralEvent(referral_id=row.referral_id, actor=user.username, facility=episode.facility, action="sent", details=destination)); episode.status = "referred"; episode.assigned_department = "Referral"; episode.updated_at = datetime.utcnow()
    audit(db, user, "network_referral_sent", "network_referral", row.referral_id, f"{episode.facility} to {destination}"); db.commit()
    return {**referral_json(row, True), "access_code": access_code, "access_code_notice": "Share this time limited code with the patient or authorized receiving team. It will not be displayed again."}


@router.get("/referrals")
def list_network_referrals(user: User = Depends(care_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user)
    rows = db.scalars(select(NetworkReferral).where(or_(NetworkReferral.source_facility == facility, NetworkReferral.destination_facility == facility)).order_by(NetworkReferral.created_at.desc()).limit(200)).all()
    return [referral_json(row, row.source_facility == facility or user.role == "administrator") for row in rows]


@router.post("/referrals/access")
def access_referral(payload: dict, user: User = Depends(care_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user)
    if user.role not in REFERRAL_ACCESS_ROLES: raise HTTPException(403,"Your role cannot open a clinical referral handover")
    patient_code, access_code, reason = clean(payload.get("patient_code"), 64).upper(), clean(payload.get("access_code"), 20).upper(), clean(payload.get("access_reason"), 500)
    if len(reason) < 5: raise HTTPException(422, "State why this record is being accessed")
    row = db.scalar(select(NetworkReferral).where(NetworkReferral.patient_code == patient_code, NetworkReferral.destination_facility == facility, NetworkReferral.status.in_(["sent", "accepted", "arrived", "in_care"])).order_by(NetworkReferral.created_at.desc()))
    valid = row and secrets.compare_digest(row.access_code_hash, hashlib.sha256(access_code.encode()).hexdigest())
    if not valid or row.expires_at < datetime.utcnow() or row.consent_revoked_at is not None:
        audit(db, user, "network_referral_access_denied", "patient", patient_code, reason); db.commit()
        raise HTTPException(403, "Referral details could not be verified")
    packet=referral_packet(db,row,user,reason)
    audit(db, user, "network_referral_record_accessed", "network_referral", row.referral_id, f"{reason}; scopes={','.join(packet['shared_scopes'])}"); db.commit()
    return packet


@router.post("/referrals/emergency-access")
def emergency_referral_access(payload: dict, user: User = Depends(care_allow("administrator","clinician")), db: Session = Depends(get_db)):
    facility=facility_for(user); patient_code=clean(payload.get("patient_code"),64).upper(); reason=clean(payload.get("access_reason"),500)
    if payload.get("emergency_confirmed") is not True or len(reason)<20: raise HTTPException(422,"Confirm the emergency and provide a detailed clinical justification")
    row=db.scalar(select(NetworkReferral).where(NetworkReferral.patient_code==patient_code,NetworkReferral.destination_facility==facility).order_by(NetworkReferral.created_at.desc()))
    if not row: audit(db,user,"emergency_referral_access_denied","patient",patient_code,reason); db.commit(); raise HTTPException(404,"No referral addressed to this facility")
    packet=referral_packet(db,row,user,reason,True)
    db.add(NetworkReferralEvent(referral_id=row.referral_id,actor=user.username,facility=facility,action="emergency_access",details=reason))
    audit(db,user,"emergency_referral_access_granted","network_referral",row.referral_id,reason); db.commit()
    return packet


@router.post("/referrals/{referral_id}/revoke-consent")
def revoke_referral_consent(referral_id: str, payload: dict, user: User = Depends(care_allow("administrator","clinician")), db: Session = Depends(get_db)):
    row=db.scalar(select(NetworkReferral).where(NetworkReferral.referral_id==referral_id))
    if not row: raise HTTPException(404,"Referral not found")
    if user.role!="administrator" and row.source_facility.casefold()!=facility_for(user).casefold(): raise HTTPException(403,"Only the referring facility can record consent withdrawal")
    reason=clean(payload.get("reason"),500)
    if len(reason)<5: raise HTTPException(422,"Record the reason for consent withdrawal")
    row.consent_revoked_at=datetime.utcnow()
    for grant in db.scalars(select(ReferralAccessGrant).where(ReferralAccessGrant.referral_id==referral_id)).all(): grant.revoked=True
    db.add(NetworkReferralEvent(referral_id=referral_id,actor=user.username,facility=facility_for(user),action="consent_revoked",details=reason)); audit(db,user,"referral_consent_revoked","network_referral",referral_id,reason); db.commit()
    return {"referral_id":referral_id,"consent_revoked":True}


@router.get("/referrals/{referral_id}/access-history")
def referral_access_history(referral_id: str, user: User = Depends(care_allow("administrator","clinician")), db: Session = Depends(get_db)):
    row=db.scalar(select(NetworkReferral).where(NetworkReferral.referral_id==referral_id))
    if not row: raise HTTPException(404,"Referral not found")
    facility=facility_for(user)
    if user.role!="administrator" and facility.casefold() not in {row.source_facility.casefold(),row.destination_facility.casefold()}: raise HTTPException(403,"This referral belongs to another care network")
    grants=db.scalars(select(ReferralAccessGrant).where(ReferralAccessGrant.referral_id==referral_id).order_by(ReferralAccessGrant.created_at.desc())).all()
    audit(db,user,"referral_access_history_viewed","network_referral",referral_id); db.commit()
    return [{"username":g.username,"facility":g.facility,"department":g.department,"purpose":g.purpose,"reason":g.access_reason,"emergency":g.emergency,"created_at":g.created_at.isoformat(),"expires_at":g.expires_at.isoformat()} for g in grants]


@router.patch("/referrals/{referral_id}")
def update_network_referral(referral_id: str, payload: dict, user: User = Depends(care_allow("administrator", "clinician", "nutritionist_dietitian", "field_officer")), db: Session = Depends(get_db)):
    row = db.scalar(select(NetworkReferral).where(NetworkReferral.referral_id == referral_id))
    if not row: raise HTTPException(404, "Referral not found")
    facility = facility_for(user); status = clean(payload.get("status"), 30)
    if status not in REFERRAL_STATES: raise HTTPException(422, "Invalid referral status")
    receiving_action = status in {"accepted", "arrived", "in_care", "completed", "redirected"}
    if user.role != "administrator" and receiving_action and row.destination_facility.casefold() != facility.casefold(): raise HTTPException(403, "Only the receiving facility can perform this action")
    if row.status == "completed": raise HTTPException(409, "Completed referrals cannot be changed")
    details = clean(payload.get("details"), 2000)
    if status == "completed" and len(details) < 5: raise HTTPException(422, "Referral feedback is required when care is completed")
    row.status = status
    if status == "accepted": row.accepted_by = user.username; row.accepted_at = datetime.utcnow()
    if status == "completed": row.feedback = details; row.completed_at = datetime.utcnow()
    db.add(NetworkReferralEvent(referral_id=row.referral_id, actor=user.username, facility=facility, action=status, details=details))
    audit(db, user, f"network_referral_{status}", "network_referral", referral_id, details[:500]); db.commit()
    return referral_json(row, True)


@router.get("/patients/{patient_code}/timeline")
def local_patient_timeline(patient_code: str, user: User = Depends(care_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user); patient_code = patient_code.upper()
    events = db.scalars(select(CareEvent).where(CareEvent.patient_code == patient_code, CareEvent.facility == facility).order_by(CareEvent.created_at)).all()
    if not events: raise HTTPException(404, "No local care history found")
    audit(db, user, "local_care_timeline_viewed", "patient", patient_code, facility); db.commit()
    return [{"department":event.department,"event_type":event.event_type,"summary":event.summary,"created_by":event.created_by,"created_at":event.created_at.isoformat()} for event in events]
