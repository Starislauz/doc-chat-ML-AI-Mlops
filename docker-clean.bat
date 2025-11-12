@echo off
REM ================================================
REM RAG Document Chat - Clean Stop
REM Stops and removes containers (keeps data)
REM ================================================

echo.
echo ================================================
echo  WARNING: This will stop and remove containers
echo  Your data will be preserved in Docker volumes
echo ================================================
echo.

set /p confirm="Are you sure? (Y/N): "
if /i not "%confirm%"=="Y" (
    echo Operation cancelled
    pause
    exit /b
)

echo.
echo Stopping and removing containers...
echo.

docker-compose down

if errorlevel 1 (
    echo [ERROR] Failed to clean containers
    pause
    exit /b 1
)

echo.
echo [OK] Containers removed successfully
echo      Your data is preserved in Docker volumes
echo.
echo To start again: docker-start.bat
echo.

pause
