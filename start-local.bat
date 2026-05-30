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

REM 4. Verify Redis via Python script
echo  [INFO] Checking Redis connection...
python -c "import redis; r=redis.Redis(host='localhost', port=6379, db=0); r.ping()" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [WARN] Redis is not running locally on port 6379.
    echo  [WARN] Please start Redis (e.g. via Docker) before proceeding.
    echo  [WARN] Starting it via Docker: docker run -d -p 6379:6379 redis
    pause
)

REM 5. Ensure data directory
if not exist data mkdir data

REM 6. Start Celery worker in background
echo  [INFO] Starting Celery worker in a new window...
start "Celery Worker" cmd /c "call venv\Scripts\activate.bat && celery -A backend.worker.tasks:celery_app worker --loglevel=info --pool=solo"

REM 7. Start FastAPI
echo.
echo  ============================================================
echo   LogAnalyzer is starting up!
echo.
echo   UI:     http://localhost:8000
echo   API:    http://localhost:8000/docs
echo.
echo   Press Ctrl+C in this window to stop the API server.
echo   Close the Celery Worker window to stop the worker.
echo  ============================================================
echo.

uvicorn backend.api.app:app --reload --host 0.0.0.0 --port 8000
