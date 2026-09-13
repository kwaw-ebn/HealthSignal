import uuid
from datetime import date, datetime
import gradio as gr
import pandas as pd
from sqlalchemy import select
from healthsignal_api.database import Screening, SessionLocal, init_db
from healthsignal_api.rules import screen
from healthsignal_api.schemas import ScreeningRequest

init_db()
NOTICE="HealthSignal supports screening and surveillance. It does not replace clinical judgement, diagnostic testing or approved Ghana Health Service protocols."

def code(): return "HS-"+str(uuid.uuid4())[:6].upper()
def visible(d): return [gr.update(visible=d==x) for x in ["hypertension","diabetes","malaria","tb"]]

def submit(patient,visit,age,sex,region,district,community,facility,disease,s1,d1,s2,d2,pulse,weight,height,gtype,glucose,temp,fever,mtest,mresult,pregnant,family,previous,cough,contact,sweats,loss):
    common=dict(patient_code=patient,visit_date=visit,age=int(age),sex=sex,region=region or "",district=district or "",community=community or "",facility=facility or "",disease=disease)
    module={
      "hypertension":dict(systolic_1=s1,diastolic_1=d1,systolic_2=s2,diastolic_2=d2,pulse=pulse,weight_kg=weight,height_cm=height),
      "diabetes":dict(glucose_type=gtype,glucose_mmol_l=glucose,weight_kg=weight,height_cm=height,family_history=family,previous_diagnosis=previous),
      "malaria":dict(temperature_c=temp,fever_or_history=fever,malaria_test=mtest,malaria_result=mresult,pregnant=pregnant),
      "tb":dict(cough_two_weeks=cough,tb_contact=contact,night_sweats=sweats,unexplained_weight_loss=loss)}[disease]
    try:
        p=ScreeningRequest(**{**common,**{k:v for k,v in module.items() if v is not None}}); r=screen(p); sid=str(uuid.uuid4()); now=datetime.utcnow()
        with SessionLocal() as db:
            db.add(Screening(screening_id=sid,patient_code=p.patient_code,visit_date=str(p.visit_date),region=p.region,district=p.district,community=p.community,facility=p.facility,age=p.age,sex=p.sex,pregnant=p.pregnant,disease=p.disease,risk_level=r.risk,classification=r.classification,recommendation=r.recommendation,score=r.score,inputs_json=p.model_dump_json(),referred=False,created_at=now)); db.commit()
        color={"Low":"#238636","Moderate":"#c76b00","High":"#c73535","Urgent":"#852c99"}[r.risk]; bmi=f"<p><b>Calculated BMI:</b> {r.bmi}</p>" if r.bmi else ""
        return f"<div class='result' style='border-color:{color}'><b class='badge' style='background:{color}'>{r.risk} priority</b><h3>{r.classification}</h3><p>{r.recommendation}</p>{bmi}<small>{NOTICE}</small></div>",code()
    except Exception as e: return f"<div class='result error'><h3>Check the information entered</h3><p>{e}</p></div>",patient

def records():
    with SessionLocal() as db: rows=db.scalars(select(Screening).order_by(Screening.created_at.desc()).limit(500)).all()
    return pd.DataFrame([[r.visit_date,r.patient_code,r.disease.title(),r.risk_level,r.classification,r.district] for r in rows],columns=["Date","Patient code","Condition","Priority","Classification","District"])

CSS=""".gradio-container{max-width:1380px!important;background:#f4f8f8!important}.hero{background:linear-gradient(120deg,#064b57,#0da0a1);padding:28px 32px;border-radius:22px;color:white;box-shadow:0 12px 35px #07374018}.heroin{display:flex;align-items:center;gap:16px}.logo{width:72px;height:72px;object-fit:cover;border-radius:18px}.hero h1{font-size:clamp(1.8rem,4vw,2.6rem);margin:0}.hero p{color:#d8eeee;margin:4px 0}.creator{margin-left:auto;text-align:right}.creator span,.creator small{display:block;color:#cde8e8}.panel{background:white!important;border:1px solid #dce8e8!important;border-radius:16px!important;box-shadow:0 5px 20px #0737400b!important}.result{background:white;padding:20px;border-radius:15px;border-left:7px solid;box-shadow:0 10px 25px #07374014}.badge{color:white;padding:5px 10px;border-radius:50px}.error{border-color:#c73535}.safety{background:#fff8e8;border:1px solid #efd99e;border-radius:12px;padding:16px}.footer{text-align:center;color:#657b80;padding:20px}@media(max-width:700px){.hero{padding:20px 16px}.heroin{flex-wrap:wrap}.logo{width:56px;height:56px}.creator{margin:0;text-align:left;width:100%}.gradio-container{padding:7px!important}}"""

with gr.Blocks(title="HealthSignal",theme=gr.themes.Soft(primary_hue="teal"),css=CSS) as demo:
    gr.HTML("<div class='hero'><div class='heroin'><img class='logo' src='/gradio_api/file=static/logo.jpg'><div><small>GHANA FOCUSED DIGITAL HEALTH</small><h1>HealthSignal</h1><p>Field screening, early warning and public health decision support</p></div><div class='creator'><span>Created by</span><b>Ebenezer Kwaw</b><small>Public Health and AI</small></div></div></div>")
    with gr.Tabs():
      with gr.Tab("Field Screening"):
        gr.Markdown("## New field screening\nUse a non identifying patient code.")
        with gr.Group(elem_classes="panel"):
          with gr.Row(): patient=gr.Textbox(code(),label="Patient code"); visit=gr.Textbox(str(date.today()),label="Visit date"); age=gr.Number(30,label="Age",precision=0); sex=gr.Dropdown(["Female","Male","Other","Unknown"],"Female",label="Sex")
          with gr.Row(): region=gr.Textbox("Central",label="Region"); district=gr.Textbox("Agona East",label="District"); community=gr.Textbox(label="Community"); facility=gr.Textbox(label="Facility / outreach")
          disease=gr.Radio(["hypertension","diabetes","malaria","tb"],"hypertension",label="Screening module")
          with gr.Group() as hypertension:
            with gr.Row(): s1=gr.Number(120,label="Systolic 1"); d1=gr.Number(80,label="Diastolic 1"); s2=gr.Number(120,label="Systolic 2"); d2=gr.Number(80,label="Diastolic 2")
            with gr.Row(): pulse=gr.Number(75,label="Pulse"); weight=gr.Number(70,label="Weight kg"); height=gr.Number(170,label="Height cm")
          with gr.Group(visible=False) as diabetes:
            with gr.Row(): gtype=gr.Dropdown(["FBS","RBS","Not tested"],"FBS",label="Glucose test"); glucose=gr.Number(5,label="Glucose mmol/L"); family=gr.Checkbox(label="Family history"); previous=gr.Checkbox(label="Previous diagnosis")
          with gr.Group(visible=False) as malaria:
            with gr.Row(): temp=gr.Number(36.8,label="Temperature °C"); mtest=gr.Dropdown(["Not done","RDT","Microscopy"],"Not done",label="Test"); mresult=gr.Dropdown(["Not available","Negative","Positive"],"Not available",label="Result")
            with gr.Row(): fever=gr.Checkbox(label="Fever or recent fever"); pregnant=gr.Checkbox(label="Pregnant")
          with gr.Group(visible=False) as tb:
            with gr.Row(): cough=gr.Checkbox(label="Cough for two weeks or more"); contact=gr.Checkbox(label="Known TB contact"); sweats=gr.Checkbox(label="Night sweats"); loss=gr.Checkbox(label="Unexplained weight loss")
          button=gr.Button("Screen and save",variant="primary")
        output=gr.HTML(); disease.change(visible,disease,[hypertension,diabetes,malaria,tb])
        button.click(submit,[patient,visit,age,sex,region,district,community,facility,disease,s1,d1,s2,d2,pulse,weight,height,gtype,glucose,temp,fever,mtest,mresult,pregnant,family,previous,cough,contact,sweats,loss],[output,patient])
      with gr.Tab("Records"):
        gr.Markdown("## Screening records\nReview non identifying field records."); table=gr.Dataframe(interactive=False); gr.Button("Refresh records").click(records,outputs=table); demo.load(records,outputs=table)
      with gr.Tab("About"):
        gr.Markdown("## Public health intelligence designed for field realities\nHealthSignal is a Ghana focused platform developed by **Ebenezer Kwaw**.\n\n<div class='safety'><b>Clinical safety notice</b><br>HealthSignal is a development and review project. It does not diagnose disease or replace clinical judgement, testing or approved GHS protocols.</div>")
    gr.HTML("<div class='footer'>HealthSignal · Created by Ebenezer Kwaw · Public Health and AI</div>")

if __name__=="__main__": demo.launch()
