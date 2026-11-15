"""SQLite persistence layer for the unified PULSO prototype."""
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from argon2 import PasswordHasher

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("PULSO_DB_PATH", str(ROOT / ".local" / "pulso.sqlite3")))
HASHER = PasswordHasher(time_cost=2, memory_cost=32768, parallelism=1)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    sns_number TEXT UNIQUE,
    license_number TEXT UNIQUE,
    role TEXT NOT NULL CHECK(role IN ('patient', 'doctor')),
    full_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    birth_date TEXT,
    email TEXT,
    password_hash TEXT NOT NULL,
    preferences TEXT NOT NULL DEFAULT '{}',
    clinical_alerts TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    patient_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    grant_code TEXT,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS share_codes (
    code TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    duration_key TEXT NOT NULL,
    duration_label TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS exams (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    exam_type TEXT NOT NULL,
    specialty TEXT NOT NULL DEFAULT 'medicina_geral',
    issuer TEXT NOT NULL DEFAULT 'Registo Pessoal',
    exam_date TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    extracted_values TEXT NOT NULL DEFAULT '[]',
    file_name TEXT,
    mime_type TEXT,
    file_blob BLOB,
    added_by_role TEXT NOT NULL DEFAULT 'patient',
    added_by_name TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS measurements (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('pressure', 'spo2', 'glucose')),
    systolic INTEGER,
    diastolic INTEGER,
    heart_rate INTEGER,
    spo2 REAL,
    value REAL,
    unit TEXT,
    measured_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    added_by_role TEXT NOT NULL DEFAULT 'patient',
    added_by_name TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    event_type TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,
    notes TEXT NOT NULL DEFAULT '',
    exam_id TEXT,
    added_by_role TEXT NOT NULL DEFAULT 'patient',
    added_by_name TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor_role TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
"""


@contextmanager
def get_db(write: bool = False):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def seed_demo_data():
    """Seed realistic demo patient (Sr. António Silva) and doctor (Dra. Marta Fernandes) if DB is empty."""
    with get_db(write=True) as db:
        count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count > 0:
            return

        now = time.time()
        patient_id = "pat-antonio-silva"
        doctor_id = "doc-marta-fernandes"

        alerts = [
            {"severity": "high", "title": "Alergia Grave a Iodo", "detail": "Evitar contrastes radiológicos iodados."},
            {"severity": "medium", "title": "Pacemaker Cardíaco", "detail": "Implante permanente — precaução em RMN."},
            {"severity": "info", "title": "Anticoagulação (Varfarina 5mg)", "detail": "Monitorização regular de INR."},
        ]
        prefs = {
            "theme": "dark",
            "mode": "balanced",
            "textSize": "standard",
        }

        db.execute(
            """INSERT INTO users(id, sns_number, license_number, role, full_name, display_name, birth_date, email, password_hash, preferences, clinical_alerts, created_at)
               VALUES (?, ?, NULL, 'patient', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                patient_id,
                "234891024",
                "António José da Silva",
                "Sr. António Silva",
                "1958-04-12",
                "antonio.silva@inbox.pulso.health",
                HASHER.hash("pulso1234"),
                json.dumps(prefs),
                json.dumps(alerts),
                now,
            ),
        )

        db.execute(
            """INSERT INTO users(id, sns_number, license_number, role, full_name, display_name, birth_date, email, password_hash, preferences, clinical_alerts, created_at)
               VALUES (?, NULL, ?, 'doctor', ?, ?, ?, ?, ?, ?, '[]', ?)""",
            (
                doctor_id,
                "48192",
                "Dra. Marta Fernandes",
                "Dra. Marta Fernandes",
                "1978-09-20",
                "marta.fernandes@usfsaojoao.pt",
                HASHER.hash("medica1234"),
                json.dumps(prefs),
                now,
            ),
        )

        # Seed default 8-digit share code for presentation convenience (valid 24h)
        db.execute(
            """INSERT INTO share_codes(code, patient_id, duration_key, duration_label, created_at, expires_at, revoked)
               VALUES ('74921830', ?, '1h', '1 Hora', ?, ?, 0)""",
            (patient_id, now, now + 86400),
        )

        # Seed longitudinal exams
        seed_exams = [
            (
                "ex-unilabs-2026-10",
                "Painel Metabólico e Perfil Lipídico",
                "blood_tests",
                "blood_panel",
                "endocrinology",
                "Unilabs (Privado)",
                "2026-10-18",
                "Glicose em jejum: 118 mg/dL; Colesterol LDL: 132 mg/dL; Creatinina: 1.08 mg/dL.",
                [
                    {"parameter": "glucose", "label": "Glicose em Jejum", "value": 118, "unit": "mg/dL", "reference": "70 - 99", "verification": "text_verified"},
                    {"parameter": "ldl", "label": "Colesterol LDL", "value": 132, "unit": "mg/dL", "reference": "< 115", "verification": "text_verified"},
                    {"parameter": "creatinine", "label": "Creatinina Sérica", "value": 1.08, "unit": "mg/dL", "reference": "0.70 - 1.25", "verification": "text_verified"},
                    {"parameter": "hba1c", "label": "HbA1c", "value": 6.2, "unit": "%", "reference": "4.0 - 5.7", "verification": "text_verified"},
                ],
            ),
            (
                "ex-sns-2026-06",
                "Análises de Rotina — USF São João",
                "blood_tests",
                "blood_panel",
                "general_practice",
                "SNS · Centro de Saúde",
                "2026-06-05",
                "Glicose: 109 mg/dL; Colesterol LDL: 141 mg/dL; Creatinina: 1.02 mg/dL.",
                [
                    {"parameter": "glucose", "label": "Glicose em Jejum", "value": 109, "unit": "mg/dL", "reference": "70 - 99", "verification": "text_verified"},
                    {"parameter": "ldl", "label": "Colesterol LDL", "value": 141, "unit": "mg/dL", "reference": "< 115", "verification": "text_verified"},
                    {"parameter": "creatinine", "label": "Creatinina Sérica", "value": 1.02, "unit": "mg/dL", "reference": "0.70 - 1.25", "verification": "text_verified"},
                ],
            ),
            (
                "ex-luz-2025-11",
                "Avaliação Cardiológica & Eco-Doppler",
                "imaging",
                "echocardiogram",
                "cardiology",
                "Hospital da Luz",
                "2025-11-22",
                "Fração de ejeção preservada (62%). Pacemaker normofuncionante.",
                [],
            ),
            (
                "ex-germano-2025-05",
                "Hemograma e Bioquímica Geral",
                "blood_tests",
                "blood_panel",
                "general_practice",
                "Germano de Sousa",
                "2025-05-14",
                "Glicose: 101 mg/dL; Colesterol LDL: 155 mg/dL; Creatinina: 0.96 mg/dL; Hemoglobina: 14.1 g/dL.",
                [
                    {"parameter": "glucose", "label": "Glicose em Jejum", "value": 101, "unit": "mg/dL", "reference": "70 - 99", "verification": "text_verified"},
                    {"parameter": "ldl", "label": "Colesterol LDL", "value": 155, "unit": "mg/dL", "reference": "< 115", "verification": "text_verified"},
                    {"parameter": "creatinine", "label": "Creatinina Sérica", "value": 0.96, "unit": "mg/dL", "reference": "0.70 - 1.25", "verification": "text_verified"},
                    {"parameter": "hemoglobin", "label": "Hemoglobina", "value": 14.1, "unit": "g/dL", "reference": "13.0 - 17.5", "verification": "text_verified"},
                ],
            ),
        ]

        for eid, title, cat, etype, spec, issuer, edate, summary, vals in seed_exams:
            db.execute(
                """INSERT INTO exams(id, patient_id, title, category, exam_type, specialty, issuer, exam_date, summary, extracted_values, added_by_role, added_by_name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'patient', 'Sr. António Silva', ?, ?)""",
                (eid, patient_id, title, cat, etype, spec, issuer, edate, summary, json.dumps(vals), now, now),
            )

        # Seed manual measurements (Blood Pressure & SpO2)
        seed_meas = [
            ("m-bp-1", "pressure", 136, 84, 72, None, None, "mmHg", "2026-10-20T09:15", "Em repouso antes do pequeno-almoço"),
            ("m-bp-2", "pressure", 132, 80, 70, None, None, "mmHg", "2026-11-02T09:30", "Controlo semanal em casa"),
            ("m-spo2-1", "spo2", None, None, 71, 97.0, None, "%", "2026-11-02T09:32", "Oxímetro de dedo"),
        ]
        for mid, kind, sys_v, dia_v, hr_v, spo2_v, val, unit, mat, notes in seed_meas:
            db.execute(
                """INSERT INTO measurements(id, patient_id, kind, systolic, diastolic, heart_rate, spo2, value, unit, measured_at, notes, added_by_role, added_by_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'patient', 'Sr. António Silva', ?)""",
                (mid, patient_id, kind, sys_v, dia_v, hr_v, spo2_v, val, unit, mat, notes, now),
            )

        # Seed clinical events for timeline chart markers
        seed_events = [
            ("ev-1", "Início de Atorvastatina 20mg", "medication", "2025-12-01", None, "Prescrita após colesterol LDL elevado.", "ex-luz-2025-11"),
            ("ev-2", "Consulta de Rotina USF São João", "consultation", "2026-06-08", None, "Avaliação semestral de glicemia e função renal.", "ex-sns-2026-06"),
        ]
        for evid, title, etype, sdate, edate, notes, exid in seed_events:
            db.execute(
                """INSERT INTO events(id, patient_id, title, event_type, start_date, end_date, notes, exam_id, added_by_role, added_by_name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'patient', 'Sr. António Silva', ?, ?)""",
                (evid, patient_id, title, etype, sdate, edate, notes, exid, now, now),
            )

        db.execute(
            """INSERT INTO audit_log(id, patient_id, actor_role, actor_name, action, details, created_at)
               VALUES (?, ?, 'system', 'Sistema PULSO', 'SEED_DEMO', 'Carteira clínica demonstrativa inicializada.', ?)""",
            (str(uuid.uuid4()), patient_id, now),
        )
