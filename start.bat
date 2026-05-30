@echo off
setlocal EnableDelayedExpansion

echo.
echo  ============================================================
echo   LogAnalyzer Agent — Docker Launcher
echo  ============================================================
echo.

REM ------------------------------------------------------------------
REM 1. Check Docker
REM ------------------------------------------------------------------
where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo  [FAIL] Docker is not installed or not in PATH.
    echo         Download from https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)
echo  [OK]   Docker CLI found

docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo  [FAIL] Docker daemon is not running.
    echo         Please start Docker Desktop and try again.
    pause
    exit /b 1
)
echo  [OK]   Docker daemon is running

REM ------------------------------------------------------------------
REM 2. Ensure Redis container is running
REM ------------------------------------------------------------------
echo  [INFO] Checking Redis container ...

docker ps --filter "name=redis" --format "{{.Names}}" 2>nul | findstr /i "redis" >nul 2>&1
if %errorlevel% neq 0 (
    REM Check if a stopped redis container exists
    docker ps -a --filter "name=redis" --format "{{.Names}}" 2>nul | findstr /i "redis" >nul 2>&1
    if %errorlevel% equ 0 (
        echo  [INFO] Starting existing Redis container ...
        docker start redis >nul 2>&1
    ) else (
        echo  [INFO] Creating new Redis container ...
        docker run -d --name redis -p 6379:6379 redis:latest >nul 2>&1
    )
    if %errorlevel% neq 0 (
        echo  [FAIL] Could not start Redis container.
        pause
        exit /b 1
    )
)
echo  [OK]   Redis container is running

REM ------------------------------------------------------------------
REM 3. Verify Redis is accepting connections
REM ------------------------------------------------------------------
timeout /t 2 /nobreak >nul
docker exec redis redis-cli ping >nul 2>&1
if %errorlevel% neq 0 (
    echo  [WARN] Redis started but not yet accepting connections. Waiting ...
    timeout /t 3 /nobreak >nul
    docker exec redis redis-cli ping >nul 2>&1
    if %errorlevel% neq 0 (
        echo  [FAIL] Redis is not responding to PING.
        pause
        exit /b 1
    )
)
echo  [OK]   Redis is responding to PING

REM ------------------------------------------------------------------
REM 4. Build and start app containers
REM ------------------------------------------------------------------
echo.
echo  [INFO] Building and starting LogAnalyzer containers ...
docker-compose up -d --build

if %errorlevel% neq 0 (
    echo  [FAIL] docker-compose up failed.
    pause
    exit /b 1
)

REM ------------------------------------------------------------------
REM 5. Health check
REM ------------------------------------------------------------------
echo.
echo  [INFO] Waiting for services to start ...
timeout /t 5 /nobreak >nul

REM Try to hit the health/root endpoint
curl -s -o nul -w "%%{http_code}" http://localhost:8000/ >nul 2>&1
if %errorlevel% equ 0 (
    echo  [OK]   FastAPI is responding
) else (
    echo  [WARN] Could not reach http://localhost:8000 yet.
    echo         It may still be starting. Check: docker-compose logs -f
)

echo.
echo  ============================================================
echo   LogAnalyzer is now running!
echo.
echo   UI:     http://localhost:8000
echo   API:    http://localhost:8000/docs
echo.
echo   Useful commands:
echo     docker-compose logs -f          View live logs
echo     docker-compose down             Stop all containers
echo     docker stop redis               Stop Redis
echo  ============================================================
echo.
pause
