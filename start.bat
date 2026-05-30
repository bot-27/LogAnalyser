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
REM 2. Build and start app containers
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
REM 3. Health check
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
echo  ============================================================
echo.
pause
