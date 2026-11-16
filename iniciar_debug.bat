@echo off
chcp 65001 > nul
title [CONSOLA DEBUG] PNGTuber Duo / Coop
color 0A
echo ======================================================================
echo           PNGTUBER DUO / CO-OP - CONSOLA DE DEBUG EN VIVO
echo ======================================================================
echo   Aqui veras en tiempo real cada accion, clic, cambio de personaje,
echo   calibracion de audio y cualquier mensaje o advertencia del sistema.
echo ======================================================================
echo.

python -u main.py

echo.
echo ======================================================================
echo [FIN] La aplicacion ha cerrado (Codigo de salida: %errorlevel%).
echo Presiona cualquier tecla para salir...
echo ======================================================================
pause > nul
