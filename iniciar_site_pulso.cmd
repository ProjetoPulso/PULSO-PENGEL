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

echo [PULSO] A iniciar servidor FastAPI em http://127.0.0.1:8000 ...
start "PULSO Backend Server" cmd /k "cd /d "%~dp0" && ".venv\Scripts\uvicorn.exe" server.app:app --host 127.0.0.1 --port 8000"

timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8000/demo_aula.html"
echo [PULSO] Site aberto em http://127.0.0.1:8000/demo_aula.html
