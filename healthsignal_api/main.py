import os, uuid
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .database import Referral, Screening, User, SessionLocal, get_db, init_db
from .auth import allow, current_user, hash_password, token_for, verify_password
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
        if not db.scalar(select(User).where(User.username==username)):
            db.add(User(username=username,full_name=os.getenv("ADMIN_NAME","System Administrator"),password_hash=hash_password(password),role="administrator",active=True)); db.commit()

@app.post("/api/v1/auth/login")
def login(payload:dict,db:Session=Depends(get_db)):
    username=str(payload.get("username","")).strip().lower(); password=str(payload.get("password",""))
    user=db.scalar(select(User).where(User.username==username,User.active.is_(True)))
    if not user or not verify_password(password,user.password_hash): raise HTTPException(401,"Invalid username or password")
    return {"access_token":token_for(user),"token_type":"bearer","user":{"username":user.username,"full_name":user.full_name,"role":user.role}}

@app.get("/api/v1/auth/me")
def me(user:User=Depends(current_user)): return {"username":user.username,"full_name":user.full_name,"role":user.role}

@app.post("/api/v1/users",status_code=201)
def create_user(payload:dict,user:User=Depends(allow("administrator")),db:Session=Depends(get_db)):
    username=str(payload.get("username","")).strip().lower(); password=str(payload.get("password","")); role=payload.get("role")
    roles={"administrator","clinician","disease_control_officer","data_officer","field_worker"}
    if len(username)<3 or len(password)<10 or role not in roles: raise HTTPException(422,"Use a valid username, role and password of at least 10 characters")
    if db.scalar(select(User).where(User.username==username)): raise HTTPException(409,"Username already exists")
    created=User(username=username,full_name=str(payload.get("full_name",username)),password_hash=hash_password(password),role=role,active=True); db.add(created); db.commit()
    return {"username":created.username,"full_name":created.full_name,"role":created.role}
@app.get("/",include_in_schema=False)
def frontend(): return FileResponse(STATIC_DIR / "index.html")
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
