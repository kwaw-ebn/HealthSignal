import os
import secrets
import tempfile
from datetime import datetime

db_file=tempfile.NamedTemporaryFile(suffix=".db",delete=False)
db_file.close()
os.environ["DATABASE_URL"]=f"sqlite:///{db_file.name}"
os.environ["JWT_SECRET"]="test-secret-that-is-long-enough"
os.environ["ADMIN_USERNAME"]="test.admin"
ADMIN_TEST_PASSWORD=secrets.token_urlsafe(18)+"Aa1"
WORKER_TEST_PASSWORD=secrets.token_urlsafe(18)+"Aa1"
TEMP_TEST_PASSWORD=secrets.token_urlsafe(18)+"Aa1"
os.environ["ADMIN_PASSWORD"]=ADMIN_TEST_PASSWORD
os.environ["ADMIN_NAME"]="Test Administrator"

from fastapi.testclient import TestClient
from healthsignal_api.main import app

REGISTRATION={
    "username":"ama.mensah","email":"ama@example.com","full_name":"Ama Mensah",
    "phone":"0240000000","staff_id":"GHS-001","facility":"Duakwa Health Centre",
    "district":"Agona East","region":"Central","role":"field_officer",
    "password":WORKER_TEST_PASSWORD,"terms_accepted":True,
}

def admin_headers(client):
    response=client.post("/api/v1/auth/login",json={"username":"test.admin","password":ADMIN_TEST_PASSWORD})
    return {"Authorization":f"Bearer {response.json()['access_token']}"}

def approved_role_headers(client, admin, role, suffix):
    password=secrets.token_urlsafe(18)+"Aa1"
    username=f"{role}.{suffix}"
    account={"username":username,"email":f"{username}@example.com","full_name":role.replace('_',' ').title(),"phone":"0240000099","staff_id":f"GHS-{suffix}","facility":"HealthSignal Demonstration Hospital","district":"Agona East","region":"Central","role":role,"password":password,"terms_accepted":True}
    assert client.post("/api/v1/auth/register",json=account).status_code==201
    user_id=next(u["id"] for u in client.get("/api/v1/users",headers=admin).json() if u["username"]==username)
    assert client.patch(f"/api/v1/users/{user_id}/status",headers=admin,json={"status":"approved","role":role}).status_code==200
    token=client.post("/api/v1/auth/login",json={"username":username,"password":password}).json()["access_token"]
    return {"Authorization":f"Bearer {token}"}

def test_registration_requires_approval():
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/register",json=REGISTRATION).status_code==201
        assert client.post("/api/v1/auth/login",json={"username":"ama.mensah","password":WORKER_TEST_PASSWORD}).status_code==403
        headers=admin_headers(client)
        users=client.get("/api/v1/users",headers=headers).json()
        user_id=next(user["id"] for user in users if user["username"]=="ama.mensah")
        assert client.patch(f"/api/v1/users/{user_id}/status",headers=headers,json={"status":"approved","role":"field_officer"}).status_code==200
        assert client.post("/api/v1/auth/login",json={"username":"ama.mensah","password":WORKER_TEST_PASSWORD}).status_code==200

def test_duplicate_registration_is_rejected():
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/register",json=REGISTRATION).status_code==409

def test_admin_can_suspend_and_reset_password():
    with TestClient(app) as client:
        headers=admin_headers(client)
        users=client.get("/api/v1/users",headers=headers).json()
        user_id=next(user["id"] for user in users if user["username"]=="ama.mensah")
        assert client.post(f"/api/v1/users/{user_id}/reset-password",headers=headers,json={"temporary_password":TEMP_TEST_PASSWORD}).status_code==200
        login=client.post("/api/v1/auth/login",json={"username":"ama.mensah","password":TEMP_TEST_PASSWORD})
        assert login.status_code==200 and login.json()["user"]["password_change_required"] is True
        assert client.patch(f"/api/v1/users/{user_id}/status",headers=headers,json={"status":"suspended"}).status_code==200
        assert client.post("/api/v1/auth/login",json={"username":"ama.mensah","password":TEMP_TEST_PASSWORD}).status_code==403

def test_non_admin_cannot_list_users():
    with TestClient(app) as client:
        headers=admin_headers(client)
        users=client.get("/api/v1/users",headers=headers).json()
        user_id=next(user["id"] for user in users if user["username"]=="ama.mensah")
        client.patch(f"/api/v1/users/{user_id}/status",headers=headers,json={"status":"approved"})
        login=client.post("/api/v1/auth/login",json={"username":"ama.mensah","password":TEMP_TEST_PASSWORD}).json()
        worker_headers={"Authorization":f"Bearer {login['access_token']}"}
        assert client.get("/api/v1/users",headers=worker_headers).status_code==403

def test_relational_encounter_history_and_surveillance():
    with TestClient(app) as client:
        headers=admin_headers(client)
        payload={"patient_code":"PT-FIELD01","visit_date":"2026-09-13","age":34,"sex":"Female","region":"Central","district":"Agona East","community":"Duakwa","facility":"Duakwa Health Centre","disease":"malaria","temperature_c":38.1,"fever_or_history":True,"malaria_test":"RDT","malaria_result":"Positive","case_status":"confirmed","symptoms":["fever","headache"],"lab_test_name":"Malaria RDT","lab_result":"Positive","outcome":"Referred","follow_up_date":"2026-09-16","completion_status":"complete"}
        created=client.post("/api/v1/screenings",headers=headers,json=payload)
        assert created.status_code==201 and created.json()["encounter_id"]
        history=client.get("/api/v1/patients/PT-FIELD01",headers=headers)
        assert history.status_code==200
        assert history.json()["laboratory_tests"][0]["result"]=="Positive"
        summary=client.get("/api/v1/surveillance/summary?days=90",headers=headers)
        assert summary.status_code==200
        assert summary.json()["confirmed"]>=1

def test_flagged_case_enters_clinical_review_and_records_history():
    with TestClient(app) as client:
        headers=admin_headers(client)
        payload={"patient_code":"PT-REVIEW01","visit_date":"2026-09-13","age":42,"sex":"Male","region":"Central","district":"Agona East","community":"Nsaba","facility":"Nsaba Health Centre","disease":"malaria","temperature_c":39.1,"fever_or_history":True,"malaria_test":"Not done","malaria_result":"Not available","case_status":"suspected","completion_status":"incomplete","symptoms":["fever"]}
        assert client.post("/api/v1/screenings",headers=headers,json=payload).status_code==201
        reviews=client.get("/api/v1/reviews?status=awaiting_review",headers=headers)
        assert reviews.status_code==200
        review=next(x for x in reviews.json() if x["patient_code"]=="PT-REVIEW01")
        assert "Encounter is incomplete" in review["flag_reasons"]
        decision={"classification":"inconclusive","recommended_action":"request_laboratory_test","status":"follow_up_required","notes":"Malaria test required before a final classification is recorded.","follow_up_date":"2026-09-15"}
        updated=client.patch(f"/api/v1/reviews/{review['review_id']}",headers=headers,json=decision)
        assert updated.status_code==200
        detail=client.get(f"/api/v1/reviews/{review['review_id']}",headers=headers).json()
        assert detail["status"]=="follow_up_required"
        assert any(event["action"]=="clinical_decision_recorded" for event in detail["history"])

def test_care_network_patient_journey_and_controlled_referral_access():
    with TestClient(app) as client:
        source_headers=admin_headers(client)
        episode=client.post("/api/v1/care-network/episodes",headers=source_headers,json={"age":29,"sex":"Female","community":"Duakwa","visit_type":"OPD","chief_complaint":"Fever and weakness"})
        assert episode.status_code==201
        episode_data=episode.json(); episode_id=episode_data["episode_id"]; patient_code=episode_data["patient_code"]
        triage=client.post(f"/api/v1/care-network/episodes/{episode_id}/triage",headers=source_headers,json={"temperature_c":38.2,"pulse":92,"systolic":118,"diastolic":76,"weight_kg":62,"height_cm":165})
        assert triage.status_code==201 and triage.json()["bmi"]==22.8
        consultation=client.post(f"/api/v1/care-network/episodes/{episode_id}/consultation",headers=source_headers,json={"assessment":"Fever requiring malaria test","plan":"Request RDT and review result","allergies":"None known","disposition":"Laboratory"})
        assert consultation.status_code==201
        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/laboratory",headers=source_headers,json={"test_name":"Malaria RDT","result":"Negative","next_department":"Consulting Room"}).status_code==201
        referral=client.post("/api/v1/care-network/referrals",headers=source_headers,json={"episode_id":episode_id,"destination_facility":"Nsaba Health Centre","receiving_department":"Consulting Room","reason":"Further clinical assessment","clinical_summary":"Fever assessed, malaria RDT negative; continued evaluation requested.","urgency":"urgent","consent_type":"patient","consent_scopes":["demographics","care_summary","allergies","vitals","laboratory"],"validity_hours":72,"consent_confirmed":True})
        assert referral.status_code==201
        access_code=referral.json()["access_code"]

        receiver_password=secrets.token_urlsafe(18)+"Aa1"
        receiver={"username":"receiver.clinician","email":"receiver@example.com","full_name":"Receiving Clinician","phone":"0240000001","staff_id":"GHS-002","facility":"Nsaba Health Centre","district":"Agona East","region":"Central","role":"clinician","password":receiver_password,"terms_accepted":True}
        assert client.post("/api/v1/auth/register",json=receiver).status_code==201
        users=client.get("/api/v1/users",headers=source_headers).json(); receiver_id=next(u["id"] for u in users if u["username"]=="receiver.clinician")
        assert client.patch(f"/api/v1/users/{receiver_id}/status",headers=source_headers,json={"status":"approved","role":"clinician"}).status_code==200
        token=client.post("/api/v1/auth/login",json={"username":"receiver.clinician","password":receiver_password}).json()["access_token"]
        receiver_headers={"Authorization":f"Bearer {token}"}

        denied=client.post("/api/v1/care-network/referrals/access",headers=receiver_headers,json={"patient_code":patient_code,"access_code":"WRONG1","access_reason":"Patient arrived for referred care"})
        assert denied.status_code==403
        shared=client.post("/api/v1/care-network/referrals/access",headers=receiver_headers,json={"patient_code":patient_code,"access_code":access_code,"access_reason":"Patient arrived for referred care"})
        assert shared.status_code==200
        assert shared.json()["referral"]["clinical_summary"].startswith("Fever assessed")
        assert shared.json()["shared_scopes"]==["allergies","care_summary","demographics","laboratory","vitals"]
        assert "medications" not in shared.json()
        assert shared.json()["vitals"]
        assert shared.json()["access_session"]["token"]
        referral_id=shared.json()["referral"]["referral_id"]
        history=client.get(f"/api/v1/care-network/referrals/{referral_id}/access-history",headers=receiver_headers)
        assert history.status_code==200 and history.json()[0]["purpose"]=="referral_treatment"
        assert client.patch(f"/api/v1/care-network/referrals/{referral_id}",headers=receiver_headers,json={"status":"accepted","details":"Referral accepted"}).status_code==200
        assert client.patch(f"/api/v1/care-network/referrals/{referral_id}",headers=receiver_headers,json={"status":"arrived","details":"Patient arrived"}).status_code==200
        assert client.patch(f"/api/v1/care-network/referrals/{referral_id}",headers=receiver_headers,json={"status":"in_care","details":"Clinical review started"}).status_code==200
        completed=client.patch(f"/api/v1/care-network/referrals/{referral_id}",headers=receiver_headers,json={"status":"completed","details":"Assessment completed and feedback returned."})
        assert completed.status_code==200 and completed.json()["status"]=="completed"

def test_referral_emergency_access_and_consent_revocation():
    with TestClient(app) as client:
        source_headers=admin_headers(client)
        episode=client.post("/api/v1/care-network/episodes",headers=source_headers,json={"age":40,"sex":"Male","community":"Nsaba","chief_complaint":"Urgent assessment"}).json()
        referral=client.post("/api/v1/care-network/referrals",headers=source_headers,json={"episode_id":episode["episode_id"],"destination_facility":"Referral Hospital","reason":"Urgent specialist review","clinical_summary":"Patient requires timely specialist assessment.","urgency":"emergency","consent_type":"patient","consent_scopes":["care_summary"],"validity_hours":24,"consent_confirmed":True}).json()
        password=secrets.token_urlsafe(18)+"Aa1"
        account={"username":"emergency.doctor","email":"doctor@example.com","full_name":"Emergency Doctor","phone":"0240000002","staff_id":"GHS-003","facility":"Referral Hospital","district":"Agona East","region":"Central","role":"clinician","password":password,"terms_accepted":True}
        assert client.post("/api/v1/auth/register",json=account).status_code==201
        user_id=next(u["id"] for u in client.get("/api/v1/users",headers=source_headers).json() if u["username"]=="emergency.doctor")
        assert client.patch(f"/api/v1/users/{user_id}/status",headers=source_headers,json={"status":"approved","role":"clinician"}).status_code==200
        token=client.post("/api/v1/auth/login",json={"username":"emergency.doctor","password":password}).json()["access_token"]
        receiver_headers={"Authorization":f"Bearer {token}"}
        emergency=client.post("/api/v1/care-network/referrals/emergency-access",headers=receiver_headers,json={"patient_code":episode["patient_code"],"access_reason":"Patient arrived unconscious and essential history is required now","emergency_confirmed":True})
        assert emergency.status_code==200 and emergency.json()["emergency_access"] is True
        assert emergency.json()["shared_scopes"]==["allergies","care_summary","demographics"]
        revoked=client.post(f"/api/v1/care-network/referrals/{referral['referral_id']}/revoke-consent",headers=source_headers,json={"reason":"Patient withdrew authorization"})
        assert revoked.status_code==200
        denied=client.post("/api/v1/care-network/referrals/access",headers=receiver_headers,json={"patient_code":episode["patient_code"],"access_code":referral["access_code"],"access_reason":"Routine referral treatment"})
        assert denied.status_code==403

def test_care_network_geofence_requires_short_location_grant():
    with TestClient(app) as client:
        headers=admin_headers(client)
        configured=client.put("/api/v1/care-network/security/config",headers=headers,json={"facility":"HealthSignal Demonstration Hospital","latitude":5.6037,"longitude":-0.1870,"allowed_radius_m":250,"geofence_enabled":True})
        assert configured.status_code==200 and configured.json()["geofence_enabled"] is True
        blocked=client.get("/api/v1/care-network/overview",headers=headers)
        assert blocked.status_code==403 and blocked.headers["x-care-location"]=="required"
        outside=client.post("/api/v1/care-network/security/verify",headers=headers,json={"latitude":5.6200,"longitude":-0.1870,"accuracy_m":20})
        assert outside.status_code==403
        verified=client.post("/api/v1/care-network/security/verify",headers=headers,json={"latitude":5.6038,"longitude":-0.1870,"accuracy_m":15})
        assert verified.status_code==200 and verified.json()["verified"] is True
        grant=verified.json()["care_access_token"]
        allowed=client.get("/api/v1/care-network/overview",headers={**headers,"X-Care-Access":grant})
        assert allowed.status_code==200
        wrong_grant=client.get("/api/v1/care-network/overview",headers={**headers,"X-Care-Access":"not-a-valid-grant"})
        assert wrong_grant.status_code==403

def test_department_accounts_have_separate_least_privilege_workspaces():
    with TestClient(app) as client:
        admin=admin_headers(client)
        client.put("/api/v1/care-network/security/config",headers=admin,json={"facility":"HealthSignal Demonstration Hospital","latitude":5.6037,"longitude":-0.1870,"allowed_radius_m":250,"geofence_enabled":False})
        records=approved_role_headers(client,admin,"records_officer","101")
        opd=approved_role_headers(client,admin,"opd_nurse","102")
        laboratory=approved_role_headers(client,admin,"laboratory_officer","103")
        pharmacy=approved_role_headers(client,admin,"pharmacist","104")

        episode=client.post("/api/v1/care-network/episodes",headers=records,json={"age":31,"sex":"Female","community":"Duakwa","chief_complaint":"Fever"})
        assert episode.status_code==201
        episode_id=episode.json()["episode_id"]
        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/triage",headers=records,json={"pulse":80}).status_code==403

        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/triage",headers=opd,json={"temperature_c":37.8,"pulse":88}).status_code==201
        assert client.post("/api/v1/care-network/episodes",headers=opd,json={"age":20,"sex":"Male","chief_complaint":"Test"}).status_code==403
        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/laboratory",headers=opd,json={"test_name":"RDT","result":"Negative"}).status_code==403

        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/consultation",headers=admin,json={"assessment":"Test requested","plan":"Laboratory review","disposition":"Laboratory"}).status_code==201
        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/laboratory",headers=laboratory,json={"test_name":"Malaria RDT","result":"Negative"}).status_code==201
        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/triage",headers=laboratory,json={"pulse":80}).status_code==403

        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/medications",headers=admin,json={"medicine":"Paracetamol","instructions":"Use as prescribed"}).status_code==201
        queue=client.get("/api/v1/care-network/medications",headers=pharmacy)
        assert queue.status_code==200 and queue.json()
        order_id=queue.json()[0]["order_id"]
        assert client.patch(f"/api/v1/care-network/medications/{order_id}/dispense",headers=pharmacy).status_code==200
        assert client.get("/api/v1/care-network/medications",headers=opd).status_code==403

def test_insurance_claim_is_created_from_records_and_collects_services_for_xml():
    with TestClient(app) as client:
        admin=admin_headers(client)
        client.put("/api/v1/care-network/security/config",headers=admin,json={"facility":"HealthSignal Demonstration Hospital","latitude":5.6037,"longitude":-0.1870,"allowed_radius_m":250,"geofence_enabled":False})
        insurance=approved_role_headers(client,admin,"insurance_officer","201")
        episode=client.post("/api/v1/care-network/episodes",headers=admin,json={"age":36,"sex":"Female","community":"Duakwa","chief_complaint":"Review","insurance_number":"NHIS-TEST-001","ccc_number":"CCC-001","surname":"Mensah","other_names":"Ama","date_of_birth":"1990-01-10","folder_number":"F-100","attendance_type":"Emergency/Acute Episode"})
        assert episode.status_code==201 and episode.json()["insurance_claim_created"] is True
        episode_id=episode.json()["episode_id"]
        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/consultation",headers=admin,json={"assessment":"Clinical assessment for insurance test","plan":"Laboratory and medication","disposition":"Laboratory"}).status_code==201
        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/laboratory",headers=admin,json={"test_name":"Full blood count","result":"Reviewed"}).status_code==201
        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/medications",headers=admin,json={"medicine":"Test medicine","instructions":"Use as directed"}).status_code==201
        claims=client.get("/api/v1/care-network/insurance/claims",headers=insurance)
        assert claims.status_code==200
        claim=next(x for x in claims.json() if x["episode_id"]==episode_id)
        detail=client.get(f"/api/v1/care-network/insurance/claims/{claim['claim_id']}",headers=insurance).json()
        assert detail["diagnoses"] and detail["investigations"] and detail["medicines"]
        assert client.post("/api/v1/care-network/episodes",headers=insurance,json={"age":20,"sex":"Male","chief_complaint":"Denied"}).status_code==403
        updated=client.patch(f"/api/v1/care-network/insurance/claims/{claim['claim_id']}",headers=insurance,json={"physician_name_id":"DR-001","service_outcome":"Discharged","specialty":"OPDC","principal_gdrg":"MVP-TEST","manual_entries":[{"type":"procedure","code":"PROC-01","description":"Clinical procedure","quantity":1,"unit_cost":20}]})
        assert updated.status_code==200
        validated=client.post(f"/api/v1/care-network/insurance/claims/{claim['claim_id']}/validate",headers=insurance)
        assert validated.status_code==200 and validated.json()["status"]=="ready_for_export"
        exported=client.get(f"/api/v1/care-network/insurance/claims/{claim['claim_id']}/xml",headers=insurance)
        assert exported.status_code==200 and exported.headers["content-type"].startswith("application/xml")
        assert b"NHIA-standardized-eclaims" in exported.content and b"NHIS-TEST-001" in exported.content

def test_admission_service_billing_insurance_routing_and_clearance_reports():
    with TestClient(app) as client:
        admin=admin_headers(client)
        client.put("/api/v1/care-network/security/config",headers=admin,json={"facility":"HealthSignal Demonstration Hospital","latitude":5.6037,"longitude":-0.1870,"allowed_radius_m":250,"geofence_enabled":False})
        episode=client.post("/api/v1/care-network/episodes",headers=admin,json={"age":45,"sex":"Male","community":"Nsaba","chief_complaint":"Admission test","insurance_number":"NHIS-BILL-1","ccc_number":"CCC-BILL-1","surname":"Test","attendance_type":"OPD"}).json()
        episode_id=episode["episode_id"]
        admitted=client.post(f"/api/v1/care-network/episodes/{episode_id}/consultation",headers=admin,json={"assessment":"Requires inpatient observation","plan":"Admit and monitor","disposition":"Admit","ward":"Male Ward","charge_amount":50,"insurance_covered":True})
        assert admitted.status_code==201 and admitted.json()["next_department"]=="Admit"
        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/laboratory",headers=admin,json={"test_name":"Full blood count","result":"Reviewed","charge_amount":25,"insurance_covered":False}).status_code==201
        assert client.post(f"/api/v1/care-network/episodes/{episode_id}/medications",headers=admin,json={"medicine":"Test medicine","instructions":"Ward treatment","charge_amount":15,"insurance_covered":True}).status_code==201
        bill=client.get(f"/api/v1/care-network/billing/episodes/{episode_id}",headers=admin).json()
        assert bill["visit_type"]=="Inpatient" and bill["insurance_total"]==65 and bill["patient_balance"]==25
        claim=next(x for x in client.get("/api/v1/care-network/insurance/claims",headers=admin).json() if x["episode_id"]==episode_id)
        assert client.patch(f"/api/v1/care-network/insurance/claims/{claim['claim_id']}",headers=admin,json={"physician_name_id":"DR-1","service_outcome":"Discharged","specialty":"MEDI","principal_gdrg":"TEST"}).status_code==200
        assert client.get(f"/api/v1/care-network/insurance/claims/{claim['claim_id']}",headers=admin).json()["attendance_type"]=="Inpatient"
        assert client.post(f"/api/v1/care-network/insurance/claims/{claim['claim_id']}/validate",headers=admin).status_code==200
        assert client.get(f"/api/v1/care-network/insurance/claims/{claim['claim_id']}/xml",headers=admin).status_code==200
        paid=client.post(f"/api/v1/care-network/billing/episodes/{episode_id}/pay",headers=admin,json={"payment_method":"Mobile Money"})
        assert paid.status_code==200 and paid.json()["amount"]==25
        cleared=client.post(f"/api/v1/care-network/billing/episodes/{episode_id}/clear",headers=admin)
        assert cleared.status_code==200 and cleared.json()["status"]=="completed"
        month=datetime.utcnow().strftime("%Y-%m")
        assert client.get(f"/api/v1/care-network/reports/monthly?month={month}",headers=admin).status_code==200
        assert client.get(f"/api/v1/care-network/reports/financial?month={month}",headers=admin).json()["billed"]>=90
        assert client.get(f"/api/v1/care-network/reports/system-usage?month={month}",headers=admin).status_code==200
