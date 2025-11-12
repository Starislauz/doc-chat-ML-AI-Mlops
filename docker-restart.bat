@echo off
REM ================================================
REM RAG Document Chat - Restart Services
REM ================================================

echo.
echo Restarting services...
echo.

docker-compose restart

if errorlevel 1 (
    echo [ERROR] Failed to restart services
    pause
    exit /b 1
)

echo.
echo [OK] Services restarted successfully
echo.
echo Check status: docker-status.bat
echo View logs:    docker-logs.bat
echo.

pause
