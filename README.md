# HealthSignal

A Ghana focused field screening, early warning and public health decision support platform created by **Ebenezer Kwaw**.

## Features

- Professional custom responsive frontend for mobile, tablet and laptop
- FastAPI backend serving the website and API
- Hypertension, diabetes, malaria and TB screening workflows
- Automatic BMI calculation
- Transparent priority classifications and referral recommendations
- Non identifying records, surveillance dashboard and CSV export
- HealthSignal Care Network hospital operations workspace
- Records, OPD triage, consultation, laboratory and pharmacy workflow
- Multi facility patient journeys and department queues
- Controlled inter facility referral handover using an authorized account, patient ID, time limited referral code and documented access reason
- Referral acceptance, arrival, care and completion feedback states
- Optional facility geofence with browser location verification and 20 minute Care Network access grants
- Location verification denials and approvals recorded in the security audit log
- Render Blueprint configuration

## Run locally

```bash
pip install -r requirements.txt
uvicorn healthsignal_api.main:app --reload --port 8000
```

Open `http://localhost:8000`. API documentation is available at `/docs`.

## Deploy on Render

The included `render.yaml` deploys HealthSignal as one free Render web service. The frontend and backend share one origin for faster loading and simpler configuration.

The free service uses temporary SQLite storage for portfolio testing. Connect a managed PostgreSQL database before collecting real programme or patient data.

## Clinical safety

HealthSignal is a development and clinical review project. It supports screening, care coordination and surveillance and does not diagnose disease or replace clinical judgement, diagnostic testing or approved Ghana Health Service protocols. The Care Network is a stakeholder demonstration and must use synthetic data until privacy, security, clinical governance, interoperability and regulatory reviews are complete.
