import base64, csv, io, json, math, os, re, statistics, uuid
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .database import Attachment, AuditLog, Encounter, LaboratoryTest, Patient, Referral, ReviewCase, ReviewEvent, Screening, User, SessionLocal, get_db, init_db
from .auth import allow, authenticated_user, current_user, hash_password, token_for, verify_password
from .rules import screen
from .schemas import ScreeningRequest, ScreeningResult

DISCLAIMER="HealthSignal supports screening and surveillance. It does not replace clinical judgement, diagnostic testing, or Ghana Health Service protocols."
app=FastAPI(title="HealthSignal API",version="1.0.0",description="Field screening and public health surveillance API")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in os.getenv("CORS_ORIGINS","http://localhost:8501").split(",")],allow_methods=["*"],allow_headers=["*"])
STATIC_DIR=Path(__file__).resolve().parent.parent / "static"
app.mount("/static",StaticFiles(directory=STATIC_DIR),name="static")
@app.on_event("startup")
def startup(): init_db()
@app.get("/health")
def health(): return {"status":"ok","service":"healthsignal-api","version":app.version}
@app.on_event("startup")
def bootstrap_admin():
    username=os.getenv("ADMIN_USERNAME","").strip().lower(); password=os.getenv("ADMIN_PASSWORD","")
    if not username or not password: return
    with SessionLocal() as db:
        existing=db.scalar(select(User).where(User.username==username))
        if not existing:
            db.add(User(username=username,full_name=os.getenv("ADMIN_NAME","System Administrator"),password_hash=hash_password(password),role="administrator",status="approved",active=True,terms_accepted=True)); db.commit()
        elif existing.role=="administrator":
            existing.status="approved"; existing.active=True; db.commit()

@app.on_event("startup")
def backfill_review_queue():
    """Add eligible historical screenings once, without changing clinical data."""
    with SessionLocal() as db:
        for screening in db.scalars(select(Screening).where(Screening.archived.is_(False))).all():
            if db.scalar(select(ReviewCase).where(ReviewCase.screening_id==screening.screening_id)): continue
            encounter=db.scalar(select(Encounter).where(Encounter.screening_id==screening.screening_id))
            reasons=[]
            if screening.disease not in {"hypertension","diabetes","malaria","tb"}: reasons.append("Module requires medical protocol review")
            if screening.risk_level in {"High","Urgent"}: reasons.append(f"{screening.risk_level} priority screening signal")
            if encounter and encounter.completion_status=="incomplete": reasons.append("Encounter is incomplete")
            if screening.referred: reasons.append("Referral follow up requires review")
            if not reasons or not encounter: continue
            review_id=str(uuid.uuid4()); priority="immediate" if screening.risk_level=="Urgent" else "urgent" if screening.risk_level=="High" else "routine"; now=datetime.utcnow()
            db.add(ReviewCase(review_id=review_id,screening_id=screening.screening_id,encounter_id=encounter.encounter_id,patient_code=screening.patient_code,disease=screening.disease,district=screening.district,facility=encounter.facility,priority=priority,status="awaiting_review",flag_reasons_json=json.dumps(reasons),follow_up_date=encounter.follow_up_date,created_by=screening.created_by or "system",created_at=now,updated_at=now))
            db.add(ReviewEvent(review_id=review_id,actor="system",action="historical_case_flagged",details="; ".join(reasons),created_at=now))
        db.commit()

ROLES={"administrator","clinician","nutritionist_dietitian","disease_control_officer","field_officer","data_officer"}
REQUESTABLE_ROLES=ROLES-{"administrator"}
STATUSES={"pending","approved","rejected","suspended"}
REVIEW_CLASSES={"suspected","probable","confirmed","excluded","inconclusive"}
REVIEW_ACTIONS={"repeat_assessment","request_laboratory_test","refer_to_facility","notify_disease_control","start_follow_up","close_case"}
REVIEW_STATUSES={"awaiting_review","under_review","follow_up_required","closed"}
CLINICALLY_REVIEWED_MODULES={"hypertension","diabetes","malaria","tb"}
ALL_MODULES={"hypertension","diabetes","malaria","tb","maternal_risk","childhood_malnutrition","anaemia_pregnancy","hiv_linkage","cholera_diarrhoea","measles","meningitis","acute_respiratory_infection","hepatitis","mental_health","other_ncd"}
NUTRITION_MODULES={"childhood_malnutrition","anaemia_pregnancy","hypertension","diabetes","other_ncd"}
PUBLIC_HEALTH_MODULES={"malaria","tb","hiv_linkage","cholera_diarrhoea","measles","meningitis","acute_respiratory_infection","hepatitis"}
ROLE_MODULES={"administrator":ALL_MODULES,"clinician":ALL_MODULES,"nutritionist_dietitian":NUTRITION_MODULES,"disease_control_officer":PUBLIC_HEALTH_MODULES,"field_officer":ALL_MODULES,"data_officer":set()}
ROLE_VIEWS={"administrator":["screening","dashboard","surveillance","records","referrals","reviews","users","account","about"],"clinician":["screening","dashboard","records","referrals","reviews","account","about"],"nutritionist_dietitian":["screening","dashboard","records","referrals","reviews","account","about"],"disease_control_officer":["screening","dashboard","surveillance","records","referrals","reviews","account","about"],"field_officer":["screening","dashboard","records","referrals","reviews","account","about"],"data_officer":["dashboard","surveillance","records","reviews","account","about"]}

def clean(value): return str(value or "").strip()
def valid_password(value):
    return len(value)>=12 and re.search(r"[A-Z]",value) and re.search(r"[a-z]",value) and re.search(r"\d",value)
def audit(db,actor,action,target_type,target_id,details=""):
    db.add(AuditLog(actor=actor,action=action,target_type=target_type,target_id=str(target_id),details=details))

def review_json(row,screening=None,encounter=None,events=None):
    return {"review_id":row.review_id,"screening_id":row.screening_id,"encounter_id":row.encounter_id,"patient_code":row.patient_code,"disease":row.disease,"district":row.district,"facility":row.facility,"priority":row.priority,"status":row.status,"flag_reasons":json.loads(row.flag_reasons_json or "[]"),"assigned_to":row.assigned_to,"reviewer_classification":row.reviewer_classification,"recommended_action":row.recommended_action,"reviewer_notes":row.reviewer_notes,"follow_up_date":row.follow_up_date,"reviewed_by":row.reviewed_by,"reviewed_at":row.reviewed_at.isoformat() if row.reviewed_at else None,"created_by":row.created_by,"created_at":row.created_at.isoformat(),"screening":{"visit_date":screening.visit_date,"community":screening.community,"risk_level":screening.risk_level,"classification":screening.classification,"case_status":screening.case_status,"outcome":screening.outcome} if screening else None,"encounter":{"temperature_c":encounter.temperature_c,"pulse":encounter.pulse,"respiratory_rate":encounter.respiratory_rate,"oxygen_saturation":encounter.oxygen_saturation,"blood_pressure":f"{encounter.systolic}/{encounter.diastolic}" if encounter.systolic and encounter.diastolic else None,"bmi":encounter.bmi,"symptoms":json.loads(encounter.symptoms_json or "[]"),"notes":encounter.notes,"completion_status":encounter.completion_status} if encounter else None,"history":[{"actor":e.actor,"action":e.action,"details":e.details,"created_at":e.created_at.isoformat()} for e in (events or [])]}

def review_flags(p,result):
    reasons=[]
    if p.disease not in CLINICALLY_REVIEWED_MODULES: reasons.append("Module requires medical protocol review")
    if result.risk in {"High","Urgent"}: reasons.append(f"{result.risk} priority screening signal")
    if p.completion_status=="incomplete": reasons.append("Encounter is incomplete")
    if p.case_status=="confirmed" and not (p.lab_test_name and p.lab_result): reasons.append("Confirmed status has no laboratory result recorded")
    if p.referred: reasons.append("Referral follow up requires review")
    return reasons
def user_json(user):
    return {"id":user.id,"username":user.username,"email":user.email,"full_name":user.full_name,"phone":user.phone,"staff_id":user.staff_id,"facility":user.facility,"district":user.district,"region":user.region,"role":user.role,"status":user.status,"active":user.active,"force_password_change":user.force_password_change,"allowed_views":ROLE_VIEWS.get(user.role,["account","about"]),"allowed_modules":sorted(ROLE_MODULES.get(user.role,set())),"last_login":user.last_login.isoformat() if user.last_login else None,"created_at":user.created_at.isoformat() if user.created_at else None}

def require_module_access(user,module):
    if module not in ROLE_MODULES.get(user.role,set()): raise HTTPException(403,"This screening module is not assigned to your professional role")

def require_review_access(user,row):
    if user.role in {"administrator","clinician"}: return
    if user.role=="nutritionist_dietitian" and row.disease in NUTRITION_MODULES: return
    if user.role=="disease_control_officer" and row.disease in PUBLIC_HEALTH_MODULES: return
    raise HTTPException(403,"This clinical review is not assigned to your professional role")

@app.post("/api/v1/auth/register",status_code=201)
def register(payload:dict,db:Session=Depends(get_db)):
    username=clean(payload.get("username")).lower(); email=clean(payload.get("email")).lower()
    password=str(payload.get("password") or ""); role=clean(payload.get("role"))
    if not re.fullmatch(r"[a-z0-9._]{3,80}",username): raise HTTPException(422,"Username may contain lowercase letters, numbers, dots and underscores")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email): raise HTTPException(422,"Enter a valid email address")
    if role not in REQUESTABLE_ROLES: raise HTTPException(422,"Select a valid staff role")
    if not valid_password(password): raise HTTPException(422,"Password must have at least 12 characters, uppercase, lowercase and a number")
    required={k:clean(payload.get(k)) for k in ("full_name","phone","staff_id","facility","district","region")}
    if not all(required.values()): raise HTTPException(422,"Complete all staff and facility details")
    if payload.get("terms_accepted") is not True: raise HTTPException(422,"Privacy and acceptable use acknowledgement is required")
    if db.scalar(select(User).where((User.username==username)|(User.email==email)|(User.staff_id==required["staff_id"]))): raise HTTPException(409,"Username, email or staff ID is already registered")
    user=User(username=username,email=email,password_hash=hash_password(password),role=role,status="pending",active=False,terms_accepted=True,**required)
    db.add(user); db.flush(); audit(db,username,"access_requested","user",user.id,f"Requested {role} access"); db.commit()
    return {"message":"Access request submitted for administrator review","status":"pending"}

@app.post("/api/v1/auth/login")
def login(payload:dict,db:Session=Depends(get_db)):
    username=str(payload.get("username","")).strip().lower(); password=str(payload.get("password",""))
    user=db.scalar(select(User).where(User.username==username)); now=datetime.utcnow()
    if user and user.locked_until and user.locked_until>now: raise HTTPException(429,"Account temporarily locked. Try again later")
    if not user or not verify_password(password,user.password_hash):
        if user:
            user.failed_login_attempts=(user.failed_login_attempts or 0)+1
            if user.failed_login_attempts>=5: user.locked_until=now+timedelta(minutes=15); user.failed_login_attempts=0
            db.commit()
        raise HTTPException(401,"Invalid username or password")
    if user.status=="pending": raise HTTPException(403,"Your access request is awaiting administrator approval")
    if user.status in {"rejected","suspended"} or not user.active: raise HTTPException(403,"This account is not currently authorized")
    user.failed_login_attempts=0; user.locked_until=None; user.last_login=now
    audit(db,user.username,"login","user",user.id); db.commit()
    return {"access_token":token_for(user),"token_type":"bearer","user":{**user_json(user),"password_change_required":user.force_password_change}}

@app.get("/api/v1/auth/me")
def me(user:User=Depends(authenticated_user)): return {**user_json(user),"password_change_required":user.force_password_change}

@app.post("/api/v1/auth/change-password")
def change_password(payload:dict,user:User=Depends(authenticated_user),db:Session=Depends(get_db)):
    current=str(payload.get("current_password") or ""); new=str(payload.get("new_password") or "")
    if not verify_password(current,user.password_hash): raise HTTPException(400,"Current password is incorrect")
    if not valid_password(new): raise HTTPException(422,"New password must have at least 12 characters, uppercase, lowercase and a number")
    if verify_password(new,user.password_hash): raise HTTPException(422,"Choose a different password")
    user.password_hash=hash_password(new); user.force_password_change=False
    audit(db,user.username,"password_changed","user",user.id); db.commit()
    return {"message":"Password changed successfully"}

@app.post("/api/v1/auth/forgot-password")
def forgot_password(payload:dict,db:Session=Depends(get_db)):
    identifier=clean(payload.get("identifier")).lower()
    user=db.scalar(select(User).where((User.username==identifier)|(User.email==identifier)))
    if user: audit(db,user.username,"password_help_requested","user",user.id); db.commit()
    return {"message":"If the account exists, an administrator can issue a temporary password. Contact your HealthSignal administrator."}

@app.post("/api/v1/users",status_code=201)
def create_user(payload:dict,user:User=Depends(allow("administrator")),db:Session=Depends(get_db)):
    username=str(payload.get("username","")).strip().lower(); password=str(payload.get("password","")); role=payload.get("role")
    if len(username)<3 or not valid_password(password) or role not in ROLES: raise HTTPException(422,"Use a valid username, role and strong password")
    if db.scalar(select(User).where(User.username==username)): raise HTTPException(409,"Username already exists")
    created=User(username=username,email=clean(payload.get("email")).lower() or None,full_name=str(payload.get("full_name",username)),password_hash=hash_password(password),role=role,status="approved",active=True,terms_accepted=True); db.add(created); db.flush(); audit(db,user.username,"user_created","user",created.id,role); db.commit()
    return {"username":created.username,"full_name":created.full_name,"role":created.role}

@app.get("/api/v1/users")
def list_users(status:str|None=None,user:User=Depends(allow("administrator")),db:Session=Depends(get_db)):
    stmt=select(User).order_by(User.created_at.desc())
    if status:
        if status not in STATUSES: raise HTTPException(422,"Invalid account status")
        stmt=stmt.where(User.status==status)
    return [user_json(row) for row in db.scalars(stmt).all()]

@app.patch("/api/v1/users/{user_id}/status")
def review_user(user_id:int,payload:dict,user:User=Depends(allow("administrator")),db:Session=Depends(get_db)):
    target=db.get(User,user_id); status=clean(payload.get("status"))
    if not target: raise HTTPException(404,"User not found")
    if status not in STATUSES-{"pending"}: raise HTTPException(422,"Status must be approved, rejected or suspended")
    if target.id==user.id and status!="approved": raise HTTPException(400,"You cannot disable your own administrator account")
    role=clean(payload.get("role")) or target.role
    if role not in ROLES: raise HTTPException(422,"Invalid role")
    target.status=status; target.active=status=="approved"; target.role=role; target.reviewed_by=user.username; target.reviewed_at=datetime.utcnow()
    audit(db,user.username,f"user_{status}","user",target.id,role); db.commit()
    return user_json(target)

@app.patch("/api/v1/users/{user_id}/assignment")
def update_assignment(user_id:int,payload:dict,user:User=Depends(allow("administrator")),db:Session=Depends(get_db)):
    target=db.get(User,user_id)
    if not target: raise HTTPException(404,"User not found")
    for field in ("facility","district","region"):
        if field in payload: setattr(target,field,clean(payload[field]))
    role=clean(payload.get("role"))
    if role:
        if role not in ROLES: raise HTTPException(422,"Invalid role")
        target.role=role
    audit(db,user.username,"assignment_updated","user",target.id,target.role); db.commit()
    return user_json(target)

@app.post("/api/v1/users/{user_id}/reset-password")
def reset_password(user_id:int,payload:dict,user:User=Depends(allow("administrator")),db:Session=Depends(get_db)):
    target=db.get(User,user_id); temporary=str(payload.get("temporary_password") or "")
    if not target: raise HTTPException(404,"User not found")
    if not valid_password(temporary): raise HTTPException(422,"Temporary password must have at least 12 characters, uppercase, lowercase and a number")
    target.password_hash=hash_password(temporary); target.force_password_change=True; target.locked_until=None; target.failed_login_attempts=0
    audit(db,user.username,"password_reset","user",target.id); db.commit()
    return {"message":"Temporary password set. The user must change it after signing in."}

@app.get("/api/v1/audit-logs")
def audit_logs(limit:int=Query(100,ge=1,le=500),user:User=Depends(allow("administrator")),db:Session=Depends(get_db)):
    rows=db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    return [{"actor":r.actor,"action":r.action,"target_type":r.target_type,"target_id":r.target_id,"details":r.details,"created_at":r.created_at.isoformat()} for r in rows]
@app.get("/",include_in_schema=False)
def frontend(): return FileResponse(STATIC_DIR / "index.html",headers={"Cache-Control":"no-cache, no-store, must-revalidate"})
@app.post("/api/v1/screenings",response_model=ScreeningResult,status_code=201)
def create_screening(p: ScreeningRequest,user:User=Depends(current_user),db: Session=Depends(get_db)):
    require_module_access(user,p.disease); d=screen(p); now=datetime.utcnow(); sid=str(uuid.uuid4()); eid=str(uuid.uuid4())
    patient=db.scalar(select(Patient).where(Patient.patient_code==p.patient_code))
    if not patient:
        patient=Patient(patient_code=p.patient_code,sex=p.sex,approximate_age=p.age,home_community=p.community,district=p.district,region=p.region,created_by=user.username)
        db.add(patient)
    else:
        patient.sex=p.sex; patient.approximate_age=p.age; patient.home_community=p.community or patient.home_community; patient.district=p.district or patient.district; patient.region=p.region or patient.region; patient.updated_at=now
    db.add(Screening(screening_id=sid,patient_code=p.patient_code,visit_date=p.visit_date.isoformat(),region=p.region,district=p.district,community=p.community,facility=p.facility,age=p.age,sex=p.sex,pregnant=p.pregnant,disease=p.disease,risk_level=d.risk,classification=d.classification,recommendation=d.recommendation,score=d.score,inputs_json=p.model_dump_json(),referred=p.referred,latitude=p.latitude if p.gps_consent else None,longitude=p.longitude if p.gps_consent else None,case_status=p.case_status,outcome=p.outcome,created_by=user.username,created_at=now,updated_at=now))
    db.add(Encounter(encounter_id=eid,patient_code=p.patient_code,screening_id=sid,visit_date=p.visit_date.isoformat(),facility=p.facility,community=p.community,district=p.district,region=p.region,temperature_c=p.temperature_c,pulse=p.pulse,respiratory_rate=p.respiratory_rate,oxygen_saturation=p.oxygen_saturation,systolic=p.systolic_1,diastolic=p.diastolic_1,weight_kg=p.weight_kg,height_cm=p.height_cm,bmi=d.bmi,pregnant=p.pregnant,symptoms_json=json.dumps(p.symptoms),notes=p.notes,outcome=p.outcome,follow_up_date=p.follow_up_date.isoformat() if p.follow_up_date else None,completion_status=p.completion_status,created_by=user.username,created_at=now,updated_at=now))
    if p.lab_test_name and p.lab_result:
        db.add(LaboratoryTest(test_id=str(uuid.uuid4()),encounter_id=eid,patient_code=p.patient_code,test_name=p.lab_test_name,result=p.lab_result,result_unit=p.lab_result_unit,created_by=user.username))
    if p.referred and p.referral_destination:
        db.add(Referral(referral_id=str(uuid.uuid4()),screening_id=sid,patient_code=p.patient_code,destination=p.referral_destination,reason=p.referral_reason or d.recommendation,status="Pending",due_date=p.follow_up_date.isoformat() if p.follow_up_date else None,created_by=user.username))
    flags=review_flags(p,d)
    if flags:
        review_id=str(uuid.uuid4()); priority="immediate" if d.risk=="Urgent" else "urgent" if d.risk=="High" else "routine"
        db.add(ReviewCase(review_id=review_id,screening_id=sid,encounter_id=eid,patient_code=p.patient_code,disease=p.disease,district=p.district,facility=p.facility,priority=priority,status="awaiting_review",flag_reasons_json=json.dumps(flags),follow_up_date=p.follow_up_date.isoformat() if p.follow_up_date else None,created_by=user.username,created_at=now,updated_at=now))
        db.add(ReviewEvent(review_id=review_id,actor="system",action="case_flagged",details="; ".join(flags),created_at=now))
    audit(db,user.username,"screening_created","screening",sid,p.disease); db.commit()
    return ScreeningResult(screening_id=sid,encounter_id=eid,disease=p.disease,risk_level=d.risk,classification=d.classification,recommendation=d.recommendation,score=d.score,bmi=d.bmi,disclaimer=DISCLAIMER,created_at=now)

@app.get("/api/v1/reviews")
def list_reviews(status:str|None=None,priority:str|None=None,disease:str|None=None,district:str|None=None,user:User=Depends(current_user),db:Session=Depends(get_db)):
    stmt=select(ReviewCase).order_by(ReviewCase.created_at.desc()).limit(500)
    if user.role=="field_officer": stmt=stmt.where(ReviewCase.created_by==user.username)
    elif user.role=="nutritionist_dietitian": stmt=stmt.where(ReviewCase.disease.in_(NUTRITION_MODULES))
    elif user.role=="disease_control_officer": stmt=stmt.where(ReviewCase.disease.in_(PUBLIC_HEALTH_MODULES))
    if status: stmt=stmt.where(ReviewCase.status==status)
    if priority: stmt=stmt.where(ReviewCase.priority==priority)
    if disease: stmt=stmt.where(ReviewCase.disease==disease)
    if district: stmt=stmt.where(func.lower(ReviewCase.district)==district.lower())
    rows=db.scalars(stmt).all()
    return [review_json(r,db.scalar(select(Screening).where(Screening.screening_id==r.screening_id)),db.scalar(select(Encounter).where(Encounter.encounter_id==r.encounter_id))) for r in rows]

@app.get("/api/v1/reviews/{review_id}")
def get_review(review_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.scalar(select(ReviewCase).where(ReviewCase.review_id==review_id))
    if not row or (user.role=="field_officer" and row.created_by!=user.username): raise HTTPException(404,"Review case not found")
    if user.role in {"nutritionist_dietitian","disease_control_officer"}: require_review_access(user,row)
    events=db.scalars(select(ReviewEvent).where(ReviewEvent.review_id==review_id).order_by(ReviewEvent.created_at.desc())).all()
    return review_json(row,db.scalar(select(Screening).where(Screening.screening_id==row.screening_id)),db.scalar(select(Encounter).where(Encounter.encounter_id==row.encounter_id)),events)

@app.patch("/api/v1/reviews/{review_id}")
def decide_review(review_id:str,payload:dict,user:User=Depends(allow("administrator","clinician","nutritionist_dietitian","disease_control_officer")),db:Session=Depends(get_db)):
    row=db.scalar(select(ReviewCase).where(ReviewCase.review_id==review_id))
    if not row: raise HTTPException(404,"Review case not found")
    require_review_access(user,row)
    classification=clean(payload.get("classification")); action=clean(payload.get("recommended_action")); status=clean(payload.get("status"))
    if classification not in REVIEW_CLASSES: raise HTTPException(422,"Select a valid reviewer classification")
    if action not in REVIEW_ACTIONS: raise HTTPException(422,"Select a valid recommended action")
    if status not in REVIEW_STATUSES: raise HTTPException(422,"Select a valid review status")
    notes=clean(payload.get("notes"))
    if len(notes)<5: raise HTTPException(422,"Add a brief review note")
    row.reviewer_classification=classification; row.recommended_action=action; row.status=status; row.reviewer_notes=notes[:3000]; row.follow_up_date=payload.get("follow_up_date") or None; row.assigned_to=clean(payload.get("assigned_to")) or user.username; row.reviewed_by=user.username; row.reviewed_at=datetime.utcnow(); row.updated_at=datetime.utcnow()
    screening=db.scalar(select(Screening).where(Screening.screening_id==row.screening_id))
    if screening: screening.case_status=classification; screening.updated_at=datetime.utcnow()
    details=f"{classification}; {action}; {status}"
    db.add(ReviewEvent(review_id=review_id,actor=user.username,action="clinical_decision_recorded",details=details)); audit(db,user.username,"review_decided","review",review_id,details); db.commit()
    return review_json(row,screening,db.scalar(select(Encounter).where(Encounter.encounter_id==row.encounter_id)))

@app.patch("/api/v1/reviews/{review_id}/data-quality")
def review_data_quality(review_id:str,payload:dict,user:User=Depends(allow("administrator","data_officer")),db:Session=Depends(get_db)):
    row=db.scalar(select(ReviewCase).where(ReviewCase.review_id==review_id))
    if not row: raise HTTPException(404,"Review case not found")
    note=clean(payload.get("note"))
    if len(note)<5: raise HTTPException(422,"Describe the data correction or validation")
    if row.status=="awaiting_review": row.status="under_review"
    row.updated_at=datetime.utcnow(); db.add(ReviewEvent(review_id=review_id,actor=user.username,action="data_quality_checked",details=note[:2000])); audit(db,user.username,"review_data_checked","review",review_id,note[:500]); db.commit()
    return {"message":"Data quality note recorded without changing the clinical classification","status":row.status}
@app.get("/api/v1/screenings")
def list_screenings(limit:int=Query(100,ge=1,le=1000),patient_code:str|None=None,user:User=Depends(current_user),db:Session=Depends(get_db)):
    stmt=select(Screening).where(Screening.archived.is_(False)).order_by(Screening.created_at.desc()).limit(limit)
    if user.role=="field_officer": stmt=stmt.where(Screening.created_by==user.username)
    if patient_code: stmt=stmt.where(Screening.patient_code==patient_code)
    return [{"screening_id":r.screening_id,"patient_code":r.patient_code,"visit_date":r.visit_date,"district":r.district,"community":r.community,"disease":r.disease,"risk_level":r.risk_level,"classification":r.classification,"recommendation":r.recommendation,"referred":r.referred,"case_status":r.case_status,"outcome":r.outcome} for r in db.scalars(stmt).all()]
@app.get("/api/v1/dashboard")
def dashboard(days:int=Query(30,ge=1,le=365),user:User=Depends(current_user),db:Session=Depends(get_db)):
    stmt=select(Screening.disease,Screening.risk_level,func.count()).where(Screening.created_at>=datetime.utcnow()-timedelta(days=days))
    if user.role=="field_officer": stmt=stmt.where(Screening.created_by==user.username)
    rows=db.execute(stmt.group_by(Screening.disease,Screening.risk_level)).all()
    return {"period_days":days,"total_screenings":sum(x[2] for x in rows),"high_or_urgent":sum(x[2] for x in rows if x[1] in ("High","Urgent")),"breakdown":[{"disease":d,"risk_level":r,"count":c} for d,r,c in rows],"note":"Counts are screening signals, not confirmed disease incidence."}

@app.post("/api/v1/referrals",status_code=201)
def create_referral(payload:dict,user:User=Depends(allow("administrator","clinician","nutritionist_dietitian","disease_control_officer","field_officer")),db:Session=Depends(get_db)):
    screening_id=str(payload.get("screening_id","")); screening=db.scalar(select(Screening).where(Screening.screening_id==screening_id))
    if not screening: raise HTTPException(404,"Screening record not found")
    referral=Referral(referral_id=str(uuid.uuid4()),screening_id=screening_id,patient_code=screening.patient_code,destination=str(payload.get("destination","")).strip(),reason=str(payload.get("reason",screening.recommendation)),status="Pending",due_date=payload.get("due_date"),created_by=user.username)
    if not referral.destination: raise HTTPException(422,"Referral destination is required")
    db.add(referral); screening.referred=True; db.commit(); return {"referral_id":referral.referral_id,"status":referral.status}

@app.get("/api/v1/referrals")
def list_referrals(user:User=Depends(current_user),db:Session=Depends(get_db)):
    stmt=select(Referral).order_by(Referral.created_at.desc()).limit(500)
    if user.role=="field_officer": stmt=stmt.where(Referral.created_by==user.username)
    rows=db.scalars(stmt).all()
    return [{"referral_id":r.referral_id,"screening_id":r.screening_id,"patient_code":r.patient_code,"destination":r.destination,"reason":r.reason,"status":r.status,"due_date":r.due_date,"created_by":r.created_by} for r in rows]

@app.patch("/api/v1/referrals/{referral_id}")
def update_referral(referral_id:str,payload:dict,user:User=Depends(allow("administrator","clinician","nutritionist_dietitian","disease_control_officer")),db:Session=Depends(get_db)):
    referral=db.scalar(select(Referral).where(Referral.referral_id==referral_id))
    if not referral: raise HTTPException(404,"Referral not found")
    status=payload.get("status"); allowed={"Pending","Contacted","Completed","Unable to reach"}
    if status not in allowed: raise HTTPException(422,"Invalid referral status")
    referral.status=status; referral.completed_at=datetime.utcnow() if status=="Completed" else None; db.commit(); return {"referral_id":referral.referral_id,"status":referral.status}

@app.get("/api/v1/patients/{patient_code}")
def patient_history(patient_code:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    patient=db.scalar(select(Patient).where(Patient.patient_code==patient_code,Patient.archived.is_(False)))
    if not patient: raise HTTPException(404,"Patient code not found")
    encounters=db.scalars(select(Encounter).where(Encounter.patient_code==patient_code,Encounter.archived.is_(False)).order_by(Encounter.visit_date.desc())).all()
    if user.role=="field_officer": encounters=[e for e in encounters if e.created_by==user.username]
    if not encounters and user.role=="field_officer": raise HTTPException(404,"Patient code not found in your submitted records")
    allowed_encounters={e.encounter_id for e in encounters}
    labs=db.scalars(select(LaboratoryTest).where(LaboratoryTest.patient_code==patient_code).order_by(LaboratoryTest.tested_at.desc())).all()
    if user.role=="field_officer": labs=[x for x in labs if x.encounter_id in allowed_encounters]
    return {"patient":{"patient_code":patient.patient_code,"sex":patient.sex,"age":patient.approximate_age,"community":patient.home_community,"district":patient.district,"region":patient.region},"encounters":[{"encounter_id":e.encounter_id,"screening_id":e.screening_id,"visit_date":e.visit_date,"facility":e.facility,"community":e.community,"district":e.district,"temperature_c":e.temperature_c,"pulse":e.pulse,"respiratory_rate":e.respiratory_rate,"oxygen_saturation":e.oxygen_saturation,"blood_pressure":f"{e.systolic}/{e.diastolic}" if e.systolic and e.diastolic else None,"weight_kg":e.weight_kg,"height_cm":e.height_cm,"bmi":e.bmi,"pregnant":e.pregnant,"symptoms":json.loads(e.symptoms_json or "[]"),"notes":e.notes,"outcome":e.outcome,"follow_up_date":e.follow_up_date,"completion_status":e.completion_status} for e in encounters],"laboratory_tests":[{"test_name":x.test_name,"result":x.result,"unit":x.result_unit,"tested_at":x.tested_at.isoformat()} for x in labs]}

@app.patch("/api/v1/encounters/{encounter_id}")
def update_encounter(encounter_id:str,payload:dict,user:User=Depends(allow("administrator","clinician","nutritionist_dietitian","data_officer","field_officer")),db:Session=Depends(get_db)):
    encounter=db.scalar(select(Encounter).where(Encounter.encounter_id==encounter_id,Encounter.archived.is_(False)))
    if not encounter: raise HTTPException(404,"Encounter not found")
    if user.role=="field_officer" and encounter.created_by!=user.username: raise HTTPException(403,"You can update only records you submitted")
    allowed_fields={"facility","community","district","region","temperature_c","pulse","respiratory_rate","oxygen_saturation","weight_kg","height_cm","pregnant","notes","outcome","follow_up_date","completion_status"}
    for field,value in payload.items():
        if field in allowed_fields: setattr(encounter,field,value)
    if encounter.weight_kg and encounter.height_cm: encounter.bmi=round(encounter.weight_kg/((encounter.height_cm/100)**2),1)
    encounter.updated_at=datetime.utcnow(); audit(db,user.username,"encounter_updated","encounter",encounter_id); db.commit()
    return {"message":"Encounter updated","bmi":encounter.bmi}

@app.post("/api/v1/encounters/{encounter_id}/archive")
def archive_encounter(encounter_id:str,user:User=Depends(allow("administrator","data_officer")),db:Session=Depends(get_db)):
    encounter=db.scalar(select(Encounter).where(Encounter.encounter_id==encounter_id))
    if not encounter: raise HTTPException(404,"Encounter not found")
    encounter.archived=True
    if encounter.screening_id:
        screening=db.scalar(select(Screening).where(Screening.screening_id==encounter.screening_id))
        if screening: screening.archived=True
    audit(db,user.username,"encounter_archived","encounter",encounter_id); db.commit(); return {"message":"Record archived"}

@app.post("/api/v1/encounters/{encounter_id}/attachments",status_code=201)
def add_attachment(encounter_id:str,payload:dict,user:User=Depends(allow("administrator","clinician","nutritionist_dietitian","field_officer")),db:Session=Depends(get_db)):
    encounter=db.scalar(select(Encounter).where(Encounter.encounter_id==encounter_id,Encounter.archived.is_(False)))
    if not encounter: raise HTTPException(404,"Encounter not found")
    if user.role=="field_officer" and encounter.created_by!=user.username: raise HTTPException(403,"You can upload only to records you submitted")
    if payload.get("consent_confirmed") is not True: raise HTTPException(422,"Consent confirmation is required")
    content_type=clean(payload.get("content_type")); encoded=str(payload.get("data_base64") or "")
    if content_type not in {"image/jpeg","image/png","application/pdf"}: raise HTTPException(422,"Only JPG, PNG or PDF files are supported")
    try: content=base64.b64decode(encoded,validate=True)
    except Exception: raise HTTPException(422,"Invalid file data")
    if not content or len(content)>1_000_000: raise HTTPException(413,"File must be 1 MB or smaller on the free tier")
    attachment=Attachment(attachment_id=str(uuid.uuid4()),encounter_id=encounter_id,patient_code=encounter.patient_code,filename=clean(payload.get("filename"))[:180],content_type=content_type,content=content,consent_confirmed=True,created_by=user.username)
    db.add(attachment); audit(db,user.username,"attachment_added","encounter",encounter_id,content_type); db.commit(); return {"attachment_id":attachment.attachment_id,"message":"File stored securely"}

def surveillance_rows(db,days,district=None):
    since=datetime.utcnow()-timedelta(days=days); stmt=select(Screening).where(Screening.created_at>=since,Screening.archived.is_(False))
    if district: stmt=stmt.where(func.lower(Screening.district)==district.lower())
    return db.scalars(stmt).all()

@app.get("/api/v1/surveillance/summary")
def surveillance_summary(days:int=Query(90,ge=7,le=730),district:str|None=None,user:User=Depends(allow("administrator","clinician","disease_control_officer","data_officer")),db:Session=Depends(get_db)):
    rows=surveillance_rows(db,days,district); today=datetime.utcnow().date(); tests=[r for r in rows if r.case_status in {"tested","confirmed","excluded"}]; confirmed=[r for r in rows if r.case_status=="confirmed"]
    def counts(key):
        output={}
        for row in rows:
            value=key(row) or "Not recorded"; output[value]=output.get(value,0)+1
        return [{"label":k,"count":v} for k,v in sorted(output.items(),key=lambda x:-x[1])]
    weekly={}
    for r in rows:
        try:
            date=datetime.fromisoformat(r.visit_date).date(); start=date-timedelta(days=date.weekday()); label=start.isoformat()
        except Exception: label="Unknown"
        weekly[label]=weekly.get(label,0)+1
    high=[r for r in rows if r.risk_level in {"High","Urgent"}]; hotspots={}
    for r in high:
        key=f"{r.community or 'Unknown'}, {r.district or 'Unknown'}"; hotspots.setdefault(key,{"community":r.community or "Unknown","district":r.district or "Unknown","count":0,"latitude":r.latitude,"longitude":r.longitude}); hotspots[key]["count"]+=1
    referrals=db.scalars(select(Referral).where(Referral.created_at>=datetime.utcnow()-timedelta(days=days))).all(); completed=sum(1 for r in referrals if r.status=="Completed")
    current=sum(1 for r in rows if (today-r.created_at.date()).days<7); prior=[sum(1 for r in rows if 7*i<=(today-r.created_at.date()).days<7*(i+1)) for i in range(1,5)]; baseline=statistics.mean(prior) if prior else 0; alert=current>=3 and current>=(baseline*2 if baseline else 3)
    return {"period_days":days,"total":len(rows),"district_counts":counts(lambda r:r.district),"community_counts":counts(lambda r:r.community),"disease_counts":counts(lambda r:r.disease),"weekly_trends":[{"week":k,"count":weekly[k]} for k in sorted(weekly)],"age_distribution":counts(lambda r:"0–4" if r.age<5 else "5–14" if r.age<15 else "15–24" if r.age<25 else "25–44" if r.age<45 else "45–64" if r.age<65 else "65+"),"sex_distribution":counts(lambda r:r.sex),"case_status":counts(lambda r:r.case_status),"tested":len(tests),"confirmed":len(confirmed),"test_positivity_rate":round(len(confirmed)/len(tests)*100,1) if tests else None,"hotspots":sorted(hotspots.values(),key=lambda x:-x["count"]),"alert":{"active":alert,"current_week":current,"four_week_average":round(baseline,1),"message":"Abnormal increase requires investigation" if alert else "No statistical alert at the current threshold"},"referral_completion_rate":round(completed/len(referrals)*100,1) if referrals else None,"referrals_total":len(referrals),"note":"Signals are based on screening records and require epidemiological review."}

@app.get("/api/v1/surveillance/forecast")
def forecast(disease:str|None=None,district:str|None=None,user:User=Depends(allow("administrator","disease_control_officer","data_officer")),db:Session=Depends(get_db)):
    rows=surveillance_rows(db,180,district)
    if disease: rows=[r for r in rows if r.disease==disease]
    weeks={}
    for r in rows:
        start=r.created_at.date()-timedelta(days=r.created_at.weekday()); weeks[start.isoformat()]=weeks.get(start.isoformat(),0)+1
    values=[weeks[k] for k in sorted(weeks)][-12:]
    if len(values)<4: return {"status":"insufficient_data","message":"At least four weeks of reporting data are required","model_version":"baseline-1.0","last_training_date":datetime.utcnow().date().isoformat()}
    recent=values[-4:]; expected=statistics.mean(recent); uncertainty=max(1,statistics.stdev(recent) if len(recent)>1 else math.sqrt(expected)); trend=(recent[-1]-recent[0])/max(1,len(recent)-1)
    predictions=[max(0,round(expected+trend*i,1)) for i in range(1,5)]; upper=[round(x+1.96*uncertainty,1) for x in predictions]; risk="High" if trend>max(1,expected*.25) else "Moderate" if trend>0 else "Low"
    return {"status":"available","risk_level":risk,"expected_cases_next_1_to_4_weeks":predictions,"upper_uncertainty_bounds":upper,"contributing_indicators":{"recent_weekly_counts":recent,"weekly_trend":round(trend,2),"district":district or "All","disease":disease or "All"},"model_version":"transparent-baseline-1.0","last_training_date":datetime.utcnow().date().isoformat(),"recommended_response":"Review data quality and investigate communities driving the increase." if risk!="Low" else "Continue routine surveillance and reporting.","disclaimer":"Aggregate planning signal only. It does not predict individual diagnoses."}

@app.get("/api/v1/reports/district.csv")
def district_report(district:str="",days:int=Query(90,ge=7,le=730),user:User=Depends(allow("administrator","disease_control_officer","data_officer")),db:Session=Depends(get_db)):
    rows=surveillance_rows(db,days,district or None); output=io.StringIO(); writer=csv.writer(output); writer.writerow(["visit_date","district","community","patient_code","disease","case_status","risk_level","outcome","referred"])
    for r in rows: writer.writerow([r.visit_date,r.district,r.community,r.patient_code,r.disease,r.case_status,r.risk_level,r.outcome or "",r.referred])
    audit(db,user.username,"district_report_downloaded","report",district or "all",f"{days} days"); db.commit()
    return Response(output.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="healthsignal-{(district or "all").replace(" ","-").lower()}-{days}d.csv"'})
