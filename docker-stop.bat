@echo off
REM ================================================
REM RAG Document Chat - Stop Services
REM ================================================

echo.
echo Stopping services...
echo.

docker-compose stop

if errorlevel 1 (
    echo [ERROR] Failed to stop services
    pause
    exit /b 1
)

echo.
echo [OK] Services stopped successfully
echo.
echo To start again: docker-start.bat
echo.

pause
