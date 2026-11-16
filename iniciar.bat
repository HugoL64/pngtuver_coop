@echo off
chcp 65001 > nul
title PNGTuber Duo / Coop
echo ========================================================
echo        Iniciando PNGTuber Duo / Coop...
echo ========================================================
python -u main.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Hubo un error al ejecutar la aplicacion (Codigo: %errorlevel%).
    echo Presiona cualquier tecla para salir...
    pause > nul
)
