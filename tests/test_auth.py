import os
import tempfile

db_file=tempfile.NamedTemporaryFile(suffix=".db",delete=False)
db_file.close()
os.environ["DATABASE_URL"]=f"sqlite:///{db_file.name}"
os.environ["JWT_SECRET"]="test-secret-that-is-long-enough"
os.environ["ADMIN_USERNAME"]="test.admin"
os.environ["ADMIN_PASSWORD"]="AdminPassword123"
os.environ["ADMIN_NAME"]="Test Administrator"

from fastapi.testclient import TestClient
from healthsignal_api.main import app

REGISTRATION={
    "username":"ama.mensah","email":"ama@example.com","full_name":"Ama Mensah",
    "phone":"0240000000","staff_id":"GHS-001","facility":"Duakwa Health Centre",
    "district":"Agona East","region":"Central","role":"field_worker",
    "password":"StrongWorker123","terms_accepted":True,
}

def admin_headers(client):
    response=client.post("/api/v1/auth/login",json={"username":"test.admin","password":"AdminPassword123"})
    return {"Authorization":f"Bearer {response.json()['access_token']}"}

def test_registration_requires_approval():
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/register",json=REGISTRATION).status_code==201
        assert client.post("/api/v1/auth/login",json={"username":"ama.mensah","password":"StrongWorker123"}).status_code==403
        headers=admin_headers(client)
        users=client.get("/api/v1/users",headers=headers).json()
        user_id=next(user["id"] for user in users if user["username"]=="ama.mensah")
        assert client.patch(f"/api/v1/users/{user_id}/status",headers=headers,json={"status":"approved","role":"field_worker"}).status_code==200
        assert client.post("/api/v1/auth/login",json={"username":"ama.mensah","password":"StrongWorker123"}).status_code==200

def test_duplicate_registration_is_rejected():
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/register",json=REGISTRATION).status_code==409

def test_admin_can_suspend_and_reset_password():
    with TestClient(app) as client:
        headers=admin_headers(client)
        users=client.get("/api/v1/users",headers=headers).json()
        user_id=next(user["id"] for user in users if user["username"]=="ama.mensah")
        assert client.post(f"/api/v1/users/{user_id}/reset-password",headers=headers,json={"temporary_password":"TemporaryPass123"}).status_code==200
        login=client.post("/api/v1/auth/login",json={"username":"ama.mensah","password":"TemporaryPass123"})
        assert login.status_code==200 and login.json()["user"]["password_change_required"] is True
        assert client.patch(f"/api/v1/users/{user_id}/status",headers=headers,json={"status":"suspended"}).status_code==200
        assert client.post("/api/v1/auth/login",json={"username":"ama.mensah","password":"TemporaryPass123"}).status_code==403

def test_non_admin_cannot_list_users():
    with TestClient(app) as client:
        headers=admin_headers(client)
        users=client.get("/api/v1/users",headers=headers).json()
        user_id=next(user["id"] for user in users if user["username"]=="ama.mensah")
        client.patch(f"/api/v1/users/{user_id}/status",headers=headers,json={"status":"approved"})
        login=client.post("/api/v1/auth/login",json={"username":"ama.mensah","password":"TemporaryPass123"}).json()
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
