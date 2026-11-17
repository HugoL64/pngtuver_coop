# PNGTuber Duo / Coop (Micrófono + Discord)

Proyecto listo para usar con **2 avatares PNGtuber en dos ventanas independientes de croma verde** para OBS Studio.
- **Avatar 1**: Reacciona a tu micrófono al hablar.
- **Avatar 2**: Reacciona al audio de Discord (usando captura de altavoces/auriculares vía WASAPI Loopback, **sin necesidad de instalar cables virtuales**).

---

## 📁 Estructura del Proyecto

- **`dist/PNGTuberCoop/`**: Carpeta con el ejecutable listo para enviar a un amigo (`PNGTuberCoop.exe`). Solo tienen que abrirlo y funciona sin instalar nada.
- **`main.py`**: Código fuente de la interfaz gráfica principal.
- **`audio_engine.py`**: Motor de captura de audio dual en tiempo real.
- **`avatar_window.py`**: Ventanas de renderizado de avatares con croma y animación de rebote.
- **`assets/`**: Imágenes por defecto de avatares (Gatito azul y Osito naranja).
- **`iniciar.bat`**: Script para ejecutar el proyecto en Python con un doble clic.
- **`iniciar_debug.bat`**: Script para ejecutar el proyecto con **consola de debug visible en tiempo real**, mostrando cada clic, acción, calibración y registro con marca de tiempo.
- **`build_exe.bat`**: Script para recompilar el ejecutable `.exe` con PyInstaller.
- **`GUIA_OBS.md`**: Guía paso a paso para configurar las fuentes y filtros de Croma en OBS Studio.

---

## ⚡ Inicio Rápido

1. Ejecuta **`iniciar_debug.bat`** (si deseas ver la consola de depuración con el registro de acciones) o **`iniciar.bat`**.
2. **Interfaz Retro Co-op**:
   - **Avatar en Grande y Navegación con Flechas (◀ Nombre ▶)**:
     - El personaje seleccionado se muestra en **tamaño grande (220x220)** animado en vivo (habla, pestañea y grita en tiempo real).
     - Arriba de cada avatar se ubica su nombre con **flechas triangulares (`◀` y `▶`)** para cambiar de personaje al instante con un solo clic.
     - Botón `[ ➕ ]` para crear nuevos personajes fácilmente.
   - **Botón Grande con Engrane `[ ⚙️ EDITAR IMÁGENES Y POSES ]`**:
     - Al hacer clic, te lleva a un menú con **tarjetas visuales** de cada pose (Quieto, Pestañeo, Hablando, Hablando pestañeo, Grito).
     - Al dar clic en cualquier tarjeta puedes seleccionar una nueva imagen desde tu explorador de archivos.
     - Botón `[ ◀ VOLVER A LA SELECCIÓN ]` para regresar inmediatamente a la pantalla anterior.
   - **Tarjeta Jugador 2 (Discord)**:
     - **Desactivado por defecto**: Se muestra como un recuadro interactivo que te invita a hacer clic para activarlo cuando quieras transmitir en Co-op con un amigo.
     - Al activarse, muestra su propio avatar en grande, selector con flechas `[ ◀ ] [ ▶ ]` y botón de poses.
   - **Autoguardado 100% automático**: Cualquier cambio queda guardado al instante en disco.
3. Haz clic en **"🚀 ENVIAR A OBS (Abrir Avatares)"**.
4. En OBS, añade dos fuentes de **Captura de ventana** y aplica el filtro **Fondo croma (Verde)**.

---

## A Gift for the Community

This project is a gift from **HugoL64** to the creator and streamer community. Feel free to use it, enjoy it on your streams, and share it with your friends for free.

## Project License

This project uses a **dual license** to protect both the code and the artwork while keeping its free, community-driven spirit:

### Source Code — GNU GPLv3
* All source code in this program (`.py`, `.bat`, `.spec`, and scripts) is licensed under the **GNU General Public License v3.0 (GPLv3)**.
* **Cannot be privatized:** You are free to use, modify, and improve the code, but **any modified or derivative version you distribute must remain open-source and free under the same GPLv3 license**. It cannot be closed-source or turned into proprietary software.

### Visual Assets and Artwork (`/assets` and `/personajes`) — CC BY-NC-SA 4.0
* All sprites, illustrations, poses, props, and visual elements located in the `/assets` and `/personajes` folders are licensed under **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)**, with the following clarifications:
  * **Permitted use:** You may freely use them in your livestreams (Twitch, YouTube, Kick, etc.) and videos, modify them for personal use, and **share or gift them for free** within the community with proper attribution.
  * **No selling (Non-Commercial):** Selling, reselling, charging for these files, or including them in paid products or physical/digital merchandise is prohibited.
  * **AI restriction (applies to artwork only):** This restriction applies exclusively to the visual assets and not to the source code. Using this artwork to train Artificial Intelligence models, or using generative AI on it to alter it, create variations, or attempt to bypass this license for commercial purposes, is prohibited. Any derivative work based on this artwork automatically inherits the **Non-Commercial (NC)** and **ShareAlike (SA)** conditions.

