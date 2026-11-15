/* PULSO — Unified Web Client (API SQLite + RBAC + 8 Pulso DS Modules) */
(function () {
  const SESSION_KEY = "pulso_api_session_token";

  function getToken() {
    return sessionStorage.getItem(SESSION_KEY) || "";
  }
  function setToken(t) {
    if (t) sessionStorage.setItem(SESSION_KEY, t);
    else sessionStorage.removeItem(SESSION_KEY);
  }

  const API_BASE =
    window.location.protocol === "file:" || (window.location.port && window.location.port !== "8000")
      ? "http://127.0.0.1:8000"
      : "";

  async function apiFetch(path, opts = {}) {
    const headers = Object.assign({}, opts.headers || {});
    const token = getToken();
    if (token) headers["X-Pulso-Session"] = token;
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

  window.PulsoAPI = {
    getToken,
    setToken,
    health: () => apiFetch("/api/health"),
    me: () => apiFetch("/api/me"),
    registerPatient: (data) =>
      apiFetch("/api/auth/register", { method: "POST", body: JSON.stringify(data) }).then((r) => {
        if (r.sessionToken) setToken(r.sessionToken);
        return r;
      }),
    loginPatient: (data) =>
      apiFetch("/api/auth/login/patient", { method: "POST", body: JSON.stringify(data) }).then((r) => {
        if (r.sessionToken) setToken(r.sessionToken);
        return r;
      }),
    loginDoctor: (data) =>
      apiFetch("/api/auth/login/doctor", { method: "POST", body: JSON.stringify(data) }).then((r) => {
        if (r.sessionToken) setToken(r.sessionToken);
        return r;
      }),
    logout: () =>
      apiFetch("/api/auth/logout", { method: "POST" }).finally(() => {
        setToken("");
      }),
    updatePreferences: (prefs) =>
      apiFetch("/api/auth/preferences", { method: "PATCH", body: JSON.stringify(prefs) }),
    createShareCode: (durationKey) =>
      apiFetch("/api/share-codes", { method: "POST", body: JSON.stringify({ durationKey }) }),
    getActiveShareCode: () => apiFetch("/api/share-codes/active"),
    revokeShareCode: (code) =>
      apiFetch(`/api/share-codes/${encodeURIComponent(code)}`, { method: "DELETE" }),
    listRecords: () => apiFetch("/api/records"),
    createExam: (data) =>
      apiFetch("/api/exams", { method: "POST", body: JSON.stringify(data) }),
    updateExam: (id, data) =>
      apiFetch(`/api/exams/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(data) }),
    deleteExam: (id) =>
      apiFetch(`/api/exams/${encodeURIComponent(id)}`, { method: "DELETE" }),
    createMeasurement: (data) =>
      apiFetch("/api/measurements", { method: "POST", body: JSON.stringify(data) }),
    deleteMeasurement: (id) =>
      apiFetch(`/api/measurements/${encodeURIComponent(id)}`, { method: "DELETE" }),
    createEvent: (data) =>
      apiFetch("/api/events", { method: "POST", body: JSON.stringify(data) }),
    deleteEvent: (id) =>
      apiFetch(`/api/events/${encodeURIComponent(id)}`, { method: "DELETE" }),
    getCatalogs: () => apiFetch("/api/catalogs"),
    runExtraction: (file) => {
      const fd = new FormData();
      fd.append("file", file);
      return apiFetch("/api/extractions", { method: "POST", body: fd });
    },
    getSamplePdfBlob: async () => {
      const res = await fetch("/api/extractions/sample.pdf");
      return res.blob();
    },
  };
})();
