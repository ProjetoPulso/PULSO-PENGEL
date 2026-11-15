@echo off
title PULSO - Arranque do Site Clinico e App Utente
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [PULSO] A criar ambiente virtual Python (.venv)...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERRO] Python nao encontrado no PATH.
    pause
    exit /b 1
  )
  echo [PULSO] A instalar dependencias do servidor...
  ".venv\Scripts\python.exe" -m pip install -r server\requirements.txt
)

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if %errorlevel%==0 (
  echo [PULSO] Servidor ja esta ativo em http://127.0.0.1:8000
) else (
  echo [PULSO] A iniciar servidor FastAPI em http://127.0.0.1:8000 ...
  start "PULSO Backend Server" .venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8000
  powershell -NoProfile -Command "for ($i=0; $i -lt 20; $i++) { try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1"
)

start "" "http://127.0.0.1:8000/demo_aula.html"
