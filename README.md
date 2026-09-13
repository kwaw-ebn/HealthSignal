---
title: HealthSignal
emoji: 🩺
colorFrom: teal
colorTo: green
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
pinned: false
---

# HealthSignal

A Ghana focused field screening, early warning and public health decision support platform created by **Ebenezer Kwaw**.

## Current capabilities

- Responsive frontend for mobile, tablet and laptop
- Python screening and data backend hosted with the interface
- Hypertension, diabetes, malaria and TB screening workflows
- Automatic BMI calculation
- Transparent priority classification and referral recommendations
- Non identifying screening records, surveillance summary and CSV export
- Docker configuration for Hugging Face Spaces

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:7860`.

## Deploy on Hugging Face Spaces

Create a new **Docker Space**, then connect or upload this repository. Hugging Face will build the included `Dockerfile` and serve both the frontend and backend on port `7860`.

## Clinical safety

HealthSignal is a development and clinical review project. It supports screening and surveillance and does not diagnose disease or replace clinical judgement, diagnostic testing or approved Ghana Health Service protocols. It must undergo appropriate clinical, programme, privacy and security review before real patient use.
