import os
import sys
import tempfile
from pathlib import Path

# Use an isolated temporary SQLite database for tests
_TMP_DIR = tempfile.TemporaryDirectory()
os.environ["PULSO_DB_PATH"] = str(Path(_TMP_DIR.name) / "test_pulso.sqlite3")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from server.app import app  # noqa: E402


def test_health_and_catalogs():
    with TestClient(app) as client:
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        cat = client.get("/api/catalogs")
        assert cat.status_code == 200
        data = cat.json()
        assert len(data["learning"]["topics"]) == 23
        assert len(data["registration"]["categories"]) == 8


def test_patient_registration_by_sns_and_empty_wallet():
    with TestClient(app) as client:
        # Invalid SNS (not 9 digits)
        bad = client.post("/api/auth/register", json={
            "snsNumber": "12345",
            "fullName": "Teste Inválido",
            "birthDate": "1990-01-01",
            "password": "password123"
        })
        assert bad.status_code == 422

        # Valid 9-digit SNS
        reg = client.post("/api/auth/register", json={
            "snsNumber": "298765432",
            "fullName": "Maria João Costa",
            "birthDate": "1985-05-14",
            "password": "password123",
            "email": "maria@exemplo.pt"
        })
        assert reg.status_code == 200
        body = reg.json()
        assert body["role"] == "patient"
        assert body["snsNumber"] == "298765432"

        # New patient starts with empty wallet
        recs = client.get("/api/records")
        assert recs.status_code == 200
        assert recs.json()["exams"] == []


def test_dual_login_and_rbac_enforcement():
    # Patient logs in, creates a share code, then Doctor logs in with it
    with TestClient(app) as patient_client:
        login_p = patient_client.post("/api/auth/login/patient", json={
            "snsNumber": "234891024",
            "password": "pulso1234"
        })
        assert login_p.status_code == 200
        assert login_p.json()["role"] == "patient"

        recs = patient_client.get("/api/records").json()
        assert len(recs["exams"]) >= 4
        first_exam_id = recs["exams"][0]["id"]

        code_res = patient_client.post("/api/share-codes", json={"durationKey": "1h"})
        assert code_res.status_code == 200
        code = code_res.json()["code"]
        assert len(code) == 8

        # Doctor logs in with the 8-digit code in a separate client
        with TestClient(app) as doctor_client:
            login_d = doctor_client.post("/api/auth/login/doctor", json={
                "licenseNumber": "48192",
                "accessCode": code
            })
            assert login_d.status_code == 200
            assert login_d.json()["role"] == "doctor"

            # Doctor CAN read records
            d_recs = doctor_client.get("/api/records")
            assert d_recs.status_code == 200
            assert len(d_recs.json()["exams"]) >= 4

            # Doctor CAN add a consultation measurement
            m_res = doctor_client.post("/api/measurements", json={
                "kind": "pressure",
                "systolic": 126,
                "diastolic": 80,
                "heartRate": 74,
                "measuredAt": "2026-11-15T12:00",
                "notes": "Medição em consulta"
            })
            assert m_res.status_code == 200

            # Doctor CANNOT delete patient's exam (403)
            del_res = doctor_client.delete(f"/api/exams/{first_exam_id}")
            assert del_res.status_code == 403

            # Doctor CANNOT generate share codes (403)
            sc_res = doctor_client.post("/api/share-codes", json={"durationKey": "1h"})
            assert sc_res.status_code == 403

            # Doctor CANNOT change patient preferences (403)
            pref_res = doctor_client.patch("/api/auth/preferences", json={"theme": "light"})
            assert pref_res.status_code == 403


def test_pdf_extraction_exam_crud_and_events():
    demo_pdf = ROOT / "server" / "shared" / "laboratorio-demo.pdf"
    assert demo_pdf.exists()

    with TestClient(app) as client:
        client.post("/api/auth/login/patient", json={
            "snsNumber": "234891024",
            "password": "pulso1234"
        })

        with demo_pdf.open("rb") as fh:
            ext = client.post("/api/extractions", files={"file": ("laboratorio-demo.pdf", fh, "application/pdf")})
        assert ext.status_code == 200
        ext_data = ext.json()
        assert "extraction" in ext_data
        extracted = ext_data["extraction"]

        # Create exam from extraction
        created = client.post("/api/exams", json={
            "title": extracted.get("title") or "Análises Demo",
            "category": extracted.get("category") or "blood_tests",
            "issuer": extracted.get("issuer") or "Lab Demo",
            "examDate": "2026-11-15",
            "summary": "Extraído de PDF Demo",
            "extractedValues": extracted.get("extractedValues", [])
        })
        assert created.status_code == 200
        exam_id = created.json()["id"]

        # Edit classification without duplicating
        before_count = len(client.get("/api/records").json()["exams"])
        patched = client.patch(f"/api/exams/{exam_id}", json={
            "category": "clinical_reports",
            "issuer": "USF São João"
        })
        assert patched.status_code == 200
        after_count = len(client.get("/api/records").json()["exams"])
        assert before_count == after_count

        # Create & delete clinical event
        ev = client.post("/api/events", json={
            "title": "Ajuste terapêutico",
            "eventType": "medication",
            "startDate": "2026-11-15",
            "notes": "Teste"
        })
        assert ev.status_code == 200
        ev_id = ev.json()["id"]
        assert client.delete(f"/api/events/{ev_id}").status_code == 200
