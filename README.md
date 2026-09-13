---
title: HealthSignal
emoji: 🩺
colorFrom: teal
colorTo: green
sdk: docker
app_port: 7860
---

# HealthSignal

A Ghana focused field screening, early warning and public health decision support platform created by **Ebenezer Kwaw**.

## Current capabilities

- Responsive frontend for mobile, tablet and laptop
- FastAPI backend and interactive API documentation at `/docs`
- Hypertension, diabetes, malaria and TB screening workflows
- Automatic BMI calculation
- Transparent priority classification and referral recommendations
- Non identifying screening records, surveillance summary and CSV export
- Docker configuration for Hugging Face Spaces

## Run locally

```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 7860
```

Open `http://localhost:7860`.

## Deploy on Hugging Face Spaces

Create a new **Docker Space**, then connect or upload this repository. Hugging Face will build the included `Dockerfile` and serve both the frontend and backend on port `7860`.

## Clinical safety

HealthSignal is a development and clinical review project. It supports screening and surveillance and does not diagnose disease or replace clinical judgement, diagnostic testing or approved Ghana Health Service protocols. It must undergo appropriate clinical, programme, privacy and security review before real patient use.
