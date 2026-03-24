@echo off
title AI Trading Platform
echo ================================================
echo  AI Trading Platform — Launcher
echo ================================================

:: Start infrastructure
echo [1/4] Starting Docker infrastructure...
docker-compose up -d
timeout /t 5 /nobreak >nul

:: Start data ingestion in new window
echo [2/4] Starting Data Ingestion...
start "Data Ingestion" cmd /k "cd /d %~dp0 && venv\Scripts\activate && python -m data_ingestion.scheduler"
timeout /t 3 /nobreak >nul

:: Start indicator engine in new window
echo [3/4] Starting Indicator Engine...
start "Indicator Engine" cmd /k "cd /d %~dp0 && venv\Scripts\activate && python -m data_processing.indicator_engine --mode scheduler"
timeout /t 3 /nobreak >nul

:: Start trading engine in new window
echo [4/4] Starting Trading Engine...
start "Trading Engine" cmd /k "cd /d %~dp0 && venv\Scripts\activate && python -m execution_engine.scheduler"

echo.
echo ================================================
echo  All services started!
echo  - Grafana Dashboard: http://localhost:3000
echo  - pgAdmin:           http://localhost:5050
echo ================================================
echo.
pause