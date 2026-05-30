@echo off
setlocal EnableDelayedExpansion

echo.
echo  ============================================================
echo   LogAnalyzer Agent — Local Development Launcher
echo  ============================================================
echo.

REM 1. Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  [FAIL] Python is not installed or not in PATH.
    pause
    exit /b 1
)

REM 2. Virtual environment
if not exist venv\Scripts\activate.bat (
    echo  [INFO] Virtual environment not found. Creating .\venv ...
    python -m venv venv
)
call venv\Scripts\activate.bat

REM 3. Install dependencies
echo  [INFO] Installing dependencies ...
python -m pip install --upgrade pip --quiet >nul 2>&1
pip install -r requirements.txt --quiet >nul 2>&1
if exist backend\requirements.txt (
    pip install -r backend\requirements.txt --quiet >nul 2>&1
)

REM 4. Ensure data directory
if not exist data mkdir data

REM 5. Start FastAPI
echo.
echo  ============================================================
echo   LogAnalyzer is starting up!
echo.
echo   UI:     http://localhost:8000
echo   API:    http://localhost:8000/docs
echo.
echo   Press Ctrl+C in this window to stop the API server.
echo  ============================================================
echo.

uvicorn backend.api.app:app --reload --host 0.0.0.0 --port 8000
