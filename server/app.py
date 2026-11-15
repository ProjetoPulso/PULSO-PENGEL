"""Unified FastAPI application for the PULSO web prototype (HTML + SQLite + Pulso DS extraction)."""
import asyncio
import base64
import json
import os
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Optional

from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response as RawResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .connectors import PT_CONNECTORS
from .db import HASHER, get_db, seed_demo_data
from .hybrid import MAX_UPLOAD, MIMES, extract_document
from .local_ollama import EngineError, LocalOllama

BASE_DIR = Path(__file__).resolve().parent.parent
SERVER_DIR = Path(__file__).resolve().parent
SHARED_DIR = SERVER_DIR / "shared"

SESSION_COOKIE = "pulso_session"
DURATION_MAP = {
    "1h": (3600, "1 Hora"),
    "1d": (86400, "1 Dia"),
    "1m": (2592000, "1 Mês"),
}

# In-memory bounded extraction queue (supports async status polling & cancel)
EXTRACTION_JOBS: dict[str, dict[str, Any]] = {}
EXTRACTION_LOCK = asyncio.Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    seed_demo_data()
    yield


app = FastAPI(title="PULSO — Portal Clínico & Aplicação Utente", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
        "null",
    ],
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _clean_sns(raw: str) -> str:
    digits = re.sub(r"\D+", "", raw or "")
    if len(digits) != 9:
        raise HTTPException(422, "O Nº de Utente SNS deve conter exatamente 9 dígitos.")
    return digits


def _record_audit(db, patient_id: str, role: str, name: str, action: str, details: str = ""):
    db.execute(
        """INSERT INTO audit_log(id, patient_id, actor_role, actor_name, action, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), patient_id, role, name, action, details, time.time()),
    )


def _get_session(request: Request, required: bool = True) -> Optional[dict[str, Any]]:
    token = request.headers.get("x-pulso-session") or request.cookies.get(SESSION_COOKIE)
    if not token:
        if required:
            raise HTTPException(401, "Sessão não iniciada. Por favor, inicie sessão.")
        return None

    with get_db() as db:
        row = db.execute(
            """SELECT s.token, s.user_id, s.role, s.patient_id, s.grant_code, s.expires_at,
                      u.full_name, u.display_name, u.sns_number, u.license_number, u.email, u.birth_date, u.preferences
               FROM sessions s
               JOIN users u ON u.id = s.user_id
               WHERE s.token = ?""",
            (token,),
        ).fetchone()

        if not row or row["expires_at"] <= time.time():
            if required:
                raise HTTPException(401, "Sessão expirada. Inicie sessão novamente.")
            return None

        # If doctor, verify the underlying share code wasn't revoked or expired
        if row["role"] == "doctor" and row["grant_code"]:
            grant = db.execute(
                "SELECT revoked, expires_at FROM share_codes WHERE code = ?",
                (row["grant_code"],),
            ).fetchone()
            if not grant or grant["revoked"] or grant["expires_at"] <= time.time():
                if required:
                    raise HTTPException(401, "O acesso temporário expirou ou foi revogado pelo utente.")
                return None

        patient_row = None
        if row["patient_id"]:
            patient_row = db.execute(
                "SELECT id, sns_number, full_name, display_name, birth_date, email, clinical_alerts, preferences FROM users WHERE id = ?",
                (row["patient_id"],),
            ).fetchone()

        return {
            "token": row["token"],
            "user_id": row["user_id"],
            "role": row["role"],
            "patient_id": row["patient_id"],
            "grant_code": row["grant_code"],
            "expires_at": row["expires_at"],
            "user": {
                "id": row["user_id"],
                "role": row["role"],
                "fullName": row["full_name"],
                "displayName": row["display_name"],
                "snsNumber": row["sns_number"],
                "licenseNumber": row["license_number"],
                "email": row["email"],
                "birthDate": row["birth_date"],
                "preferences": json.loads(row["preferences"] or "{}"),
            },
            "patient": {
                "id": patient_row["id"],
                "snsNumber": patient_row["sns_number"],
                "fullName": patient_row["full_name"],
                "displayName": patient_row["display_name"],
                "birthDate": patient_row["birth_date"],
                "email": patient_row["email"],
                "clinicalAlerts": json.loads(patient_row["clinical_alerts"] or "[]"),
                "preferences": json.loads(patient_row["preferences"] or "{}"),
            }
            if patient_row
            else None,
        }


def _require_patient(sess: dict[str, Any]):
    if sess["role"] != "patient":
        raise HTTPException(403, "Ação reservada apenas ao utente titular da carteira clínica.")


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class RegisterPatientReq(BaseModel):
    snsNumber: str
    fullName: str
    birthDate: str
    password: str
    email: Optional[str] = None


class LoginPatientReq(BaseModel):
    snsNumber: str
    password: str


class LoginDoctorReq(BaseModel):
    licenseNumber: Optional[str] = "48192"
    accessCode: Optional[str] = None
    qrToken: Optional[str] = None


class CreateShareCodeReq(BaseModel):
    durationKey: Literal["1h", "1d", "1m"] = "1h"


class PreferencesReq(BaseModel):
    theme: Optional[Literal["dark", "light"]] = None
    mode: Optional[Literal["simple", "balanced", "detailed"]] = None
    textSize: Optional[Literal["standard", "large", "xlarge"]] = None
    contrast: Optional[Literal["standard", "high"]] = None
    reducedMotion: Optional[bool] = None


class ProfileUpdateReq(BaseModel):
    fullName: Optional[str] = None
    birthDate: Optional[str] = None
    email: Optional[str] = None
    clinicalAlerts: Optional[list[str]] = None
    password: Optional[str] = None


class ExamCreateReq(BaseModel):
    title: str
    category: str = "blood_tests"
    examType: str = "blood_panel"
    specialty: str = "general_practice"
    issuer: str = "Registo Manual"
    examDate: str
    summary: str = ""
    extractedValues: list[dict[str, Any]] = Field(default_factory=list)
    fileBase64: Optional[str] = None
    fileName: Optional[str] = None
    mimeType: Optional[str] = None


class ExamPatchReq(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    examType: Optional[str] = None
    specialty: Optional[str] = None
    issuer: Optional[str] = None
    examDate: Optional[str] = None
    summary: Optional[str] = None


class MeasurementReq(BaseModel):
    kind: Literal["pressure", "spo2", "glucose"] = "pressure"
    systolic: Optional[int] = None
    diastolic: Optional[int] = None
    heartRate: Optional[int] = None
    spo2: Optional[float] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    measuredAt: str
    notes: str = ""


class EventReq(BaseModel):
    title: str
    eventType: Literal["medication", "consultation", "hospitalization", "symptom", "other"] = "consultation"
    startDate: str
    endDate: Optional[str] = None
    notes: str = ""
    examId: Optional[str] = None


# ---------------------------------------------------------------------------
# Auth & RBAC Routes
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "pulso-unified", "version": "1.0.0"}


@app.post("/api/auth/register")
def register_patient(body: RegisterPatientReq, response: Response):
    sns = _clean_sns(body.snsNumber)
    name = body.fullName.strip()
    if len(name) < 2:
        raise HTTPException(422, "Introduz o nome completo do utente.")
    if len(body.password) < 6:
        raise HTTPException(422, "A palavra-passe deve ter pelo menos 6 caracteres.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.birthDate):
        raise HTTPException(422, "Data de nascimento inválida (usa AAAA-MM-DD).")

    user_id = f"pat-{uuid.uuid4().hex[:12]}"
    inbox_slug = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".") or sns
    email = (body.email or "").strip() or f"{inbox_slug}@inbox.pulso.health"
    now = time.time()
    prefs = {"theme": "dark", "mode": "balanced", "textSize": "standard", "contrast": "high", "reducedMotion": False}

    with get_db(write=True) as db:
        existing = db.execute("SELECT id FROM users WHERE sns_number = ?", (sns,)).fetchone()
        if existing:
            raise HTTPException(409, f"Já existe uma conta registada com o Nº de Utente SNS {sns}.")

        db.execute(
            """INSERT INTO users(id, sns_number, license_number, role, full_name, display_name, birth_date, email, password_hash, preferences, clinical_alerts, created_at)
               VALUES (?, ?, NULL, 'patient', ?, ?, ?, ?, ?, ?, '[]', ?)""",
            (user_id, sns, name, name, body.birthDate, email, HASHER.hash(body.password), json.dumps(prefs), now),
        )

        token = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO sessions(token, user_id, role, patient_id, grant_code, expires_at, created_at) VALUES (?, ?, 'patient', ?, NULL, ?, ?)",
            (token, user_id, user_id, now + 8 * 3600, now),
        )
        _record_audit(db, user_id, "patient", name, "REGISTER_SNS", f"Conta criada com SNS {sns}.")

    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=8 * 3600)
    return {"ok": True, "sessionToken": token, "role": "patient", "snsNumber": sns, "displayName": name}


@app.post("/api/auth/login/patient")
def login_patient(body: LoginPatientReq, response: Response):
    sns = _clean_sns(body.snsNumber)
    with get_db(write=True) as db:
        user = db.execute("SELECT * FROM users WHERE sns_number = ? AND role = 'patient'", (sns,)).fetchone()
        if not user:
            raise HTTPException(401, "Nº de Utente SNS não encontrado ou palavra-passe incorreta.")
        try:
            HASHER.verify(user["password_hash"], body.password)
        except (VerificationError, InvalidHashError):
            raise HTTPException(401, "Nº de Utente SNS não encontrado ou palavra-passe incorreta.")

        now = time.time()
        token = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO sessions(token, user_id, role, patient_id, grant_code, expires_at, created_at) VALUES (?, ?, 'patient', ?, NULL, ?, ?)",
            (token, user["id"], user["id"], now + 8 * 3600, now),
        )
        _record_audit(db, user["id"], "patient", user["display_name"], "LOGIN_PATIENT", "Utente iniciou sessão.")

    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=8 * 3600)
    return {"ok": True, "sessionToken": token, "role": "patient", "snsNumber": sns, "displayName": user["display_name"]}


@app.post("/api/auth/login/doctor")
def login_doctor(body: LoginDoctorReq, response: Response):
    license_num = re.sub(r"\s+", "", body.licenseNumber or "48192")
    raw_code = re.sub(r"\s+", "", body.accessCode or "")

    with get_db(write=True) as db:
        doc = db.execute("SELECT * FROM users WHERE license_number = ? AND role = 'doctor'", (license_num,)).fetchone()
        if not doc:
            doc = db.execute("SELECT * FROM users WHERE role = 'doctor' LIMIT 1").fetchone()
        if not doc:
            raise HTTPException(401, "Cédula profissional não reconhecida.")

        now = time.time()
        grant = None

        if body.qrToken:
            # Support QR scan format e.g. PULSO:UTENTE:234891024:ANTONIO_SILVA
            m = re.search(r"(\d{9})", body.qrToken)
            if not m:
                raise HTTPException(400, "QR Code de utente inválido.")
            sns = m.group(1)
            pat = db.execute("SELECT id, display_name FROM users WHERE sns_number = ?", (sns,)).fetchone()
            if not pat:
                raise HTTPException(404, f"Utente com SNS {sns} não encontrado.")
            grant = db.execute(
                "SELECT * FROM share_codes WHERE patient_id = ? AND revoked = 0 AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
                (pat["id"], now),
            ).fetchone()
            if not grant:
                # Create an automatic 1h consultation grant via physical QR verification
                code = f"{secrets.randbelow(90000000) + 10000000}"
                db.execute(
                    "INSERT INTO share_codes(code, patient_id, duration_key, duration_label, created_at, expires_at, revoked) VALUES (?, ?, '1h', '1 Hora (QR)', ?, ?, 0)",
                    (code, pat["id"], now, now + 3600),
                )
                grant = db.execute("SELECT * FROM share_codes WHERE code = ?", (code,)).fetchone()
        else:
            if len(raw_code) != 8 or not raw_code.isdigit():
                raise HTTPException(422, "Introduz o código completo de 8 dígitos facultado pelo utente.")
            grant = db.execute("SELECT * FROM share_codes WHERE code = ?", (raw_code,)).fetchone()
            if not grant or grant["revoked"] or grant["expires_at"] <= now:
                raise HTTPException(401, "Código incorreto, expirado ou revogado pelo utente.")

        token = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO sessions(token, user_id, role, patient_id, grant_code, expires_at, created_at) VALUES (?, ?, 'doctor', ?, ?, ?, ?)",
            (token, doc["id"], grant["patient_id"], grant["code"], grant["expires_at"], now),
        )
        _record_audit(
            db,
            grant["patient_id"],
            "doctor",
            doc["display_name"],
            "DOCTOR_ACCESS_GRANTED",
            f"Acesso clínico desbloqueado ({grant['duration_label']}) via código {grant['code']}.",
        )

    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=int(max(60, grant["expires_at"] - now)))
    return {
        "ok": True,
        "sessionToken": token,
        "role": "doctor",
        "grantCode": grant["code"],
        "durationLabel": grant["duration_label"],
        "expiresAt": grant["expires_at"],
        "remainingSeconds": int(max(0, grant["expires_at"] - now)),
    }


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.headers.get("x-pulso-session") or request.cookies.get(SESSION_COOKIE)
    if token:
        with get_db(write=True) as db:
            db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    sess = _get_session(request, required=False)
    if not sess:
        return {"authenticated": False}
    is_patient = sess["role"] == "patient"
    return {
        "authenticated": True,
        "role": sess["role"],
        "user": sess["user"],
        "patient": sess["patient"],
        "grantCode": sess["grant_code"],
        "expiresAt": sess["expires_at"],
        "remainingSeconds": int(max(0, sess["expires_at"] - time.time())),
        "permissions": {
            "canGenerateShareCode": is_patient,
            "canRevokeShareCode": is_patient,
            "canDeleteRecords": is_patient,
            "canEditPreferences": is_patient,
            "canAddRecords": True,
            "canViewRecords": True,
        },
    }


@app.patch("/api/auth/preferences")
def update_preferences(body: PreferencesReq, request: Request):
    sess = _get_session(request)
    _require_patient(sess)
    prefs = dict(sess["user"]["preferences"])
    if body.theme is not None:
        prefs["theme"] = body.theme
    if body.mode is not None:
        prefs["mode"] = body.mode
    if body.textSize is not None:
        prefs["textSize"] = body.textSize
    if body.contrast is not None:
        prefs["contrast"] = body.contrast
    if body.reducedMotion is not None:
        prefs["reducedMotion"] = body.reducedMotion
    with get_db(write=True) as db:
        db.execute("UPDATE users SET preferences = ? WHERE id = ?", (json.dumps(prefs), sess["user_id"]))
    return {"ok": True, "preferences": prefs}


@app.patch("/api/auth/profile")
def update_profile(body: ProfileUpdateReq, request: Request):
    sess = _get_session(request)
    is_patient = sess["role"] == "patient"
    updates = []
    params: list[Any] = []

    if body.fullName is not None:
        name = body.fullName.strip()
        if len(name) < 2:
            raise HTTPException(422, "O nome completo deve ter pelo menos 2 caracteres.")
        updates.extend(["full_name = ?", "display_name = ?"])
        params.extend([name, name])

    if body.email is not None:
        updates.append("email = ?")
        params.append(body.email.strip())

    if body.birthDate is not None:
        if not is_patient:
            raise HTTPException(403, "Apenas o utente pode alterar a sua data de nascimento.")
        if body.birthDate and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.birthDate):
            raise HTTPException(422, "Data de nascimento inválida (usa AAAA-MM-DD).")
        updates.append("birth_date = ?")
        params.append(body.birthDate)

    if body.clinicalAlerts is not None:
        if not is_patient:
            raise HTTPException(403, "Apenas o utente pode editar os seus alertas clínicos.")
        cleaned_alerts = [a.strip() for a in body.clinicalAlerts if a and a.strip()]
        updates.append("clinical_alerts = ?")
        params.append(json.dumps(cleaned_alerts, ensure_ascii=False))

    if body.password is not None and body.password != "":
        if len(body.password) < 6:
            raise HTTPException(422, "A nova palavra-passe deve ter pelo menos 6 caracteres.")
        updates.append("password_hash = ?")
        params.append(HASHER.hash(body.password))

    if not updates:
        return {"ok": True, "user": sess["user"]}

    params.append(sess["user_id"])
    with get_db(write=True) as db:
        db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(params))
        if sess["patient_id"]:
            _record_audit(db, sess["patient_id"], sess["role"], sess["user"]["displayName"], "PROFILE_UPDATED", "Dados do perfil atualizados.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Share Codes (8-Digit Patient -> Doctor Authorization)
# ---------------------------------------------------------------------------


@app.post("/api/share-codes")
def create_share_code(body: CreateShareCodeReq, request: Request):
    sess = _get_session(request)
    _require_patient(sess)
    seconds, label = DURATION_MAP[body.durationKey]
    now = time.time()
    code = f"{secrets.randbelow(90000000) + 10000000}"

    with get_db(write=True) as db:
        # Revoke prior active codes from this patient so only latest is active
        db.execute("UPDATE share_codes SET revoked = 1 WHERE patient_id = ? AND revoked = 0", (sess["patient_id"],))
        db.execute(
            """INSERT INTO share_codes(code, patient_id, duration_key, duration_label, created_at, expires_at, revoked)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (code, sess["patient_id"], body.durationKey, label, now, now + seconds),
        )
        _record_audit(db, sess["patient_id"], "patient", sess["user"]["displayName"], "SHARE_CODE_CREATED", f"Código {code} ({label}).")

    return {
        "code": code,
        "formattedCode": f"{code[:4]} {code[4:]}",
        "durationKey": body.durationKey,
        "durationLabel": label,
        "expiresInSeconds": seconds,
        "expiresAt": now + seconds,
    }


@app.get("/api/share-codes/active")
def active_share_code(request: Request):
    sess = _get_session(request)
    _require_patient(sess)
    now = time.time()
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM share_codes WHERE patient_id = ? AND revoked = 0 AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
            (sess["patient_id"], now),
        ).fetchone()
    if not row:
        return {"active": False}
    code = row["code"]
    return {
        "active": True,
        "code": code,
        "formattedCode": f"{code[:4]} {code[4:]}",
        "durationKey": row["duration_key"],
        "durationLabel": row["duration_label"],
        "expiresInSeconds": int(row["expires_at"] - now),
        "expiresAt": row["expires_at"],
    }


@app.delete("/api/share-codes/{code}")
def revoke_share_code(code: str, request: Request):
    sess = _get_session(request)
    _require_patient(sess)
    clean_code = re.sub(r"\s+", "", code)
    with get_db(write=True) as db:
        db.execute("UPDATE share_codes SET revoked = 1 WHERE code = ? AND patient_id = ?", (clean_code, sess["patient_id"]))
        _record_audit(db, sess["patient_id"], "patient", sess["user"]["displayName"], "SHARE_CODE_REVOKED", f"Código {clean_code} revogado.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Clinical Records (Exams, Measurements, Events, Audit)
# ---------------------------------------------------------------------------


@app.get("/api/records")
def list_records(request: Request):
    sess = _get_session(request)
    pid = sess["patient_id"]
    with get_db() as db:
        exams_rows = db.execute(
            """SELECT id, title, category, exam_type, specialty, issuer, exam_date, summary, extracted_values,
                      file_name, mime_type, (file_blob IS NOT NULL) AS has_file, added_by_role, added_by_name, created_at
               FROM exams WHERE patient_id = ? ORDER BY exam_date DESC, created_at DESC""",
            (pid,),
        ).fetchall()
        meas_rows = db.execute(
            "SELECT * FROM measurements WHERE patient_id = ? ORDER BY measured_at DESC, created_at DESC",
            (pid,),
        ).fetchall()
        ev_rows = db.execute(
            "SELECT * FROM events WHERE patient_id = ? ORDER BY start_date DESC, created_at DESC",
            (pid,),
        ).fetchall()
        audit_rows = db.execute(
            "SELECT * FROM audit_log WHERE patient_id = ? ORDER BY created_at DESC LIMIT 30",
            (pid,),
        ).fetchall()

    exams = [
        {
            "id": r["id"],
            "title": r["title"],
            "category": r["category"],
            "examType": r["exam_type"],
            "specialty": r["specialty"],
            "issuer": r["issuer"],
            "examDate": r["exam_date"],
            "summary": r["summary"],
            "extractedValues": json.loads(r["extracted_values"] or "[]"),
            "fileName": r["file_name"],
            "mimeType": r["mime_type"],
            "hasFile": bool(r["has_file"]),
            "addedByRole": r["added_by_role"],
            "addedByName": r["added_by_name"],
        }
        for r in exams_rows
    ]
    measurements = [
        {
            "id": r["id"],
            "kind": r["kind"],
            "systolic": r["systolic"],
            "diastolic": r["diastolic"],
            "heartRate": r["heart_rate"],
            "spo2": r["spo2"],
            "value": r["value"],
            "unit": r["unit"],
            "measuredAt": r["measured_at"],
            "notes": r["notes"],
            "addedByRole": r["added_by_role"],
            "addedByName": r["added_by_name"],
        }
        for r in meas_rows
    ]
    events = [
        {
            "id": r["id"],
            "title": r["title"],
            "eventType": r["event_type"],
            "startDate": r["start_date"],
            "endDate": r["end_date"],
            "notes": r["notes"],
            "examId": r["exam_id"],
            "addedByRole": r["added_by_role"],
            "addedByName": r["added_by_name"],
        }
        for r in ev_rows
    ]
    audit = [
        {
            "id": r["id"],
            "actorRole": r["actor_role"],
            "actorName": r["actor_name"],
            "action": r["action"],
            "details": r["details"],
            "createdAt": r["created_at"],
        }
        for r in audit_rows
    ]
    return {"exams": exams, "measurements": measurements, "events": events, "audit": audit}


@app.post("/api/exams")
def create_exam(body: ExamCreateReq, request: Request):
    sess = _get_session(request)
    eid = f"ex-{uuid.uuid4().hex[:10]}"
    now = time.time()
    blob = None
    if body.fileBase64:
        try:
            raw_b64 = body.fileBase64.split(",")[-1]
            blob = base64.b64decode(raw_b64)
            if len(blob) > MAX_UPLOAD:
                raise HTTPException(413, "Ficheiro excede o limite de 2 MB.")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "Conteúdo de ficheiro inválido.")

    with get_db(write=True) as db:
        db.execute(
            """INSERT INTO exams(id, patient_id, title, category, exam_type, specialty, issuer, exam_date, summary, extracted_values, file_name, mime_type, file_blob, added_by_role, added_by_name, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eid,
                sess["patient_id"],
                body.title.strip(),
                body.category,
                body.examType,
                body.specialty,
                body.issuer.strip(),
                body.examDate,
                body.summary.strip(),
                json.dumps(body.extractedValues),
                body.fileName,
                body.mimeType,
                blob,
                sess["role"],
                sess["user"]["displayName"],
                now,
                now,
            ),
        )
        _record_audit(db, sess["patient_id"], sess["role"], sess["user"]["displayName"], "EXAM_ADDED", f"Exame: {body.title}")
    return {"ok": True, "id": eid}


@app.patch("/api/exams/{exam_id}")
def update_exam(exam_id: str, body: ExamPatchReq, request: Request):
    sess = _get_session(request)
    with get_db(write=True) as db:
        existing = db.execute("SELECT * FROM exams WHERE id = ? AND patient_id = ?", (exam_id, sess["patient_id"])).fetchone()
        if not existing:
            raise HTTPException(404, "Exame não encontrado.")
        db.execute(
            """UPDATE exams SET title=?, category=?, exam_type=?, specialty=?, issuer=?, exam_date=?, summary=?, updated_at=?
               WHERE id=? AND patient_id=?""",
            (
                body.title if body.title is not None else existing["title"],
                body.category if body.category is not None else existing["category"],
                body.examType if body.examType is not None else existing["exam_type"],
                body.specialty if body.specialty is not None else existing["specialty"],
                body.issuer if body.issuer is not None else existing["issuer"],
                body.examDate if body.examDate is not None else existing["exam_date"],
                body.summary if body.summary is not None else existing["summary"],
                time.time(),
                exam_id,
                sess["patient_id"],
            ),
        )
        _record_audit(db, sess["patient_id"], sess["role"], sess["user"]["displayName"], "EXAM_UPDATED", f"Exame {exam_id} atualizado.")
    return {"ok": True}


@app.delete("/api/exams/{exam_id}")
def delete_exam(exam_id: str, request: Request):
    sess = _get_session(request)
    _require_patient(sess)
    with get_db(write=True) as db:
        cur = db.execute("DELETE FROM exams WHERE id = ? AND patient_id = ?", (exam_id, sess["patient_id"]))
        if cur.rowcount == 0:
            raise HTTPException(404, "Exame não encontrado.")
        _record_audit(db, sess["patient_id"], "patient", sess["user"]["displayName"], "EXAM_DELETED", f"Exame {exam_id} eliminado.")
    return {"ok": True}


@app.get("/api/exams/{exam_id}/file")
def preview_exam_file(exam_id: str, request: Request):
    sess = _get_session(request)
    with get_db() as db:
        row = db.execute(
            "SELECT file_blob, mime_type, file_name FROM exams WHERE id = ? AND patient_id = ?",
            (exam_id, sess["patient_id"]),
        ).fetchone()
    if not row or not row["file_blob"]:
        raise HTTPException(404, "Ficheiro original não anexado.")
    return RawResponse(
        content=row["file_blob"],
        media_type=row["mime_type"] or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{row["file_name"] or "documento"}"'},
    )


class ConnectorConnectReq(BaseModel):
    connected: bool = True


class ConnectorCredsReq(BaseModel):
    apiKey: str = ""
    clientId: str = ""
    endpointUrl: str = ""


class CustomConnectorReq(BaseModel):
    name: str
    group: str = "Laboratório Clínico"
    protocol: str = "HL7 FHIR R4 / API Key"
    endpointUrl: str = ""
    apiKey: str = ""
    clientId: str = ""
    description: str = "Ligação API personalizada configurada pelo utente."


class EmergencyTriggerReq(BaseModel):
    mode: str = "manual_hold_2s"
    onWrist: bool = True
    gps: Optional[str] = "41.1780° N, 8.6080° W (Porto)"
    neighborsNotified: int = 3
    notes: str = ""


def _ensure_connector_table(db) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS connector_links (
               patient_id TEXT NOT NULL,
               provider TEXT NOT NULL,
               connected INTEGER NOT NULL DEFAULT 0,
               last_sync REAL,
               api_key TEXT DEFAULT '',
               client_id TEXT DEFAULT '',
               endpoint_url TEXT DEFAULT '',
               PRIMARY KEY (patient_id, provider)
           )"""
    )
    # Migrar colunas caso tabela já exista de execução anterior
    cols = {r[1] for r in db.execute("PRAGMA table_info(connector_links)").fetchall()}
    for col in ("api_key", "client_id", "endpoint_url"):
        if col not in cols:
            db.execute(f"ALTER TABLE connector_links ADD COLUMN {col} TEXT DEFAULT ''")
    db.execute(
        """CREATE TABLE IF NOT EXISTS custom_connectors (
               id TEXT NOT NULL,
               patient_id TEXT NOT NULL,
               name TEXT NOT NULL,
               grp TEXT NOT NULL,
               protocol TEXT NOT NULL,
               description TEXT NOT NULL,
               endpoint_url TEXT DEFAULT '',
               created_at REAL NOT NULL,
               PRIMARY KEY (patient_id, id)
           )"""
    )


def _mask_key(val: str) -> str:
    v = (val or "").strip()
    if not v:
        return ""
    if len(v) <= 4:
        return "••••"
    return "•" * min(12, len(v) - 4) + v[-4:]


def _all_connectors_for_patient(db, patient_id: str) -> list[dict[str, Any]]:
    custom_rows = db.execute(
        "SELECT id, name, grp, protocol, description, endpoint_url FROM custom_connectors WHERE patient_id = ? ORDER BY created_at DESC",
        (patient_id,),
    ).fetchall()
    customs = [
        {
            "id": r["id"],
            "name": r["name"],
            "group": r["grp"],
            "protocol": r["protocol"],
            "description": r["description"],
            "endpointUrl": r["endpoint_url"] or "",
            "custom": True,
            "sampleExam": {
                "externalId": f"{r['id']}-2026-01",
                "title": f"Registo Clínico Sincronizado — {r['name']}",
                "category": "blood_tests",
                "examType": "Importação API",
                "specialty": "Clínica Geral",
                "issuer": r["name"],
                "examDate": time.strftime("%Y-%m-%d"),
                "summary": f"Sincronizado automaticamente via {r['protocol']}.",
                "extractedValues": [
                    {"name": "Estado da Ligação", "value": 100, "unit": "%", "referenceRange": "OK"}
                ],
            },
        }
        for r in custom_rows
    ]
    return [*PT_CONNECTORS, *customs]


def _find_connector(provider: str, db=None, patient_id: Optional[str] = None) -> dict[str, Any]:
    for c in PT_CONNECTORS:
        if c["id"] == provider:
            return c
    if db is not None and patient_id is not None:
        for c in _all_connectors_for_patient(db, patient_id):
            if c["id"] == provider:
                return c
    raise HTTPException(404, "Conector de saúde desconhecido.")


@app.get("/api/connectors")
def list_connectors(request: Request):
    sess = _get_session(request)
    with get_db(write=True) as db:
        _ensure_connector_table(db)
        rows = db.execute(
            "SELECT provider, connected, last_sync, api_key, client_id, endpoint_url FROM connector_links WHERE patient_id = ?",
            (sess["patient_id"],),
        ).fetchall()
        all_conns = _all_connectors_for_patient(db, sess["patient_id"])
    state_map = {
        r["provider"]: {
            "connected": bool(r["connected"]),
            "lastSync": r["last_sync"],
            "hasApiKey": bool((r["api_key"] or "").strip()),
            "apiKeyMasked": _mask_key(r["api_key"] or ""),
            "clientId": r["client_id"] or "",
            "endpointUrl": r["endpoint_url"] or "",
        }
        for r in rows
    }
    items = []
    for c in all_conns:
        st = state_map.get(
            c["id"],
            {
                "connected": c["id"] == "sns24",
                "lastSync": None,
                "hasApiKey": False,
                "apiKeyMasked": "",
                "clientId": "",
                "endpointUrl": c.get("endpointUrl", ""),
            },
        )
        items.append({**c, **st})
    return {"connectors": items}


@app.post("/api/connectors")
def create_custom_connector(body: CustomConnectorReq, request: Request):
    sess = _get_session(request)
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(400, "Indique o nome da entidade ou API.")
    cid = "custom-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20] + "-" + uuid.uuid4().hex[:4]
    now = time.time()
    with get_db(write=True) as db:
        _ensure_connector_table(db)
        db.execute(
            """INSERT INTO custom_connectors(id, patient_id, name, grp, protocol, description, endpoint_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (cid, sess["patient_id"], name, body.group.strip() or "Clínica / Outro", body.protocol.strip() or "HL7 FHIR R4 / API Key", body.description.strip(), body.endpointUrl.strip(), now),
        )
        db.execute(
            """INSERT INTO connector_links(patient_id, provider, connected, last_sync, api_key, client_id, endpoint_url)
               VALUES (?, ?, ?, NULL, ?, ?, ?)""",
            (sess["patient_id"], cid, 1 if body.apiKey.strip() else 0, body.apiKey.strip(), body.clientId.strip(), body.endpointUrl.strip()),
        )
        _record_audit(
            db,
            sess["patient_id"],
            sess["role"],
            sess["user"]["displayName"],
            "CONNECTOR_CREATED",
            f"Nova ligação API configurada: {name} ({body.protocol}).",
        )
    return {"ok": True, "id": cid, "name": name}


@app.post("/api/connectors/{provider}/credentials")
def save_connector_credentials(provider: str, body: ConnectorCredsReq, request: Request):
    sess = _get_session(request)
    with get_db(write=True) as db:
        _ensure_connector_table(db)
        conn = _find_connector(provider, db, sess["patient_id"])
        db.execute(
            """INSERT INTO connector_links(patient_id, provider, connected, last_sync, api_key, client_id, endpoint_url)
               VALUES (?, ?, 1, NULL, ?, ?, ?)
               ON CONFLICT(patient_id, provider) DO UPDATE SET
                 api_key = excluded.api_key,
                 client_id = excluded.client_id,
                 endpoint_url = excluded.endpoint_url,
                 connected = 1""",
            (sess["patient_id"], provider, body.apiKey.strip(), body.clientId.strip(), body.endpointUrl.strip()),
        )
        _record_audit(
            db,
            sess["patient_id"],
            sess["role"],
            sess["user"]["displayName"],
            "CONNECTOR_KEY_SAVED",
            f"API Key / credenciais guardadas para {conn['name']}.",
        )
    return {"ok": True, "provider": provider, "hasApiKey": bool(body.apiKey.strip()), "apiKeyMasked": _mask_key(body.apiKey)}


@app.post("/api/connectors/{provider}/connect")
def toggle_connector(provider: str, body: ConnectorConnectReq, request: Request):
    sess = _get_session(request)
    with get_db(write=True) as db:
        _ensure_connector_table(db)
        conn = _find_connector(provider, db, sess["patient_id"])
        db.execute(
            """INSERT INTO connector_links(patient_id, provider, connected, last_sync)
               VALUES (?, ?, ?, NULL)
               ON CONFLICT(patient_id, provider) DO UPDATE SET connected = excluded.connected""",
            (sess["patient_id"], provider, 1 if body.connected else 0),
        )
        action = "CONNECTOR_LINKED" if body.connected else "CONNECTOR_UNLINKED"
        _record_audit(
            db,
            sess["patient_id"],
            sess["role"],
            sess["user"]["displayName"],
            action,
            f"Conector {conn['name']} ({conn['protocol']}) {'associado' if body.connected else 'desligado'}.",
        )
    return {"ok": True, "provider": provider, "connected": body.connected}


@app.post("/api/connectors/{provider}/sync")
def sync_connector(provider: str, request: Request):
    sess = _get_session(request)
    now = time.time()
    imported = 0
    with get_db(write=True) as db:
        _ensure_connector_table(db)
        conn = _find_connector(provider, db, sess["patient_id"])
        sample = conn["sampleExam"]
        exam_id = f"conn-{sess['patient_id']}-{sample['externalId']}"
        db.execute(
            """INSERT INTO connector_links(patient_id, provider, connected, last_sync)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(patient_id, provider) DO UPDATE SET connected = 1, last_sync = excluded.last_sync""",
            (sess["patient_id"], provider, now),
        )
        existing = db.execute("SELECT id FROM exams WHERE id = ?", (exam_id,)).fetchone()
        if not existing:
            db.execute(
                """INSERT INTO exams(id, patient_id, title, category, exam_type, specialty, issuer, exam_date, summary, extracted_values, file_name, mime_type, file_blob, added_by_role, added_by_name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    exam_id,
                    sess["patient_id"],
                    sample["title"],
                    sample["category"],
                    sample["examType"],
                    sample["specialty"],
                    sample["issuer"],
                    sample["examDate"],
                    sample["summary"],
                    json.dumps(sample["extractedValues"]),
                    None,
                    None,
                    None,
                    sess["role"],
                    f"API {conn['name']}",
                    now,
                    now,
                ),
            )
            imported = 1
        _record_audit(
            db,
            sess["patient_id"],
            sess["role"],
            sess["user"]["displayName"],
            "CONNECTOR_SYNC",
            f"Sincronização {conn['name']} ({conn['protocol']}): {imported} novo(s) registo(s).",
        )
    return {"ok": True, "provider": provider, "imported": imported, "examId": exam_id, "lastSync": now}


@app.post("/api/emergency/trigger")
def trigger_emergency(body: EmergencyTriggerReq, request: Request):
    sess = _get_session(request)
    evid = f"emg-{uuid.uuid4().hex[:10]}"
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    title = f"ALERTA SOS ({body.mode}) · 112 & {body.neighborsNotified} Socorristas da Comunidade"
    details = (
        f"Pulso={body.onWrist} · GPS={body.gps or 'N/D'} · "
        f"Socorristas da Comunidade={body.neighborsNotified} · {body.notes.strip() or 'Acionamento de emergência médica'}"
    )
    with get_db(write=True) as db:
        db.execute(
            """INSERT INTO events(id, patient_id, title, event_type, start_date, end_date, notes, exam_id, added_by_role, added_by_name, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                evid,
                sess["patient_id"],
                title,
                "urgent",
                today,
                None,
                details,
                None,
                sess["role"],
                sess["user"]["displayName"],
                now,
                now,
            ),
        )
        _record_audit(
            db,
            sess["patient_id"],
            sess["role"],
            sess["user"]["displayName"],
            "EMERGENCY_SOS_TRIGGERED",
            details,
        )
    return {"ok": True, "id": evid, "gps": body.gps, "neighborsNotified": body.neighborsNotified, "timestamp": now}


@app.post("/api/measurements")
def create_measurement(body: MeasurementReq, request: Request):
    sess = _get_session(request)
    mid = f"meas-{uuid.uuid4().hex[:10]}"
    now = time.time()
    unit = body.unit or ("mmHg" if body.kind == "pressure" else "%" if body.kind == "spo2" else "mg/dL")

    with get_db(write=True) as db:
        db.execute(
            """INSERT INTO measurements(id, patient_id, kind, systolic, diastolic, heart_rate, spo2, value, unit, measured_at, notes, added_by_role, added_by_name, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mid,
                sess["patient_id"],
                body.kind,
                body.systolic,
                body.diastolic,
                body.heartRate,
                body.spo2,
                body.value,
                unit,
                body.measuredAt,
                body.notes.strip(),
                sess["role"],
                sess["user"]["displayName"],
                now,
            ),
        )
        _record_audit(db, sess["patient_id"], sess["role"], sess["user"]["displayName"], "MEASUREMENT_ADDED", f"Medição {body.kind} em {body.measuredAt}.")
    return {"ok": True, "id": mid}


@app.delete("/api/measurements/{meas_id}")
def delete_measurement(meas_id: str, request: Request):
    sess = _get_session(request)
    _require_patient(sess)
    with get_db(write=True) as db:
        cur = db.execute("DELETE FROM measurements WHERE id = ? AND patient_id = ?", (meas_id, sess["patient_id"]))
        if cur.rowcount == 0:
            raise HTTPException(404, "Medição não encontrada.")
    return {"ok": True}


@app.post("/api/events")
def create_event(body: EventReq, request: Request):
    sess = _get_session(request)
    evid = f"ev-{uuid.uuid4().hex[:10]}"
    now = time.time()
    with get_db(write=True) as db:
        db.execute(
            """INSERT INTO events(id, patient_id, title, event_type, start_date, end_date, notes, exam_id, added_by_role, added_by_name, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                evid,
                sess["patient_id"],
                body.title.strip(),
                body.eventType,
                body.startDate,
                body.endDate,
                body.notes.strip(),
                body.examId,
                sess["role"],
                sess["user"]["displayName"],
                now,
                now,
            ),
        )
        _record_audit(db, sess["patient_id"], sess["role"], sess["user"]["displayName"], "EVENT_ADDED", f"Acontecimento: {body.title}")
    return {"ok": True, "id": evid}


@app.delete("/api/events/{event_id}")
def delete_event(event_id: str, request: Request):
    sess = _get_session(request)
    _require_patient(sess)
    with get_db(write=True) as db:
        cur = db.execute("DELETE FROM events WHERE id = ? AND patient_id = ?", (event_id, sess["patient_id"]))
        if cur.rowcount == 0:
            raise HTTPException(404, "Acontecimento não encontrado.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Document Extraction (PDF / PNG / JPEG -> Deterministic Parser + Ollama)
# ---------------------------------------------------------------------------


@app.get("/api/extractions/status")
def extraction_status():
    try:
        return LocalOllama().status()
    except EngineError:
        return {"available": False, "enabled": False, "model": "qwen3-vl:4b", "reason": "not_configured"}


@app.get("/api/extractions/sample.pdf")
def sample_pdf():
    return FileResponse(SHARED_DIR / "laboratorio-demo.pdf", media_type="application/pdf", filename="laboratorio-demo.pdf")


@app.post("/api/extractions")
async def run_extraction(request: Request, file: UploadFile = File(...)):
    sess = _get_session(request)
    mime = (file.content_type or "").lower()
    if mime not in MIMES:
        raise HTTPException(400, "Formato não suportado. Envia um ficheiro PDF, PNG ou JPEG.")
    payload = await file.read()
    if len(payload) > MAX_UPLOAD:
        raise HTTPException(413, "O ficheiro excede o limite de 2 MB.")
    if EXTRACTION_LOCK.locked():
        raise HTTPException(429, "Já existe uma extração em curso. Aguarda um momento.")

    job_id = f"job-{uuid.uuid4().hex[:10]}"
    async with EXTRACTION_LOCK:
        result = await asyncio.to_thread(extract_document, payload, mime)

    b64 = base64.b64encode(payload).decode("ascii")
    EXTRACTION_JOBS[job_id] = {
        "jobId": job_id,
        "patientId": sess["patient_id"],
        "fileName": file.filename or f"documento.{MIMES[mime]}",
        "mimeType": mime,
        "fileBase64": b64,
        "result": result,
    }
    return {
        "jobId": job_id,
        "fileName": EXTRACTION_JOBS[job_id]["fileName"],
        "mimeType": mime,
        "fileBase64": b64,
        "extraction": result,
    }


@app.get("/api/catalogs")
def get_catalogs():
    reg = json.loads((SHARED_DIR / "registration.json").read_text(encoding="utf-8"))
    lab = json.loads((SHARED_DIR / "laboratory.json").read_text(encoding="utf-8"))
    learn = json.loads((SHARED_DIR / "learning.json").read_text(encoding="utf-8"))
    return {"registration": reg, "laboratory": lab, "learning": learn}


# Serve Fotos & static prototype HTMLs cleanly at /
if (BASE_DIR / "Fotos").exists():
    app.mount("/Fotos", StaticFiles(directory=str(BASE_DIR / "Fotos")), name="fotos")


@app.get("/")
def serve_root():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/{filename}")
def serve_html_or_asset(filename: str):
    allowed_exact = {
        "index.html",
        "mobile.html",
        "demo_aula.html",
        "pulso_app.js",
        "qr_utente_antonio.png",
        "qr_utente_antonio.svg",
    }
    if filename in allowed_exact and (BASE_DIR / filename).exists():
        return FileResponse(BASE_DIR / filename)
    raise HTTPException(404, "Recurso não encontrado.")
