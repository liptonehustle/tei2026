@echo off
title Stop AI Trading Platform
echo ================================================
echo  Stopping AI Trading Platform...
echo ================================================

echo [1/3] Stopping Data Ingestion...
taskkill /FI "WINDOWTITLE eq Data Ingestion" /F >nul 2>&1
echo       Done.

echo [2/3] Stopping Indicator Engine...
taskkill /FI "WINDOWTITLE eq Indicator Engine" /F >nul 2>&1
echo       Done.

echo [3/3] Stopping Trading Engine...
taskkill /FI "WINDOWTITLE eq Trading Engine" /F >nul 2>&1
echo       Done.

echo.
echo Stopping Docker infrastructure...
docker-compose down
echo       Done.

echo.
echo ================================================
echo  All services stopped successfully.
echo ================================================
pause