@echo off
chcp 65001 > nul
echo ========================================================
echo        Compilando PNGTuber Duo a UN SOLO ARCHIVO (.exe)
echo ========================================================
echo.
python -m PyInstaller --noconfirm --onefile --windowed --name "PNGTuberCoop" --add-data "assets;assets" --collect-all process_audio_capture --collect-all psutil main.py

echo.
if %errorlevel% equ 0 (
    echo Limpiando archivos temporales...
    if exist build rmdir /s /q build
    copy /y dist\PNGTuberCoop.exe PNGTuberCoop.exe > nul
    echo ========================================================
    echo  ¡Compilacion exitosa!
    echo  El ejecutable final es: PNGTuberCoop.exe
    echo  Solo tienes que mandarle este archivo a tu amigo.
    echo ========================================================
) else (
    echo Error durante la compilacion.
)
pause
