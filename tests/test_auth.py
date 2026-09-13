import os
import secrets
import tempfile

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
        referral=client.post("/api/v1/care-network/referrals",headers=source_headers,json={"episode_id":episode_id,"destination_facility":"Nsaba Health Centre","reason":"Further clinical assessment","clinical_summary":"Fever assessed, malaria RDT negative; continued evaluation requested.","urgency":"urgent","consent_confirmed":True})
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
        assert any(event["event_type"]=="triage" for event in shared.json()["timeline"])
        referral_id=shared.json()["referral"]["referral_id"]
        assert client.patch(f"/api/v1/care-network/referrals/{referral_id}",headers=receiver_headers,json={"status":"accepted","details":"Referral accepted"}).status_code==200
        assert client.patch(f"/api/v1/care-network/referrals/{referral_id}",headers=receiver_headers,json={"status":"arrived","details":"Patient arrived"}).status_code==200
        assert client.patch(f"/api/v1/care-network/referrals/{referral_id}",headers=receiver_headers,json={"status":"in_care","details":"Clinical review started"}).status_code==200
        completed=client.patch(f"/api/v1/care-network/referrals/{referral_id}",headers=receiver_headers,json={"status":"completed","details":"Assessment completed and feedback returned."})
        assert completed.status_code==200 and completed.json()["status"]=="completed"

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
