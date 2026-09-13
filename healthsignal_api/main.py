import os, uuid
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .database import Screening, get_db, init_db
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
@app.get("/",include_in_schema=False)
def frontend(): return FileResponse(STATIC_DIR / "index.html")
@app.post("/api/v1/screenings",response_model=ScreeningResult,status_code=201)
def create_screening(p: ScreeningRequest,db: Session=Depends(get_db)):
    d=screen(p); now=datetime.utcnow(); sid=str(uuid.uuid4())
    db.add(Screening(screening_id=sid,patient_code=p.patient_code,visit_date=p.visit_date.isoformat(),region=p.region,district=p.district,community=p.community,facility=p.facility,age=p.age,sex=p.sex,pregnant=p.pregnant,disease=p.disease,risk_level=d.risk,classification=d.classification,recommendation=d.recommendation,score=d.score,inputs_json=p.model_dump_json(),referred=p.referred,latitude=p.latitude,longitude=p.longitude,created_at=now)); db.commit()
    return ScreeningResult(screening_id=sid,disease=p.disease,risk_level=d.risk,classification=d.classification,recommendation=d.recommendation,score=d.score,bmi=d.bmi,disclaimer=DISCLAIMER,created_at=now)
@app.get("/api/v1/screenings")
def list_screenings(limit:int=Query(100,ge=1,le=1000),patient_code:str|None=None,db:Session=Depends(get_db)):
    stmt=select(Screening).order_by(Screening.created_at.desc()).limit(limit)
    if patient_code: stmt=stmt.where(Screening.patient_code==patient_code)
    return [{"screening_id":r.screening_id,"patient_code":r.patient_code,"visit_date":r.visit_date,"district":r.district,"community":r.community,"disease":r.disease,"risk_level":r.risk_level,"classification":r.classification,"recommendation":r.recommendation,"referred":r.referred} for r in db.scalars(stmt).all()]
@app.get("/api/v1/dashboard")
def dashboard(days:int=Query(30,ge=1,le=365),db:Session=Depends(get_db)):
    rows=db.execute(select(Screening.disease,Screening.risk_level,func.count()).where(Screening.created_at>=datetime.utcnow()-timedelta(days=days)).group_by(Screening.disease,Screening.risk_level)).all()
    return {"period_days":days,"total_screenings":sum(x[2] for x in rows),"high_or_urgent":sum(x[2] for x in rows if x[1] in ("High","Urgent")),"breakdown":[{"disease":d,"risk_level":r,"count":c} for d,r,c in rows],"note":"Counts are screening signals, not confirmed disease incidence."}
