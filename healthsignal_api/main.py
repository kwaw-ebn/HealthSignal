import os, re, uuid
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .database import AuditLog, Referral, Screening, User, SessionLocal, get_db, init_db
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

ROLES={"administrator","clinician","disease_control_officer","data_officer","field_worker"}
REQUESTABLE_ROLES=ROLES-{"administrator"}
STATUSES={"pending","approved","rejected","suspended"}

def clean(value): return str(value or "").strip()
def valid_password(value):
    return len(value)>=12 and re.search(r"[A-Z]",value) and re.search(r"[a-z]",value) and re.search(r"\d",value)
def audit(db,actor,action,target_type,target_id,details=""):
    db.add(AuditLog(actor=actor,action=action,target_type=target_type,target_id=str(target_id),details=details))
def user_json(user):
    return {"id":user.id,"username":user.username,"email":user.email,"full_name":user.full_name,"phone":user.phone,"staff_id":user.staff_id,"facility":user.facility,"district":user.district,"region":user.region,"role":user.role,"status":user.status,"active":user.active,"force_password_change":user.force_password_change,"last_login":user.last_login.isoformat() if user.last_login else None,"created_at":user.created_at.isoformat() if user.created_at else None}

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
def create_screening(p: ScreeningRequest,user:User=Depends(allow("administrator","clinician","disease_control_officer","field_worker")),db: Session=Depends(get_db)):
    d=screen(p); now=datetime.utcnow(); sid=str(uuid.uuid4())
    db.add(Screening(screening_id=sid,patient_code=p.patient_code,visit_date=p.visit_date.isoformat(),region=p.region,district=p.district,community=p.community,facility=p.facility,age=p.age,sex=p.sex,pregnant=p.pregnant,disease=p.disease,risk_level=d.risk,classification=d.classification,recommendation=d.recommendation,score=d.score,inputs_json=p.model_dump_json(),referred=p.referred,latitude=p.latitude,longitude=p.longitude,created_at=now)); db.commit()
    return ScreeningResult(screening_id=sid,disease=p.disease,risk_level=d.risk,classification=d.classification,recommendation=d.recommendation,score=d.score,bmi=d.bmi,disclaimer=DISCLAIMER,created_at=now)
@app.get("/api/v1/screenings")
def list_screenings(limit:int=Query(100,ge=1,le=1000),patient_code:str|None=None,user:User=Depends(current_user),db:Session=Depends(get_db)):
    stmt=select(Screening).order_by(Screening.created_at.desc()).limit(limit)
    if patient_code: stmt=stmt.where(Screening.patient_code==patient_code)
    return [{"screening_id":r.screening_id,"patient_code":r.patient_code,"visit_date":r.visit_date,"district":r.district,"community":r.community,"disease":r.disease,"risk_level":r.risk_level,"classification":r.classification,"recommendation":r.recommendation,"referred":r.referred} for r in db.scalars(stmt).all()]
@app.get("/api/v1/dashboard")
def dashboard(days:int=Query(30,ge=1,le=365),user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.execute(select(Screening.disease,Screening.risk_level,func.count()).where(Screening.created_at>=datetime.utcnow()-timedelta(days=days)).group_by(Screening.disease,Screening.risk_level)).all()
    return {"period_days":days,"total_screenings":sum(x[2] for x in rows),"high_or_urgent":sum(x[2] for x in rows if x[1] in ("High","Urgent")),"breakdown":[{"disease":d,"risk_level":r,"count":c} for d,r,c in rows],"note":"Counts are screening signals, not confirmed disease incidence."}

@app.post("/api/v1/referrals",status_code=201)
def create_referral(payload:dict,user:User=Depends(allow("administrator","clinician","disease_control_officer","field_worker")),db:Session=Depends(get_db)):
    screening_id=str(payload.get("screening_id","")); screening=db.scalar(select(Screening).where(Screening.screening_id==screening_id))
    if not screening: raise HTTPException(404,"Screening record not found")
    referral=Referral(referral_id=str(uuid.uuid4()),screening_id=screening_id,patient_code=screening.patient_code,destination=str(payload.get("destination","")).strip(),reason=str(payload.get("reason",screening.recommendation)),status="Pending",due_date=payload.get("due_date"),created_by=user.username)
    if not referral.destination: raise HTTPException(422,"Referral destination is required")
    db.add(referral); screening.referred=True; db.commit(); return {"referral_id":referral.referral_id,"status":referral.status}

@app.get("/api/v1/referrals")
def list_referrals(user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.scalars(select(Referral).order_by(Referral.created_at.desc()).limit(500)).all()
    return [{"referral_id":r.referral_id,"screening_id":r.screening_id,"patient_code":r.patient_code,"destination":r.destination,"reason":r.reason,"status":r.status,"due_date":r.due_date,"created_by":r.created_by} for r in rows]

@app.patch("/api/v1/referrals/{referral_id}")
def update_referral(referral_id:str,payload:dict,user:User=Depends(allow("administrator","clinician","disease_control_officer")),db:Session=Depends(get_db)):
    referral=db.scalar(select(Referral).where(Referral.referral_id==referral_id))
    if not referral: raise HTTPException(404,"Referral not found")
    status=payload.get("status"); allowed={"Pending","Contacted","Completed","Unable to reach"}
    if status not in allowed: raise HTTPException(422,"Invalid referral status")
    referral.status=status; referral.completed_at=datetime.utcnow() if status=="Completed" else None; db.commit(); return {"referral_id":referral.referral_id,"status":referral.status}
