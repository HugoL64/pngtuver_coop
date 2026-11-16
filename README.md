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

