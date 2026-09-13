import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .auth import allow, current_user
from .database import (
    AuditLog,
    CareEpisode,
    CareEvent,
    Facility,
    LaboratoryTest,
    MedicationOrder,
    NetworkReferral,
    NetworkReferralEvent,
    Patient,
    User,
    get_db,
)

router = APIRouter(prefix="/api/v1/care-network", tags=["Care Network"])

CARE_ROLES = {"administrator", "clinician", "nutritionist_dietitian", "field_officer", "data_officer"}
CLINICAL_ROLES = {"administrator", "clinician", "nutritionist_dietitian"}
REFERRAL_STATES = {"sent", "accepted", "arrived", "in_care", "completed", "redirected"}
DEPARTMENTS = {"Records", "OPD", "Consulting Room", "Laboratory", "Pharmacy", "RCH", "Theatre", "Finance"}


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
        "accepted_by": row.accepted_by,
        "feedback": row.feedback,
        "expires_at": row.expires_at.isoformat(),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
    }
    if include_summary:
        data["clinical_summary"] = row.clinical_summary
    return data


def require_local_episode(db, episode_id, user):
    episode = db.scalar(select(CareEpisode).where(CareEpisode.episode_id == episode_id))
    if not episode:
        raise HTTPException(404, "Care episode not found")
    if user.role != "administrator" and episode.facility.casefold() != facility_for(user).casefold():
        raise HTTPException(403, "This care episode belongs to another facility")
    return episode


@router.get("/overview")
def overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
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
def list_facilities(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_care_role(user)
    rows = db.scalars(select(Facility).where(Facility.active.is_(True)).order_by(Facility.name)).all()
    names = {row.name for row in rows}
    account_facilities = db.scalars(select(User.facility).where(User.facility.is_not(None), User.status == "approved")).all()
    result = [{"facility_id": row.facility_id, "name": row.name, "facility_type": row.facility_type, "district": row.district, "region": row.region} for row in rows]
    for name in sorted({clean(x, 160) for x in account_facilities if clean(x, 160)} - names):
        result.append({"facility_id": None, "name": name, "facility_type": "Registered facility", "district": "", "region": ""})
    return result


@router.post("/episodes", status_code=201)
def register_episode(payload: dict, user: User = Depends(allow("administrator", "clinician", "nutritionist_dietitian", "field_officer")), db: Session = Depends(get_db)):
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
def list_episodes(department: str | None = None, status: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user)
    stmt = select(CareEpisode).where(CareEpisode.facility == facility).order_by(CareEpisode.created_at.desc()).limit(300)
    if department: stmt = stmt.where(CareEpisode.assigned_department == department)
    if status: stmt = stmt.where(CareEpisode.status == status)
    return [episode_json(row) for row in db.scalars(stmt).all()]


@router.post("/episodes/{episode_id}/triage", status_code=201)
def add_triage(episode_id: str, payload: dict, user: User = Depends(allow("administrator", "clinician", "field_officer")), db: Session = Depends(get_db)):
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
def add_consultation(episode_id: str, payload: dict, user: User = Depends(allow("administrator", "clinician", "nutritionist_dietitian")), db: Session = Depends(get_db)):
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
def add_lab_result(episode_id: str, payload: dict, user: User = Depends(allow("administrator", "clinician", "field_officer")), db: Session = Depends(get_db)):
    episode = require_local_episode(db, episode_id, user)
    test_name, result = clean(payload.get("test_name"), 100), clean(payload.get("result"), 120)
    if not test_name or not result: raise HTTPException(422, "Test name and result are required")
    db.add(LaboratoryTest(test_id=str(uuid.uuid4()), encounter_id=episode.episode_id, patient_code=episode.patient_code, test_name=test_name, result=result, result_unit=clean(payload.get("unit"), 40) or None, created_by=user.username))
    episode.status = "in_care"; episode.assigned_department = clean(payload.get("next_department"), 60) or "Consulting Room"; episode.updated_at = datetime.utcnow()
    db.add(CareEvent(event_id=str(uuid.uuid4()), episode_id=episode.episode_id, patient_code=episode.patient_code, facility=episode.facility, department="Laboratory", event_type="result_available", summary=f"{test_name}: {result}", clinical_data_json=json.dumps({"test_name": test_name, "result": result, "unit": clean(payload.get("unit"), 40)}), created_by=user.username))
    audit(db, user, "laboratory_result_recorded", "care_episode", episode_id, test_name); db.commit()
    return {"message": "Laboratory result saved", "next_department": episode.assigned_department}


@router.post("/episodes/{episode_id}/medications", status_code=201)
def prescribe(episode_id: str, payload: dict, user: User = Depends(allow("administrator", "clinician", "nutritionist_dietitian")), db: Session = Depends(get_db)):
    episode = require_local_episode(db, episode_id, user); medicine, instructions = clean(payload.get("medicine"), 160), clean(payload.get("instructions"))
    if not medicine or not instructions: raise HTTPException(422, "Medicine and instructions are required")
    row = MedicationOrder(order_id=str(uuid.uuid4()), episode_id=episode_id, patient_code=episode.patient_code, facility=episode.facility, medicine=medicine, instructions=instructions, prescribed_by=user.username)
    db.add(row); episode.assigned_department = "Pharmacy"; episode.status = "in_care"; episode.updated_at = datetime.utcnow()
    db.add(CareEvent(event_id=str(uuid.uuid4()), episode_id=episode_id, patient_code=episode.patient_code, facility=episode.facility, department="Consulting Room", event_type="medication_prescribed", summary=medicine, clinical_data_json=json.dumps({"instructions": instructions}), created_by=user.username))
    audit(db, user, "medication_prescribed", "medication_order", row.order_id, medicine); db.commit()
    return {"order_id": row.order_id, "status": row.status}


@router.get("/medications")
def list_medications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user)
    rows = db.scalars(select(MedicationOrder).where(MedicationOrder.facility == facility).order_by(MedicationOrder.created_at.desc()).limit(200)).all()
    return [{"order_id": row.order_id, "episode_id": row.episode_id, "patient_code": row.patient_code, "medicine": row.medicine, "instructions": row.instructions, "status": row.status, "prescribed_by": row.prescribed_by} for row in rows]


@router.patch("/medications/{order_id}/dispense")
def dispense(order_id: str, user: User = Depends(allow("administrator", "clinician", "field_officer")), db: Session = Depends(get_db)):
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
def create_network_referral(payload: dict, user: User = Depends(allow("administrator", "clinician", "nutritionist_dietitian")), db: Session = Depends(get_db)):
    episode = require_local_episode(db, clean(payload.get("episode_id"), 36), user)
    destination, reason, summary = clean(payload.get("destination_facility"), 160), clean(payload.get("reason")), clean(payload.get("clinical_summary"))
    urgency = clean(payload.get("urgency"), 20) or "routine"
    if not destination or destination.casefold() == episode.facility.casefold(): raise HTTPException(422, "Choose a different receiving facility")
    if len(reason) < 3 or len(summary) < 10: raise HTTPException(422, "Referral reason and clinical summary are required")
    if urgency not in {"routine", "urgent", "emergency"}: raise HTTPException(422, "Invalid referral urgency")
    if payload.get("consent_confirmed") is not True: raise HTTPException(422, "Patient consent or an approved lawful basis must be confirmed")
    access_code = secrets.token_hex(3).upper()
    row = NetworkReferral(referral_id=str(uuid.uuid4()), episode_id=episode.episode_id, patient_code=episode.patient_code, source_facility=episode.facility, destination_facility=destination, access_code_hash=hashlib.sha256(access_code.encode()).hexdigest(), reason=reason, urgency=urgency, clinical_summary=summary, status="sent", consent_confirmed=True, expires_at=datetime.utcnow()+timedelta(days=7), created_by=user.username)
    db.add(row); db.add(NetworkReferralEvent(referral_id=row.referral_id, actor=user.username, facility=episode.facility, action="sent", details=destination)); episode.status = "referred"; episode.assigned_department = "Referral"; episode.updated_at = datetime.utcnow()
    audit(db, user, "network_referral_sent", "network_referral", row.referral_id, f"{episode.facility} to {destination}"); db.commit()
    return {**referral_json(row, True), "access_code": access_code, "access_code_notice": "Share this time limited code with the patient or authorized receiving team. It will not be displayed again."}


@router.get("/referrals")
def list_network_referrals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user)
    rows = db.scalars(select(NetworkReferral).where(or_(NetworkReferral.source_facility == facility, NetworkReferral.destination_facility == facility)).order_by(NetworkReferral.created_at.desc()).limit(200)).all()
    return [referral_json(row, row.source_facility == facility or user.role == "administrator") for row in rows]


@router.post("/referrals/access")
def access_referral(payload: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user)
    patient_code, access_code, reason = clean(payload.get("patient_code"), 64).upper(), clean(payload.get("access_code"), 20).upper(), clean(payload.get("access_reason"), 500)
    if len(reason) < 5: raise HTTPException(422, "State why this record is being accessed")
    row = db.scalar(select(NetworkReferral).where(NetworkReferral.patient_code == patient_code, NetworkReferral.destination_facility == facility, NetworkReferral.status.in_(["sent", "accepted", "arrived", "in_care"])).order_by(NetworkReferral.created_at.desc()))
    valid = row and secrets.compare_digest(row.access_code_hash, hashlib.sha256(access_code.encode()).hexdigest())
    if not valid or row.expires_at < datetime.utcnow():
        audit(db, user, "network_referral_access_denied", "patient", patient_code, reason); db.commit()
        raise HTTPException(403, "Referral details could not be verified")
    events = db.scalars(select(CareEvent).where(CareEvent.patient_code == patient_code, CareEvent.facility.in_([row.source_facility, row.destination_facility])).order_by(CareEvent.created_at)).all()
    labs = db.scalars(select(LaboratoryTest).where(LaboratoryTest.patient_code == patient_code).order_by(LaboratoryTest.tested_at)).all()
    patient = db.scalar(select(Patient).where(Patient.patient_code == patient_code))
    audit(db, user, "network_referral_record_accessed", "network_referral", row.referral_id, reason); db.commit()
    return {"referral": referral_json(row, True), "patient":{"patient_code":patient.patient_code,"sex":patient.sex,"age":patient.approximate_age} if patient else {"patient_code":patient_code}, "timeline":[{"department":event.department,"event_type":event.event_type,"summary":event.summary,"facility":event.facility,"created_at":event.created_at.isoformat()} for event in events], "laboratory_results":[{"test_name":lab.test_name,"result":lab.result,"unit":lab.result_unit,"tested_at":lab.tested_at.isoformat()} for lab in labs]}


@router.patch("/referrals/{referral_id}")
def update_network_referral(referral_id: str, payload: dict, user: User = Depends(allow("administrator", "clinician", "nutritionist_dietitian", "field_officer")), db: Session = Depends(get_db)):
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
def local_patient_timeline(patient_code: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_care_role(user); facility = facility_for(user); patient_code = patient_code.upper()
    events = db.scalars(select(CareEvent).where(CareEvent.patient_code == patient_code, CareEvent.facility == facility).order_by(CareEvent.created_at)).all()
    if not events: raise HTTPException(404, "No local care history found")
    audit(db, user, "local_care_timeline_viewed", "patient", patient_code, facility); db.commit()
    return [{"department":event.department,"event_type":event.event_type,"summary":event.summary,"created_by":event.created_by,"created_at":event.created_at.isoformat()} for event in events]
