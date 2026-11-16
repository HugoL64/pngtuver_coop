# Guía Definitiva: PNGTuber Duo / Coop en OBS Studio

Esta aplicación permite tener avatares PNGtuber reactivos en ventanas independientes con fondo de croma para OBS Studio, compatible con modo solitario o en pareja con amigos de Discord.

---

## 🎮 1. Modo de Juego: Single Player vs Co-op

En la parte superior derecha de la aplicación puedes alternar entre dos modos:
- **👥 Modo Co-op (2 Jugadores)**:
  - Activa ambos avatares: Jugador 1 (Tú) y Jugador 2 (Tu amigo de Discord).
  - Al abrir ventanas, se abren las dos pantallas para OBS.
- **👤 Modo Single Player (Campaña en Solitario)**:
  - Solo tú con tu micrófono.
  - Desactiva el Avatar 2 para ahorrar pantalla, memoria y procesador en tu PC mientras juegas solo.

---

## 📁 2. Perfiles 100% Independientes (Jugador 1 y Jugador 2)

Cada jugador tiene ahora **su propia barra de gestión de perfiles**:
- **Columna 1 (Jugador 1 / Tú)**:
  - Guarda tus skins, micrófonos y sensibilidad propios (ej. *"Gatito Azul"*, *"Skin Halloween"*, *"Avatar Formal"*).
  - Botones dedicados: `➕ Nuevo`, `💾 Guardar`, `🗑️ Borrar`.
- **Columna 2 (Jugador 2 / Discord)**:
  - Guarda los perfiles de tus diferentes amigos de Discord por separado (ej. *"Carlos"*, *"Ana"*, *"Osito Default"*, *"Discord General"*).
  - Botones dedicados: `➕ Nuevo`, `💾 Guardar`, `🗑️ Borrar`.
- **¿Qué ventaja tiene?** Puedes cambiar de amigo en Discord (eligiendo *"Carlos"*) sin que se modifique tu propio avatar, o cambiarte de ropa/skin tú mismo sin alterar el avatar de tu compañero.

---

## ✨ 3. Modos de Imágenes Independientes

Cada jugador puede tener su propio modo de imágenes:
- **⚡ Modo Simple (2 imágenes)**: Solo 2 imágenes exactas (*Quieto boca cerrada* y *Hablando boca abierta*).
- **✨ Modo Pro (4 imágenes + Parpadeo + Grito)**:
  - 4 estados de parpadeo natural (ojos abiertos/cerrados).
  - Casilla para expresión de **Grito / Susto** (activable con la `Tecla 2`).
- *(Ejemplo: Puedes usar el Modo Pro de 4 imágenes para ti, mientras tu amigo en Discord usa el Modo Simple de 2 imágenes si solo te pasó dos dibujos rápidos).*

---

## 🎧 4. Puerta de Ruido con Histéresis Inteligente

En los medidores de volumen notarás dos indicadores:
1. **Línea Rosa (Umbral de apertura)**: El nivel de volumen que tu voz debe superar para abrir la boca.
2. **Línea Cyan Punteada (Umbral de cierre con histéresis - 70%)**: El nivel al que debe descender tu voz para cerrarla.
- **¿Qué ventaja tiene?** Evita que la respiración, el tecleo de fondo o las pausas entre sílabas hagan parpadear la boca de forma desagradable.

---

## 🎥 5. Configuración en OBS Studio

1. Haz clic en **"🚀 Abrir Ventanas (OBS)"**.
2. En OBS Studio, añade una fuente **Captura de ventana** para cada avatar.
3. Clic derecho en la fuente -> **Filtros** -> `+` -> **Fondo croma (Chroma Key)** -> Color: **Verde**.
4. ¡Listo! Muévelos libremente por la pantalla de tu transmisión o grabación.
