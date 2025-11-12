@echo off
REM ================================================
REM RAG Document Chat - Quick Start
REM Windows Batch Script
REM ================================================

echo.
echo ================================================
echo  RAG Document Chat - Docker Setup
echo ================================================
echo.

REM Check if .env exists
if not exist .env (
    echo [SETUP] Creating .env file from template...
    copy .env.example .env >nul
    echo [OK] .env file created
    echo.
    echo [IMPORTANT] Please edit .env file and add your GEMINI_API_KEY
    echo             Get API key from: https://makersuite.google.com/app/apikey
    echo.
    echo After adding API key, run this script again.
    pause
    exit /b
)

echo [CHECK] .env file exists
echo.

REM Check if Docker is running
docker version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running!
    echo         Please start Docker Desktop and try again.
    pause
    exit /b 1
)

echo [OK] Docker is running
echo.

REM Build and start services
echo [BUILD] Building Docker images...
docker-compose build

if errorlevel 1 (
    echo [ERROR] Failed to build Docker images
    pause
    exit /b 1
)

echo.
echo [START] Starting services...
docker-compose up -d

if errorlevel 1 (
    echo [ERROR] Failed to start services
    pause
    exit /b 1
)

echo.
echo ================================================
echo  SUCCESS! Services Started
echo ================================================
echo.
echo  Frontend:  http://localhost
echo  Backend:   http://localhost:8000
echo  API Docs:  http://localhost:8000/docs
echo  Health:    http://localhost:8000/health
echo.
echo To view logs:       docker-logs.bat
echo To stop services:   docker-stop.bat
echo To check status:    docker-status.bat
echo.
echo ================================================
echo.

pause
