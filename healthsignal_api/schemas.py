from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

SUPPORTED_MODULES={"hypertension","diabetes","malaria","tb","maternal_risk","childhood_malnutrition","anaemia_pregnancy","hiv_linkage","cholera_diarrhoea","measles","meningitis","acute_respiratory_infection","hepatitis","mental_health","other_ncd"}

class ScreeningRequest(BaseModel):
    patient_code: str = Field(min_length=2, max_length=64)
    visit_date: date
    region: str = ""; district: str = ""; community: str = ""; facility: str = ""
    age: int = Field(ge=0, le=120)
    sex: Literal["Female", "Male", "Other", "Unknown"]
    pregnant: bool = False
    disease: str
    systolic_1: int | None = Field(default=None, ge=40, le=300)
    diastolic_1: int | None = Field(default=None, ge=20, le=200)
    systolic_2: int | None = Field(default=None, ge=40, le=300)
    diastolic_2: int | None = Field(default=None, ge=20, le=200)
    pulse: int | None = Field(default=None, ge=20, le=250)
    respiratory_rate: int | None = Field(default=None, ge=5, le=100)
    oxygen_saturation: float | None = Field(default=None, ge=40, le=100)
    weight_kg: float | None = Field(default=None, gt=0, le=400)
    height_cm: float | None = Field(default=None, gt=30, le=250)
    glucose_type: Literal["Not tested", "FBS", "RBS"] = "Not tested"
    glucose_mmol_l: float | None = Field(default=None, ge=0, le=50)
    temperature_c: float | None = Field(default=None, ge=30, le=45)
    fever_or_history: bool = False
    malaria_test: Literal["Not done", "RDT", "Microscopy"] = "Not done"
    malaria_result: Literal["Not available", "Negative", "Positive"] = "Not available"
    cough_two_weeks: bool = False; tb_contact: bool = False; night_sweats: bool = False
    unexplained_weight_loss: bool = False; family_history: bool = False; previous_diagnosis: bool = False
    symptoms: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=2000)
    lab_test_name: str | None = Field(default=None, max_length=100)
    lab_result: str | None = Field(default=None, max_length=120)
    lab_result_unit: str | None = Field(default=None, max_length=40)
    outcome: str | None = Field(default=None, max_length=120)
    follow_up_date: date | None = None
    completion_status: Literal["complete","incomplete"] = "complete"
    case_status: Literal["suspected","tested","confirmed","excluded"] = "suspected"
    referred: bool = False
    referral_destination: str | None = Field(default=None, max_length=160)
    referral_reason: str | None = Field(default=None, max_length=1000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    gps_consent: bool = False
    gestational_age_weeks: int | None = Field(default=None, ge=0, le=45)
    gravida: int | None = Field(default=None, ge=0, le=30); parity: int | None = Field(default=None, ge=0, le=30); anc_visits: int | None = Field(default=None, ge=0, le=30)
    haemoglobin_g_dl: float | None = Field(default=None, ge=1, le=25)
    hiv_test_status: str | None = Field(default=None, max_length=40); syphilis_test_status: str | None = Field(default=None, max_length=40)
    previous_caesarean: bool = False; multiple_pregnancy: bool = False; reduced_fetal_movement: bool = False
    maternal_warning_signs: str | None = Field(default=None, max_length=500)
    muac_cm: float | None = Field(default=None, ge=5, le=40); bilateral_oedema: bool = False; feeding_problem: bool = False; feeding_history: str | None = Field(default=None, max_length=500)
    anaemia_symptoms: str | None = Field(default=None, max_length=500); iron_folic_acid_status: str | None = Field(default=None, max_length=40); pregnancy_malaria_status: str | None = Field(default=None, max_length=40)
    test_offered: bool = False; hiv_result_category: str | None = Field(default=None, max_length=40); confirmation_status: str | None = Field(default=None, max_length=40); linkage_status: str | None = Field(default=None, max_length=40)
    stool_count_24h: int | None = Field(default=None, ge=0, le=100); diarrhoea_duration_days: int | None = Field(default=None, ge=0, le=90); dehydration_level: str | None = Field(default=None, max_length=40); specimen_status: str | None = Field(default=None, max_length=40); disease_test_result: str | None = Field(default=None, max_length=40)
    rash_present: bool = False; vaccination_status: str | None = Field(default=None, max_length=40); symptom_onset_date: date | None = None; contact_history: bool = False
    neck_stiffness: bool = False; altered_consciousness: bool = False; breathing_difficulty: bool = False; cough_present: bool = False
    hepatitis_exposure: str | None = Field(default=None, max_length=500); jaundice_present: bool = False
    questionnaire_name: str | None = Field(default=None, max_length=80); questionnaire_score: float | None = Field(default=None, ge=0, le=1000); questionnaire_risk: str | None = Field(default=None, max_length=30); functional_impairment: bool = False; urgent_safety_concern: bool = False
    ncd_condition: str | None = Field(default=None, max_length=100); ncd_measurement: float | None = None; ncd_unit: str | None = Field(default=None, max_length=40); ncd_reported_priority: str | None = Field(default=None, max_length=30)
    @field_validator("disease")
    @classmethod
    def module_supported(cls,value):
        if value not in SUPPORTED_MODULES: raise ValueError("Unsupported screening module")
        return value
    @model_validator(mode="after")
    def checks(self):
        if self.glucose_type != "Not tested" and self.glucose_mmol_l is None: raise ValueError("Enter the measured glucose result.")
        if self.malaria_result != "Not available" and self.malaria_test == "Not done": raise ValueError("Select the malaria test performed.")
        if self.referred and not self.referral_destination: raise ValueError("Enter the referral destination.")
        return self

class ScreeningResult(BaseModel):
    screening_id: str; encounter_id: str; disease: str
    risk_level: Literal["Low", "Moderate", "High", "Urgent"]
    classification: str; recommendation: str; score: float
    bmi: float | None = None; disclaimer: str; created_at: datetime
