@echo off
REM ================================================
REM RAG Document Chat - View Logs
REM ================================================

echo.
echo Viewing service logs...
echo Press Ctrl+C to stop viewing logs
echo.

docker-compose logs -f --tail=100
