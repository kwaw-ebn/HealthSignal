from datetime import date
from healthsignal_api.rules import screen
from healthsignal_api.schemas import ScreeningRequest

def base(**changes):
    data={"patient_code":"PT-001","visit_date":date.today(),"age":35,"sex":"Female","disease":"hypertension"}; data.update(changes); return ScreeningRequest(**data)
def test_urgent_bp(): assert screen(base(systolic_1=185,diastolic_1=100)).risk=="Urgent"
def test_positive_malaria(): assert screen(base(disease="malaria",malaria_test="RDT",malaria_result="Positive")).risk=="High"
def test_tb_screen(): assert screen(base(disease="tb",cough_two_weeks=True)).classification.startswith("Presumptive")
def test_bmi(): assert screen(base(systolic_1=120,diastolic_1=80,weight_kg=70,height_cm=175)).bmi==22.9
