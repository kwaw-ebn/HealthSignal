from datetime import date
from healthsignal_api.rules import screen
from healthsignal_api.schemas import ScreeningRequest

def base(**changes):
    data={"patient_code":"PT-001","visit_date":date.today(),"age":35,"sex":"Female","disease":"hypertension"}; data.update(changes); return ScreeningRequest(**data)
def test_urgent_bp(): assert screen(base(systolic_1=185,diastolic_1=100)).risk=="Urgent"
def test_positive_malaria(): assert screen(base(disease="malaria",malaria_test="RDT",malaria_result="Positive")).risk=="High"
def test_tb_screen(): assert screen(base(disease="tb",cough_two_weeks=True)).classification.startswith("Presumptive")
def test_bmi(): assert screen(base(systolic_1=120,diastolic_1=80,weight_kg=70,height_cm=175)).bmi==22.9
def test_maternal_warning_indicator_prioritizes_referral(): assert screen(base(disease="maternal_risk",gestational_age_weeks=30,maternal_warning_signs="severe headache")).risk=="Urgent"
def test_child_nutrition_oedema_prioritizes_referral(): assert screen(base(disease="childhood_malnutrition",age=2,bilateral_oedema=True)).risk=="Urgent"
def test_anaemia_screening_priority(): assert screen(base(disease="anaemia_pregnancy",pregnant=True,haemoglobin_g_dl=9.5)).risk=="High"
def test_hiv_linkage_priority(): assert screen(base(disease="hiv_linkage",test_offered=True,hiv_result_category="Reactive")).risk=="High"
def test_diarrhoea_dehydration_priority(): assert screen(base(disease="cholera_diarrhoea",dehydration_level="Severe")).risk=="Urgent"
def test_measles_signal_priority(): assert screen(base(disease="measles",rash_present=True,fever_or_history=True)).risk=="High"
def test_meningitis_warning_priority(): assert screen(base(disease="meningitis",neck_stiffness=True,fever_or_history=True)).risk=="Urgent"
def test_respiratory_low_oxygen_priority(): assert screen(base(disease="acute_respiratory_infection",oxygen_saturation=88)).risk=="Urgent"
def test_hepatitis_test_priority(): assert screen(base(disease="hepatitis",disease_test_result="Positive")).risk=="High"
def test_wellbeing_tool_priority(): assert screen(base(disease="mental_health",questionnaire_name="Approved local tool",questionnaire_score=8,questionnaire_risk="Moderate")).risk=="Moderate"
def test_other_ncd_selected_priority(): assert screen(base(disease="other_ncd",ncd_condition="Chronic condition",ncd_reported_priority="High priority")).risk=="High"
