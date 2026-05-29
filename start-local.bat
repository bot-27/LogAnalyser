@echo off
echo Starting LogAnalyzer locally in Python Virtual Environment...
echo ==========================================================

REM Check if python is installed
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    pause
    exit /b 1
)

REM Check if venv directory exists, create if not
if not exist venv\Scripts\activate.bat (
    echo [INFO] Virtual environment not found. Creating virtual environment in .\venv...
    python -m venv venv
)

echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

echo [INFO] Installing/updating dependencies from backend\requirements.txt...
python -m pip install --upgrade pip
pip install -r backend\requirements.txt

echo.
echo ==========================================================
echo Starting LogAnalyzer backend...
echo You can access the UI at: http://localhost:8000
echo ==========================================================
python backend\app.py

pause
