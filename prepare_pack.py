import os
import shutil
import zipfile

def main():
    base_dir = r"d:\Progra\hobie\vtuber coop"
    dest_dir = os.path.join(base_dir, "PNGTuber Duo - Pack Compartir")
    zip_path = os.path.join(base_dir, "PNGTuber_Duo_Pack_Compartir.zip")

    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir, ignore_errors=True)
    os.makedirs(dest_dir, exist_ok=True)

    # 1. Copiar PNGTuberCoop.exe
    exe_src = os.path.join(base_dir, "PNGTuberCoop.exe")
    if os.path.exists(exe_src):
        shutil.copy2(exe_src, os.path.join(dest_dir, "PNGTuberCoop.exe"))
        print("[OK] Copiado PNGTuberCoop.exe")

    # 2. Copiar carpeta de personajes
    chars_src = os.path.join(base_dir, "personajes")
    if os.path.exists(chars_src):
        shutil.copytree(chars_src, os.path.join(dest_dir, "personajes"))
        print("[OK] Copiada carpeta de personajes")

    # 3. Copiar assets
    assets_src = os.path.join(base_dir, "assets")
    if os.path.exists(assets_src):
        shutil.copytree(assets_src, os.path.join(dest_dir, "assets"))
        print("[OK] Copiada carpeta de assets")

    # 4. Copiar GUIA_OBS.md
    obs_guide = os.path.join(base_dir, "GUIA_OBS.md")
    if os.path.exists(obs_guide):
        shutil.copy2(obs_guide, os.path.join(dest_dir, "GUIA_OBS.md"))

    # 5. Escribir LEEME_INICIO_RAPIDO.txt
    readme_text = """====================================================================
           PNGTuber Duo / Coop - Guía de Inicio Rápido
====================================================================

¡Gracias por usar PNGTuber Duo! Este programa te permite tener avatares
reactivos de voz para tus directos o llamadas en Discord.

--------------------------------------------------------------------
1. ¿QUÉ NECESITO PARA EJECUTARLO?
--------------------------------------------------------------------
¡Absolutamente nada! El programa es 100% portable y autónomo:
- NO necesitas instalar Python ni nada adicional.
- NO necesitas instalar dependencias ni abrir terminales.
- Solo haz DOBLE CLIC sobre el archivo:  PNGTuberCoop.exe

--------------------------------------------------------------------
2. PASOS RÁPIDOS PARA EMPEZAR
--------------------------------------------------------------------
1. Abre 'PNGTuberCoop.exe'.
2. Selecciona tu personaje haciendo clic en su tarjeta o en 'Cambiar'.
3. Abajo en la tarjeta, selecciona tu micrófono (o 'Predeterminado').
4. Haz clic en el botón '🪄 Auto (3s)' y habla normalmente durante
   3 segundos: el programa ajustará automáticamente tu sensibilidad de voz.
5. Haz clic en el botón grande verde abajo:
   '🚀 ENVIAR A OBS (Abrir Avatares)'

--------------------------------------------------------------------
3. CÓMO PONER EL FONDO TRANSPARENTE EN OBS STUDIO
--------------------------------------------------------------------
1. En OBS, ve a tu Escena -> Fuentes -> pulsa '+' -> 'Captura de ventana'.
2. En la lista desplegable, elige la ventana del avatar (ej: 'OBS Avatar - 1P').
3. Haz clic derecho sobre esa fuente en OBS -> Filtros -> '+' -> 'Filtro de Clave de Color' (Color Key).
4. Elige el color del fondo (Magenta #FF00FF o Verde #00FF00).
5. ¡Listo! Tu avatar se verá 100% transparente y reaccionará a tu voz en directo.

--------------------------------------------------------------------
4. AGREGAR TUS PROPIOS PERSONAJES Y ACCESORIOS (PROPS / ELEMENTOS)
--------------------------------------------------------------------
- Puedes crear nuevos personajes usando el botón '+ Nuevo' o abrir su carpeta con '📁 Carpeta'.
- Puedes añadir accesorios interactivos (manos con mandos, gorros, escritorios, gafas, etc.)
  haciendo clic en el botón 'Elementos'.

¡Disfruta tus transmisiones y partidas cooperativas!
"""
    readme_path = os.path.join(dest_dir, "LEEME_INICIO_RAPIDO.txt")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_text)
    print("[OK] Creado LEEME_INICIO_RAPIDO.txt")

    # 6. Crear archivo .ZIP
    if os.path.exists(zip_path):
        os.remove(zip_path)

    print("[...] Comprimiendo archivo ZIP...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(dest_dir):
            for file in files:
                full_p = os.path.join(root, file)
                rel_p = os.path.relpath(full_p, dest_dir)
                zipf.write(full_p, rel_p)

    zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"[EXITO] ZIP creado: {zip_path} ({zip_size_mb:.2f} MB)")

if __name__ == "__main__":
    main()

