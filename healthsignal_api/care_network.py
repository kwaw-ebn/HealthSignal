import hashlib
import json
import math
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query
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
    NetworkReferral,
    NetworkReferralEvent,
    ReferralAccessGrant,
    Patient,
    User,
    get_db,
)

router = APIRouter(prefix="/api/v1/care-network", tags=["Care Network"])

CARE_ROLES = {"administrator", "clinician", "nutritionist_dietitian", "field_officer", "data_officer"}
CLINICAL_ROLES = {"administrator", "clinician", "nutritionist_dietitian"}
REFERRAL_STATES = {"sent", "accepted", "arrived", "in_care", "completed", "redirected"}
DEPARTMENTS = {"Records", "OPD", "Consulting Room", "Laboratory", "Pharmacy", "RCH", "Theatre", "Finance"}
SHAREABLE_SCOPES = {"demographics", "care_summary", "allergies", "vitals", "laboratory", "medications"}
REFERRAL_ACCESS_ROLES = {"administrator", "clinician", "nutritionist_dietitian"}


def clean(value, limit=3000):
    return str(value or "").strip()[:limit]


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
def register_episode(payload: dict, user: User = Depends(care_allow("administrator", "clinician", "nutritionist_dietitian", "field_officer")), db: Session = Depends(get_db)):
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
    db.add(CareEvent(event_id=str(uuid.uuid4()), episode_id=episode.episode_id, patient_code=patient_code, facility=facility, department="Records", event_type="registered", summary="Patient registered for care", clinical_data_json="{}", created_by=user.username))
    audit(db, user, "care_episode_registered", "care_episode", episode.episode_id, facility); db.commit()
    return episode_json(episode)


@router.get("/episodes")
def list_episodes(department: str | None = None, status: str | None = None, user: User = Depends(care_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user)
    stmt = select(CareEpisode).where(CareEpisode.facility == facility).order_by(CareEpisode.created_at.desc()).limit(300)
    if department: stmt = stmt.where(CareEpisode.assigned_department == department)
    if status: stmt = stmt.where(CareEpisode.status == status)
    return [episode_json(row) for row in db.scalars(stmt).all()]


@router.post("/episodes/{episode_id}/triage", status_code=201)
def add_triage(episode_id: str, payload: dict, user: User = Depends(care_allow("administrator", "clinician", "field_officer")), db: Session = Depends(get_db)):
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
    if len(assessment) < 3 or len(plan) < 3 or disposition not in DEPARTMENTS | {"Completed"}:
        raise HTTPException(422, "Assessment, plan and a valid next department are required")
    data = {"assessment": assessment, "plan": plan, "allergies": clean(payload.get("allergies"), 500), "disposition": disposition}
    episode.status = "in_care" if disposition != "Completed" else "completed"; episode.assigned_department = disposition; episode.updated_at = datetime.utcnow()
    db.add(CareEvent(event_id=str(uuid.uuid4()), episode_id=episode.episode_id, patient_code=episode.patient_code, facility=episode.facility, department="Consulting Room", event_type="consultation", summary=assessment, clinical_data_json=json.dumps(data), created_by=user.username))
    audit(db, user, "consultation_recorded", "care_episode", episode_id, disposition); db.commit()
    return {"message": "Consultation saved", "status": episode.status, "next_department": disposition}


@router.post("/episodes/{episode_id}/laboratory", status_code=201)
def add_lab_result(episode_id: str, payload: dict, user: User = Depends(care_allow("administrator", "clinician", "field_officer")), db: Session = Depends(get_db)):
    episode = require_local_episode(db, episode_id, user)
    test_name, result = clean(payload.get("test_name"), 100), clean(payload.get("result"), 120)
    if not test_name or not result: raise HTTPException(422, "Test name and result are required")
    db.add(LaboratoryTest(test_id=str(uuid.uuid4()), encounter_id=episode.episode_id, patient_code=episode.patient_code, test_name=test_name, result=result, result_unit=clean(payload.get("unit"), 40) or None, created_by=user.username))
    episode.status = "in_care"; episode.assigned_department = clean(payload.get("next_department"), 60) or "Consulting Room"; episode.updated_at = datetime.utcnow()
    db.add(CareEvent(event_id=str(uuid.uuid4()), episode_id=episode.episode_id, patient_code=episode.patient_code, facility=episode.facility, department="Laboratory", event_type="result_available", summary=f"{test_name}: {result}", clinical_data_json=json.dumps({"test_name": test_name, "result": result, "unit": clean(payload.get("unit"), 40)}), created_by=user.username))
    audit(db, user, "laboratory_result_recorded", "care_episode", episode_id, test_name); db.commit()
    return {"message": "Laboratory result saved", "next_department": episode.assigned_department}


@router.post("/episodes/{episode_id}/medications", status_code=201)
def prescribe(episode_id: str, payload: dict, user: User = Depends(care_allow("administrator", "clinician", "nutritionist_dietitian")), db: Session = Depends(get_db)):
    episode = require_local_episode(db, episode_id, user); medicine, instructions = clean(payload.get("medicine"), 160), clean(payload.get("instructions"))
    if not medicine or not instructions: raise HTTPException(422, "Medicine and instructions are required")
    row = MedicationOrder(order_id=str(uuid.uuid4()), episode_id=episode_id, patient_code=episode.patient_code, facility=episode.facility, medicine=medicine, instructions=instructions, prescribed_by=user.username)
    db.add(row); episode.assigned_department = "Pharmacy"; episode.status = "in_care"; episode.updated_at = datetime.utcnow()
    db.add(CareEvent(event_id=str(uuid.uuid4()), episode_id=episode_id, patient_code=episode.patient_code, facility=episode.facility, department="Consulting Room", event_type="medication_prescribed", summary=medicine, clinical_data_json=json.dumps({"instructions": instructions}), created_by=user.username))
    audit(db, user, "medication_prescribed", "medication_order", row.order_id, medicine); db.commit()
    return {"order_id": row.order_id, "status": row.status}


@router.get("/medications")
def list_medications(user: User = Depends(care_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user)
    rows = db.scalars(select(MedicationOrder).where(MedicationOrder.facility == facility).order_by(MedicationOrder.created_at.desc()).limit(200)).all()
    return [{"order_id": row.order_id, "episode_id": row.episode_id, "patient_code": row.patient_code, "medicine": row.medicine, "instructions": row.instructions, "status": row.status, "prescribed_by": row.prescribed_by} for row in rows]


@router.patch("/medications/{order_id}/dispense")
def dispense(order_id: str, user: User = Depends(care_allow("administrator", "clinician", "field_officer")), db: Session = Depends(get_db)):
    row = db.scalar(select(MedicationOrder).where(MedicationOrder.order_id == order_id))
    if not row: raise HTTPException(404, "Medication order not found")
    if user.role != "administrator" and row.facility.casefold() != facility_for(user).casefold(): raise HTTPException(403, "This order belongs to another facility")
    row.status = "dispensed"; row.dispensed_by = user.username; row.dispensed_at = datetime.utcnow()
    episode = db.scalar(select(CareEpisode).where(CareEpisode.episode_id == row.episode_id))
    if episode: episode.status = "completed"; episode.assigned_department = "Completed"; episode.updated_at = datetime.utcnow()
    db.add(CareEvent(event_id=str(uuid.uuid4()), episode_id=row.episode_id, patient_code=row.patient_code, facility=row.facility, department="Pharmacy", event_type="medication_dispensed", summary=row.medicine, clinical_data_json="{}", created_by=user.username))
    audit(db, user, "medication_dispensed", "medication_order", order_id, row.medicine); db.commit()
    return {"order_id": order_id, "status": row.status}


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
