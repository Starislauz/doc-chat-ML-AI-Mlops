@echo off
REM ================================================
REM RAG Document Chat - Service Status
REM ================================================

echo.
echo ================================================
echo  Service Status
echo ================================================
echo.

docker-compose ps

echo.
echo ================================================
echo  Health Check
echo ================================================
echo.

curl -s http://localhost:8000/health 2>nul
if errorlevel 1 (
    echo [ERROR] Backend not responding
    echo.
    echo Try:
    echo   - Check if services are running: docker-compose ps
    echo   - View logs: docker-logs.bat
    echo   - Restart services: docker-restart.bat
) else (
    echo.
    echo [OK] Backend is healthy
)

echo.
echo.
pause
