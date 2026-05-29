@echo off
echo Starting LogAnalyzer Container...
echo =================================

REM Check if Docker is running
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not running. Please start Docker Desktop and try again.
    pause
    exit /b 1
)

echo Building and starting the container...
docker-compose up -d --build

echo.
echo =================================
echo LogAnalyzer is now running!
echo You can access it at: http://localhost:8000
echo =================================
pause
