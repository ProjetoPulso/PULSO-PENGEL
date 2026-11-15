/* PULSO — Unified Web Client (API SQLite + Fallback Estático para GitHub Pages) */
(function () {
  const SESSION_KEY = "pulso_api_session_token";
  const STATIC_STORE_KEY = "pulso_static_store_v1";

  function getToken() {
    return sessionStorage.getItem(SESSION_KEY) || "";
  }
  function setToken(t) {
    if (t) sessionStorage.setItem(SESSION_KEY, t);
    else sessionStorage.removeItem(SESSION_KEY);
  }

  const isLocalHost =
    window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost";
  const API_BASE =
    window.location.protocol === "file:" || (isLocalHost && window.location.port && window.location.port !== "8000")
      ? "http://127.0.0.1:8000"
      : "";

  // -------------------------------------------------------------------------
  // Fallback Estático (GitHub Pages / file:// sem servidor Python ativo)
  // -------------------------------------------------------------------------
  function getStaticStore() {
    try {
      const raw = localStorage.getItem(STATIC_STORE_KEY);
      if (raw) return JSON.parse(raw);
    } catch (_) {}
    const initial = {
      patients: [
        {
          id: "pat-antonio",
          snsNumber: "234891024",
          fullName: "Sr. António Silva",
          displayName: "Sr. António Silva",
          birthDate: "1958-04-12",
          email: "antonio.silva@inbox.pulso.health",
          password: "pulso1234",
          clinicalAlerts: [
            "Alergia Grave a Iodo / Contraste Radiológico",
            "Pacemaker Cardíaco (Implantado 2022)",
            "Varfarina 5mg (Anticoagulante - Risco Hemorragia)"
          ],
          preferences: { theme: "dark", mode: "balanced", textSize: "standard", contrast: "high", reducedMotion: false },
          exams: [
            { id: "ex-1", title: "Análises ao sangue", category: "blood_tests", source: "SNS", institution: "USF São João", issuer: "USF São João", examDate: "2026-11-04", intakeChannel: "Email IA", sha256: "8f3c2e19a4b7d012", biomarkers: [{ name: "Glicose", value: 94, unit: "mg/dL" }, { name: "Creatinina", value: 0.98, unit: "mg/dL" }, { name: "eGFR", value: 82, unit: "mL/min" }] },
            { id: "ex-2", title: "Hemograma Completo", category: "blood_tests", source: "Privado", institution: "Unilabs Portugal", issuer: "Unilabs Portugal", examDate: "2026-10-10", intakeChannel: "Foto OCR", sha256: "4a1d9b72c3f8091a", biomarkers: [{ name: "Hemoglobina", value: 14.2, unit: "g/dL" }, { name: "Leucócitos", value: 6.8, unit: "x10³/µL" }, { name: "Plaquetas", value: 215, unit: "x10³/µL" }] },
            { id: "ex-3", title: "Creatinina & Função Renal", category: "blood_tests", source: "Privado", institution: "Hospital da Luz", issuer: "Hospital da Luz", examDate: "2026-06-18", intakeChannel: "Email IA", sha256: "7b2e4410f9a21d55", biomarkers: [{ name: "Creatinina", value: 0.98, unit: "mg/dL" }, { name: "Colesterol Total", value: 182, unit: "mg/dL" }] },
            { id: "ex-4", title: "Eco-Doppler Cardíaco", category: "cardiology", source: "Privado", institution: "Hospital da Luz", issuer: "Hospital da Luz", examDate: "2025-11-20", intakeChannel: "PDF Upload", sha256: "9c8d1123e4f50077", biomarkers: [{ name: "FEVE", value: 62, unit: "%" }] },
            { id: "ex-5", title: "Análises de Rotina SNS", category: "blood_tests", source: "SNS", institution: "USF São João", issuer: "USF São João", examDate: "2025-05-22", intakeChannel: "Foto OCR", sha256: "3e5a7781b2c94410", biomarkers: [{ name: "HbA1c", value: 5.9, unit: "%" }] }
          ],
          measurements: [
            { id: "m-1", kind: "pressure", systolic: 124, diastolic: 78, heartRate: 72, measuredAt: "2026-11-14T09:15", notes: "Em repouso matinal" },
            { id: "m-2", kind: "spo2", spo2: 98, measuredAt: "2026-11-14T09:16", notes: "Oximetria de controlo" }
          ],
          events: [
            { id: "ev-1", title: "Ajuste Metformina 850mg", eventType: "medication", startDate: "2026-10-15", notes: "Boa tolerância" }
          ],
          auditLogs: [
            { action: "SESSION_SEEDED", actorRole: "system", actorName: "PULSO", details: "Carteira clínica inicial carregada.", createdAt: Math.floor(Date.now() / 1000) }
          ]
        }
      ]
    };
    saveStaticStore(initial);
    return initial;
  }

  function saveStaticStore(store) {
    try { localStorage.setItem(STATIC_STORE_KEY, JSON.stringify(store)); } catch (_) {}
  }

  function getStaticSession() {
    const tok = getToken();
    if (tok && tok.startsWith("static:")) {
      try { return JSON.parse(atob(tok.slice(7))); } catch (_) {}
    }
    return null;
  }

  function setStaticSession(obj) {
    setToken("static:" + btoa(unescape(encodeURIComponent(JSON.stringify(obj)))));
  }

  async function apiFetch(path, opts = {}) {
    // Se estiver em GitHub Pages (não é localhost/127.0.0.1 e não é :8000), não há backend Python
    if (!isLocalHost && window.location.protocol !== "file:") {
      const err = new Error("Static host (GitHub Pages)");
      err.isNoBackend = true;
      err.status = 404;
      throw err;
    }

    const headers = Object.assign({}, opts.headers || {});
    const token = getToken();
    if (token && !token.startsWith("static:")) headers["X-Pulso-Session"] = token;
    if (opts.body && !(opts.body instanceof FormData) && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(API_BASE + path, { ...opts, headers, credentials: "include" });
    if (!res.ok) {
      let msg = "Erro de comunicação com o servidor PULSO.";
      let hasDetail = false;
      try {
        const err = await res.json();
        if (err && err.detail) {
          msg = err.detail;
          hasDetail = true;
        }
      } catch (_) {}
      const error = new Error(msg);
      error.status = res.status;
      error.isNoBackend = !hasDetail && (res.status === 404 || res.status === 405 || res.status >= 500);
      throw error;
    }
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res;
  }

  async function withFallback(apiFn, fallbackFn) {
    try {
      return await apiFn();
    } catch (err) {
      if (err && !err.isNoBackend && (err.status === 401 || err.status === 403 || err.status === 409 || err.status === 422)) {
        throw err;
      }
      return fallbackFn();
    }
  }

  function staticFindPatient(store, patientId) {
    return store.patients.find((p) => p.id === patientId) || store.patients[0];
  }

  window.PulsoAPI = {
    getToken,
    setToken,
    health: () => withFallback(() => apiFetch("/api/health"), () => ({ status: "ok", mode: "static" })),
    me: () =>
      withFallback(
        () => apiFetch("/api/me"),
        () => {
          const s = getStaticSession();
          if (!s) return { authenticated: false };
          const store = getStaticStore();
          const pat = staticFindPatient(store, s.patientId);
          return {
            authenticated: true,
            role: s.role,
            user: s.role === "doctor" ? { fullName: "Dra. Marta Fernandes", licenseNumber: s.licenseNumber || "48192", email: "marta.fernandes@usfsaojoao.pt" } : pat,
            patient: pat,
            doctor: s.role === "doctor" ? { fullName: "Dra. Marta Fernandes", licenseNumber: s.licenseNumber || "48192", clinic: "USF São João", email: "marta.fernandes@usfsaojoao.pt" } : null
          };
        }
      ),
    registerPatient: (data) =>
      withFallback(
        () => apiFetch("/api/auth/register", { method: "POST", body: JSON.stringify(data) }).then((r) => {
          if (r.sessionToken) setToken(r.sessionToken);
          return r;
        }),
        () => {
          const sns = String(data.snsNumber || "").replace(/\D+/g, "");
          if (sns.length !== 9) throw new Error("O Nº de Utente SNS deve conter exatamente 9 dígitos.");
          const store = getStaticStore();
          if (store.patients.some((p) => p.snsNumber === sns)) {
            throw new Error(`Já existe uma conta registada com o Nº de Utente SNS ${sns}.`);
          }
          const newPat = {
            id: "pat-" + Date.now(),
            snsNumber: sns,
            fullName: data.fullName,
            displayName: data.fullName,
            birthDate: data.birthDate || "1990-01-01",
            email: data.email || `${sns}@inbox.pulso.health`,
            password: data.password,
            clinicalAlerts: [],
            preferences: { theme: "dark", mode: "balanced", textSize: "standard", contrast: "high", reducedMotion: false },
            exams: [],
            measurements: [],
            events: [],
            auditLogs: [{ action: "REGISTER_SNS", actorRole: "patient", actorName: data.fullName, details: `Conta criada com SNS ${sns}.`, createdAt: Math.floor(Date.now() / 1000) }]
          };
          store.patients.push(newPat);
          saveStaticStore(store);
          setStaticSession({ role: "patient", patientId: newPat.id });
          return { ok: true, role: "patient", snsNumber: sns, displayName: newPat.fullName, patient: newPat };
        }
      ),
    loginPatient: (data) =>
      withFallback(
        () => apiFetch("/api/auth/login/patient", { method: "POST", body: JSON.stringify(data) }).then((r) => {
          if (r.sessionToken) setToken(r.sessionToken);
          return r;
        }),
        () => {
          const store = getStaticStore();
          const pat = store.patients.find((p) => p.snsNumber === String(data.snsNumber).trim() && p.password === data.password);
          if (!pat) throw new Error("Nº de Utente SNS não encontrado ou palavra-passe incorreta.");
          setStaticSession({ role: "patient", patientId: pat.id });
          return { ok: true, role: "patient", snsNumber: pat.snsNumber, displayName: pat.displayName, patient: pat };
        }
      ),
    loginDoctor: (data) =>
      withFallback(
        () => apiFetch("/api/auth/login/doctor", { method: "POST", body: JSON.stringify(data) }).then((r) => {
          if (r.sessionToken) setToken(r.sessionToken);
          return r;
        }),
        () => {
          const raw = String(data.accessCode || "").replace(/\s+/g, "");
          let validCode = "74921830";
          let durationLabel = "1 Hora";
          let remainingSeconds = 3600;
          try {
            const g = JSON.parse(localStorage.getItem("pulso_active_access_grant") || "null");
            if (g && g.code) {
              validCode = g.code;
              durationLabel = g.durationLabel || durationLabel;
              remainingSeconds = g.expiresInSeconds || remainingSeconds;
            }
          } catch (_) {}
          if (raw !== validCode && raw !== "74921830") {
            throw new Error("Código incorreto, expirado ou revogado pelo utente.");
          }
          const store = getStaticStore();
          const pat = store.patients[0];
          setStaticSession({ role: "doctor", patientId: pat.id, licenseNumber: data.licenseNumber || "48192" });
          return {
            ok: true,
            role: "doctor",
            grantCode: raw,
            durationLabel,
            remainingSeconds,
            patient: pat,
            doctor: { fullName: "Dra. Marta Fernandes", licenseNumber: data.licenseNumber || "48192", clinic: "USF São João", email: "marta.fernandes@usfsaojoao.pt" }
          };
        }
      ),
    logout: () =>
      withFallback(
        () => apiFetch("/api/auth/logout", { method: "POST" }),
        () => ({ ok: true })
      ).finally(() => setToken("")),
    updatePreferences: (prefs) =>
      withFallback(
        () => apiFetch("/api/auth/preferences", { method: "PATCH", body: JSON.stringify(prefs) }),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          pat.preferences = Object.assign({}, pat.preferences || {}, prefs);
          saveStaticStore(store);
          return { ok: true, preferences: pat.preferences };
        }
      ),
    updateProfile: (profile) =>
      withFallback(
        () => apiFetch("/api/auth/profile", { method: "PATCH", body: JSON.stringify(profile) }),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          if (profile.fullName) { pat.fullName = profile.fullName; pat.displayName = profile.fullName; }
          if (profile.email !== undefined) pat.email = profile.email;
          if (profile.birthDate) pat.birthDate = profile.birthDate;
          if (Array.isArray(profile.clinicalAlerts)) pat.clinicalAlerts = profile.clinicalAlerts;
          if (profile.password) pat.password = profile.password;
          pat.auditLogs.unshift({ action: "PROFILE_UPDATED", actorRole: s?.role || "patient", actorName: pat.displayName, details: "Dados do perfil atualizados.", createdAt: Math.floor(Date.now() / 1000) });
          saveStaticStore(store);
          return { ok: true };
        }
      ),
    createShareCode: (durationKey) =>
      withFallback(
        () => apiFetch("/api/share-codes", { method: "POST", body: JSON.stringify({ durationKey }) }),
        () => {
          const num1 = Math.floor(1000 + Math.random() * 9000);
          const num2 = Math.floor(1000 + Math.random() * 9000);
          const code = `${num1}${num2}`;
          const formattedCode = `${num1} ${num2}`;
          const secMap = { "1h": [3600, "1 Hora"], "1d": [86400, "1 Dia"], "1m": [2592000, "1 Mês"] };
          const [expiresInSeconds, durationLabel] = secMap[durationKey] || [3600, "1 Hora"];
          return { code, formattedCode, durationKey, durationLabel, expiresInSeconds };
        }
      ),
    getActiveShareCode: () => withFallback(() => apiFetch("/api/share-codes/active"), () => ({ active: null })),
    revokeShareCode: (code) =>
      withFallback(() => apiFetch(`/api/share-codes/${encodeURIComponent(code)}`, { method: "DELETE" }), () => ({ ok: true })),
    listRecords: () =>
      withFallback(
        () => apiFetch("/api/records"),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          return { exams: pat.exams || [], measurements: pat.measurements || [], events: pat.events || [], auditLogs: pat.auditLogs || [] };
        }
      ),
    createExam: (data) =>
      withFallback(
        () => apiFetch("/api/exams", { method: "POST", body: JSON.stringify(data) }),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          const ex = { id: "ex-" + Date.now(), ...data, institution: data.issuer || "Registo Manual", source: "Privado", intakeChannel: "OCR / Upload", biomarkers: data.extractedValues || [] };
          pat.exams.unshift(ex);
          saveStaticStore(store);
          return ex;
        }
      ),
    updateExam: (id, data) =>
      withFallback(
        () => apiFetch(`/api/exams/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(data) }),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          const ex = pat.exams.find((e) => e.id === id);
          if (ex) Object.assign(ex, data);
          saveStaticStore(store);
          return ex || { ok: true };
        }
      ),
    deleteExam: (id) =>
      withFallback(
        () => apiFetch(`/api/exams/${encodeURIComponent(id)}`, { method: "DELETE" }),
        () => {
          const s = getStaticSession();
          if (s && s.role === "doctor") throw new Error("Apenas o utente pode eliminar exames.");
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          pat.exams = pat.exams.filter((e) => e.id !== id);
          saveStaticStore(store);
          return { ok: true };
        }
      ),
    createMeasurement: (data) =>
      withFallback(
        () => apiFetch("/api/measurements", { method: "POST", body: JSON.stringify(data) }),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          const m = { id: "m-" + Date.now(), ...data };
          pat.measurements.unshift(m);
          saveStaticStore(store);
          return m;
        }
      ),
    deleteMeasurement: (id) =>
      withFallback(
        () => apiFetch(`/api/measurements/${encodeURIComponent(id)}`, { method: "DELETE" }),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          pat.measurements = pat.measurements.filter((m) => m.id !== id);
          saveStaticStore(store);
          return { ok: true };
        }
      ),
    createEvent: (data) =>
      withFallback(
        () => apiFetch("/api/events", { method: "POST", body: JSON.stringify(data) }),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          const ev = { id: "ev-" + Date.now(), ...data };
          pat.events.unshift(ev);
          saveStaticStore(store);
          return ev;
        }
      ),
    deleteEvent: (id) =>
      withFallback(
        () => apiFetch(`/api/events/${encodeURIComponent(id)}`, { method: "DELETE" }),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          pat.events = pat.events.filter((e) => e.id !== id);
          saveStaticStore(store);
          return { ok: true };
        }
      ),
    getCatalogs: () =>
      withFallback(
        () => apiFetch("/api/catalogs"),
        async () => {
          const [learn, reg, lab] = await Promise.all([
            fetch("./server/shared/learning.json").then((r) => r.json()),
            fetch("./server/shared/registration.json").then((r) => r.json()),
            fetch("./server/shared/laboratory.json").then((r) => r.json()),
          ]);
          return { learning: learn, registration: reg, laboratory: lab };
        }
      ),
    runExtraction: (file) =>
      withFallback(
        () => {
          const fd = new FormData();
          fd.append("file", file);
          return apiFetch("/api/extractions", { method: "POST", body: fd });
        },
        async () => ({
          fileName: file.name,
          extraction: {
            engine: "Modo Estático (GitHub Pages)",
            title: file.name.replace(/\.[^.]+$/, "") || "Análises Laboratoriais",
            category: "blood_tests",
            issuer: "Laboratório Clínico",
            examDate: new Date().toISOString().slice(0, 10),
            extractedValues: [
              { name: "Glicose em Jejum", value: 94, unit: "mg/dL", referenceRange: "70 - 100" },
              { name: "Creatinina", value: 0.98, unit: "mg/dL", referenceRange: "0.70 - 1.20" },
              { name: "Colesterol Total", value: 182, unit: "mg/dL", referenceRange: "< 190" }
            ],
            rawText: "Pré-visualização local pronta para revisão humana."
          }
        })
      ),
    getSamplePdfBlob: async () => {
      try {
        const res = await fetch(API_BASE + "/api/extractions/sample.pdf");
        if (res.ok) return res.blob();
      } catch (_) {}
      const staticRes = await fetch("./server/shared/laboratorio-demo.pdf");
      return staticRes.blob();
    },
    listConnectors: () =>
      withFallback(
        () => apiFetch("/api/connectors"),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          const links = pat.connectorLinks || {};
          return {
            connectors: STATIC_PT_CONNECTORS.map((c) => {
              const st = links[c.id] || { connected: c.id === "sns24", lastSync: null };
              return Object.assign({}, c, { connected: !!st.connected, lastSync: st.lastSync || null });
            }),
          };
        }
      ),
    toggleConnector: (provider, connected) =>
      withFallback(
        () => apiFetch(`/api/connectors/${encodeURIComponent(provider)}/connect`, { method: "POST", body: JSON.stringify({ connected: !!connected }) }),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          const conn = STATIC_PT_CONNECTORS.find((c) => c.id === provider);
          if (!conn) throw new Error("Conector desconhecido.");
          pat.connectorLinks = pat.connectorLinks || {};
          const prev = pat.connectorLinks[provider] || {};
          pat.connectorLinks[provider] = { connected: !!connected, lastSync: prev.lastSync || null };
          pat.auditLogs = pat.auditLogs || [];
          pat.auditLogs.unshift({
            action: connected ? "CONNECTOR_LINKED" : "CONNECTOR_UNLINKED",
            actorRole: s?.role || "patient",
            actorName: pat.displayName,
            details: `Conector ${conn.name} (${conn.protocol}) ${connected ? "associado" : "desligado"}.`,
            createdAt: Math.floor(Date.now() / 1000),
          });
          saveStaticStore(store);
          return { ok: true, provider, connected: !!connected };
        }
      ),
    syncConnector: (provider) =>
      withFallback(
        () => apiFetch(`/api/connectors/${encodeURIComponent(provider)}/sync`, { method: "POST" }),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          const conn = STATIC_PT_CONNECTORS.find((c) => c.id === provider);
          if (!conn) throw new Error("Conector desconhecido.");
          const now = Date.now() / 1000;
          pat.connectorLinks = pat.connectorLinks || {};
          pat.connectorLinks[provider] = { connected: true, lastSync: now };
          const exId = `conn-${pat.id || "pat"}-${conn.sampleExam.externalId}`;
          pat.exams = pat.exams || [];
          let imported = 0;
          if (!pat.exams.some((e) => e.id === exId)) {
            pat.exams.unshift({
              id: exId,
              title: conn.sampleExam.title,
              category: conn.sampleExam.category,
              examType: conn.sampleExam.examType,
              specialty: conn.sampleExam.specialty,
              issuer: conn.sampleExam.issuer,
              examDate: conn.sampleExam.examDate,
              summary: conn.sampleExam.summary,
              extractedValues: conn.sampleExam.extractedValues,
              addedByRole: s?.role || "patient",
              addedByName: `API ${conn.name}`,
              createdAt: now,
            });
            imported = 1;
          }
          pat.auditLogs = pat.auditLogs || [];
          pat.auditLogs.unshift({
            action: "CONNECTOR_SYNC",
            actorRole: s?.role || "patient",
            actorName: pat.displayName,
            details: `Sincronização ${conn.name} (${conn.protocol}): ${imported} novo(s) registo(s).`,
            createdAt: Math.floor(now),
          });
          saveStaticStore(store);
          return { ok: true, provider, imported, examId: exId, lastSync: now };
        }
      ),
    triggerEmergency: (data) =>
      withFallback(
        () => apiFetch("/api/emergency/trigger", { method: "POST", body: JSON.stringify(data || {}) }),
        () => {
          const s = getStaticSession();
          const store = getStaticStore();
          const pat = staticFindPatient(store, s?.patientId);
          const now = Date.now() / 1000;
          const evid = "emg-" + Math.random().toString(36).slice(2, 10);
          const mode = (data && data.mode) || "manual_hold_2s";
          const neighbors = (data && data.neighborsNotified) || 3;
          const gps = (data && data.gps) || "41.1780° N, 8.6080° W (Porto)";
          const details = `Pulso=${data && data.onWrist !== false} · GPS=${gps} · Vizinhos=${neighbors} · ${(data && data.notes) || "Acionamento de emergência médica"}`;
          pat.events = pat.events || [];
          pat.events.unshift({
            id: evid,
            title: `ALERTA SOS (${mode}) · 112 & ${neighbors} Vizinhos`,
            eventType: "urgent",
            startDate: new Date().toISOString().slice(0, 10),
            endDate: null,
            notes: details,
            addedByRole: s?.role || "patient",
            addedByName: pat.displayName,
            createdAt: now,
          });
          pat.auditLogs = pat.auditLogs || [];
          pat.auditLogs.unshift({
            action: "EMERGENCY_SOS_TRIGGERED",
            actorRole: s?.role || "patient",
            actorName: pat.displayName,
            details,
            createdAt: Math.floor(now),
          });
          saveStaticStore(store);
          return { ok: true, id: evid, gps, neighborsNotified: neighbors, timestamp: now };
        }
      ),
  };

  const STATIC_PT_CONNECTORS = [
    {
      id: "sns24",
      name: "SNS 24 / SPMS (RSE)",
      group: "SNS Público",
      protocol: "HL7 FHIR R4 · RSE/PDS",
      description: "Registo de Saúde Eletrónico, prescrições eletrónicas, boletim de vacinas e altas hospitalares do SNS.",
      sampleExam: {
        externalId: "sns24-rse-2026-01",
        title: "Painel Metabólico & HbA1c — USF São João (SNS 24)",
        category: "blood_tests",
        examType: "Análises Clínicas SNS",
        specialty: "Medicina Geral e Familiar",
        issuer: "SNS / SPMS — USF São João",
        examDate: "2026-10-18",
        summary: "Sincronizado automaticamente via RSE/SNS 24. Controlo glicémico estável.",
        extractedValues: [
          { name: "Hemoglobina Glicada (HbA1c)", value: 6.1, unit: "%", referenceRange: "< 6.5" },
          { name: "Glicose em Jejum", value: 98, unit: "mg/dL", referenceRange: "70 - 100" },
          { name: "Potássio", value: 4.3, unit: "mmol/L", referenceRange: "3.5 - 5.1" },
        ],
      },
    },
    {
      id: "cuf",
      name: "CUF / MyCUF",
      group: "Hospital Privado",
      protocol: "FHIR R4 / OAuth2 MyCUF",
      description: "Relatórios de consulta, cardiologia, imagiologia e análises clínicas da rede CUF.",
      sampleExam: {
        externalId: "cuf-cardio-2026-02",
        title: "Prova de Esforço & ECG — Hospital CUF Porto",
        category: "cardiology",
        examType: "Electrocardiograma / Prova de Esforço",
        specialty: "Cardiologia",
        issuer: "Hospital CUF Porto",
        examDate: "2026-10-22",
        summary: "Sincronizado via MyCUF API. Sem alterações isquémicas durante esforço submáximo.",
        extractedValues: [
          { name: "FC Máxima Atingida", value: 142, unit: "bpm", referenceRange: "120 - 160" },
          { name: "Pressão Arterial Pico", value: 158, unit: "mmHg", referenceRange: "< 190" },
        ],
      },
    },
    {
      id: "luz",
      name: "Hospital da Luz / MY LUZ",
      group: "Hospital Privado",
      protocol: "FHIR R4 / Portal MY LUZ",
      description: "Episódios de urgência, relatórios médicos, exames de imagem e prescrições Luz Saúde.",
      sampleExam: {
        externalId: "luz-img-2026-03",
        title: "TAC Torácica Baixa Dose — Hospital da Luz Arrábida",
        category: "imaging",
        examType: "Tomografia Computorizada",
        specialty: "Imagiologia",
        issuer: "Hospital da Luz Arrábida",
        examDate: "2026-10-29",
        summary: "Sincronizado via MY LUZ. Parênquima pulmonar sem lesões focais agudas.",
        extractedValues: [
          { name: "Índice Cálcio Coronário", value: 42, unit: "Agatston", referenceRange: "< 100" },
        ],
      },
    },
    {
      id: "lusiadas",
      name: "Lusíadas Saúde / +Lusíadas",
      group: "Hospital Privado",
      protocol: "HL7 FHIR / +Lusíadas",
      description: "Notas de alta, análises e relatórios de especialidades da rede Lusíadas.",
      sampleExam: {
        externalId: "lusiadas-neuro-2026-04",
        title: "Eco-Doppler Carotídeo — Hospital Lusíadas Porto",
        category: "imaging",
        examType: "Eco-Doppler Vascular",
        specialty: "Neurologia / Angiologia",
        issuer: "Hospital Lusíadas Porto",
        examDate: "2026-11-02",
        summary: "Sincronizado via +Lusíadas. Fluxo carotídeo bilateral preservado, sem estenose significativa.",
        extractedValues: [
          { name: "Estenose Carotídea", value: 12, unit: "%", referenceRange: "< 50" },
        ],
      },
    },
    {
      id: "trofa",
      name: "Trofa Saúde",
      group: "Hospital Privado",
      protocol: "FHIR R4 / Portal Trofa Saúde",
      description: "Resultados laboratoriais, imagiologia e consultas externas na rede Trofa Saúde.",
      sampleExam: {
        externalId: "trofa-pulmo-2026-05",
        title: "Espirometria Basal — Trofa Saúde Alfena",
        category: "clinical_notes",
        examType: "Provas Funcionais Respiratórias",
        specialty: "Pneumologia",
        issuer: "Hospital Trofa Saúde Alfena",
        examDate: "2026-11-04",
        summary: "Sincronizado via Trofa Saúde API. Padrão ventilatório dentro dos parâmetros normais.",
        extractedValues: [
          { name: "FEV1 (% previsto)", value: 94, unit: "%", referenceRange: ">= 80" },
        ],
      },
    },
    {
      id: "unilabs",
      name: "Unilabs Portugal",
      group: "Laboratório Clínico",
      protocol: "HL7 / LOINC · Unilabs Connect",
      description: "Importação direta de análises clínicas, bioquímica, perfil lipídico e anatomia patológica.",
      sampleExam: {
        externalId: "unilabs-lip-2026-06",
        title: "Perfil Lipídico & Função Renal — Unilabs Portugal",
        category: "blood_tests",
        examType: "Bioquímica Sanguínea",
        specialty: "Patologia Clínica",
        issuer: "Unilabs Portugal",
        examDate: "2026-11-07",
        summary: "Sincronizado via Unilabs Connect (LOINC). Função renal estável; LDL controlado.",
        extractedValues: [
          { name: "Colesterol LDL", value: 88, unit: "mg/dL", referenceRange: "< 115" },
          { name: "Creatinina", value: 0.96, unit: "mg/dL", referenceRange: "0.70 - 1.20" },
          { name: "eGFR", value: 84, unit: "mL/min", referenceRange: ">= 60" },
        ],
      },
    },
    {
      id: "germano",
      name: "Germano de Sousa",
      group: "Laboratório Clínico",
      protocol: "FHIR Observation / LOINC",
      description: "Análises clínicas, hematologia, marcadores tiroideus e serologias do Centro de Medicina Laboratorial.",
      sampleExam: {
        externalId: "germano-tir-2026-07",
        title: "Hemograma & Função Tiroideia — Germano de Sousa",
        category: "blood_tests",
        examType: "Hematologia & Endocrinologia",
        specialty: "Patologia Clínica",
        issuer: "Centro de Medicina Laboratorial Germano de Sousa",
        examDate: "2026-11-09",
        summary: "Sincronizado via API Germano de Sousa. Hemoglobina e TSH em valores de referência.",
        extractedValues: [
          { name: "Hemoglobina", value: 14.3, unit: "g/dL", referenceRange: "13.0 - 17.5" },
          { name: "TSH", value: 2.1, unit: "mUI/L", referenceRange: "0.4 - 4.0" },
        ],
      },
    },
    {
      id: "jcs",
      name: "Joaquim Chaves Saúde",
      group: "Laboratório Clínico",
      protocol: "FHIR / Portal JCS",
      description: "Resultados laboratoriais e cardiologia diagnóstica da rede Joaquim Chaves Saúde.",
      sampleExam: {
        externalId: "jcs-vit-2026-08",
        title: "Vitamina D & Ferritina — Joaquim Chaves Saúde",
        category: "blood_tests",
        examType: "Bioquímica & Vitaminas",
        specialty: "Patologia Clínica",
        issuer: "Joaquim Chaves Saúde",
        examDate: "2026-11-11",
        summary: "Sincronizado via Portal JCS. Reservas de ferro e vitamina D adequadas.",
        extractedValues: [
          { name: "25-OH Vitamina D", value: 36, unit: "ng/mL", referenceRange: "30 - 100" },
          { name: "Ferritina", value: 112, unit: "ng/mL", referenceRange: "30 - 300" },
        ],
      },
    },
    {
      id: "synlab",
      name: "Synlab Portugal",
      group: "Laboratório Clínico",
      protocol: "HL7 FHIR / Synlab Direct",
      description: "Análises clínicas, imunologia e testes preventivos da rede Synlab Portugal.",
      sampleExam: {
        externalId: "synlab-hep-2026-09",
        title: "Painel Hepático & Proteína C Reativa — Synlab Portugal",
        category: "blood_tests",
        examType: "Bioquímica Hepática",
        specialty: "Patologia Clínica",
        issuer: "Synlab Portugal",
        examDate: "2026-11-12",
        summary: "Sincronizado via Synlab Direct. Transaminases normais e PCR sem atividade inflamatória.",
        extractedValues: [
          { name: "PCR (Proteína C Reativa)", value: 1.8, unit: "mg/L", referenceRange: "< 5.0" },
          { name: "ALT (TGP)", value: 24, unit: "U/L", referenceRange: "< 41" },
        ],
      },
    },
  ];
})();
