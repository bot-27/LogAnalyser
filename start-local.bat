@echo off
setlocal EnableDelayedExpansion

echo.
echo  ============================================================
echo   LogAnalyzer Agent — Local Development Launcher
echo  ============================================================
echo.

REM ------------------------------------------------------------------
REM 1. Check Python
REM ------------------------------------------------------------------
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  [FAIL] Python is not installed or not in PATH.
    echo         Download from https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  [OK]   %PY_VER% found

REM ------------------------------------------------------------------
REM 2. Virtual environment
REM ------------------------------------------------------------------
if not exist venv\Scripts\activate.bat (
    echo  [INFO] Virtual environment not found. Creating .\\venv ...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo  [FAIL] Could not create virtual environment.
        pause
        exit /b 1
    )
    echo  [OK]   Virtual environment created
) else (
    echo  [OK]   Virtual environment exists
)

call venv\Scripts\activate.bat
echo  [OK]   venv activated

REM ------------------------------------------------------------------
REM 3. Install / update pip dependencies
REM ------------------------------------------------------------------
echo  [INFO] Installing dependencies ...
python -m pip install --upgrade pip --quiet >nul 2>&1
pip install -r requirements.txt --quiet >nul 2>&1
if %errorlevel% neq 0 (
    echo  [WARN] pip install had issues — trying without --quiet ...
    pip install -r requirements.txt
)

REM Also install backend deps for the original monolith (if needed)
if exist backend\requirements.txt (
    pip install -r backend\requirements.txt --quiet >nul 2>&1
)
echo  [OK]   Dependencies installed

REM ------------------------------------------------------------------
REM 4. Check critical Python packages
REM ------------------------------------------------------------------
python -c "import fastapi" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [FAIL] FastAPI is not installed. Run: pip install fastapi
    pause
    exit /b 1
)
echo  [OK]   FastAPI available

python -c "import celery" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [FAIL] Celery is not installed. Run: pip install celery
    pause
    exit /b 1
)
echo  [OK]   Celery available

python -c "import sqlalchemy" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [FAIL] SQLAlchemy is not installed. Run: pip install sqlalchemy
    pause
    exit /b 1
)
echo  [OK]   SQLAlchemy available

python -c "import redis" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [FAIL] Redis Python client is not installed. Run: pip install redis
    pause
    exit /b 1
)
echo  [OK]   Redis client available

REM ------------------------------------------------------------------
REM 5. Check Redis server connectivity
REM    Uses a temp script to avoid batch choking on Python parentheses
REM ------------------------------------------------------------------
echo  [INFO] Checking Redis server on localhost:6379 ...

set REDIS_CHECK=%TEMP%\loganalyzer_redis_check.py
echo import redis > "%REDIS_CHECK%"
echo r = redis.Redis(host="localhost", port=6379, socket_connect_timeout=3) >> "%REDIS_CHECK%"
echo r.ping() >> "%REDIS_CHECK%"

python "%REDIS_CHECK%" >nul 2>&1
if %errorlevel% equ 0 (
    echo  [OK]   Redis server is reachable
    goto :redis_ok
)

REM Redis not reachable — try to start it via Docker
echo  [WARN] Redis is not reachable. Attempting Docker auto-start ...

where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo  [FAIL] Docker not found either. Cannot auto-start Redis.
    goto :redis_fail
)

docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo  [FAIL] Docker daemon is not running. Cannot auto-start Redis.
    goto :redis_fail
)

REM Check if a container named "redis" already exists
docker ps -a --filter "name=^redis$" --format "{{.Names}}" 2>nul | findstr /x "redis" >nul 2>&1
if %errorlevel% equ 0 (
    echo  [INFO] Found existing Redis container. Starting it ...
    docker start redis >nul 2>&1
) else (
    echo  [INFO] Creating new Redis container ...
    docker run -d --name redis -p 6379:6379 redis:latest >nul 2>&1
)

if %errorlevel% neq 0 (
    echo  [FAIL] Could not start Redis container.
    goto :redis_fail
)

REM Wait for Redis to be ready
echo  [INFO] Waiting for Redis to accept connections ...
timeout /t 3 /nobreak >nul

python "%REDIS_CHECK%" >nul 2>&1
if %errorlevel% equ 0 (
    echo  [OK]   Redis started via Docker and is reachable
    goto :redis_ok
)

echo  [FAIL] Redis container started but still not reachable on port 6379.
goto :redis_fail

:redis_fail
echo.
echo  ============================================================
echo   Redis is REQUIRED as the Celery message broker.
echo.
echo   Option A — Docker:
echo     docker run -d --name redis -p 6379:6379 redis:latest
echo.
echo   Option B — Memurai (native Windows):
echo     https://www.memurai.com/get-memurai
echo.
echo   Option C — WSL:
echo     wsl -e sudo service redis-server start
echo  ============================================================
echo.
del "%REDIS_CHECK%" >nul 2>&1
pause
exit /b 1

:redis_ok
del "%REDIS_CHECK%" >nul 2>&1

REM ------------------------------------------------------------------
REM 6. Ensure data directory exists
REM ------------------------------------------------------------------
if not exist data mkdir data
echo  [OK]   data\ directory ready

REM ------------------------------------------------------------------
REM 7. Start services
REM ------------------------------------------------------------------
echo.
echo  ============================================================
echo   Starting services ...
echo  ============================================================
echo.

REM Start Celery worker in a new window
echo  [INFO] Starting Celery worker ...
start "LogAnalyzer — Celery Worker" cmd /k "cd /d %~dp0 && call venv\Scripts\activate.bat && celery -A worker.tasks:celery_app worker --loglevel=info --pool=solo"

REM Give Celery a moment to connect to Redis
timeout /t 3 /nobreak >nul

REM Start FastAPI in a new window
echo  [INFO] Starting FastAPI server ...
start "LogAnalyzer — FastAPI" cmd /k "cd /d %~dp0 && call venv\Scripts\activate.bat && uvicorn api.app:app --reload --host 0.0.0.0 --port 8000"

echo.
echo  ============================================================
echo   LogAnalyzer is starting up!
echo.
echo   UI:     http://localhost:8000
echo   API:    http://localhost:8000/docs
echo.
echo   Two new terminal windows have been opened:
echo     - Celery Worker  (background task processor)
echo     - FastAPI Server  (HTTP API)
echo.
echo   Close those windows to stop the services.
echo  ============================================================
echo.
pause
