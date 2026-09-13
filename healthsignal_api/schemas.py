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
