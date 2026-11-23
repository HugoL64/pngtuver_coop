# Especificación del Protocolo Relay — PNGTuber Co-op (v1.3 — Congelada)

Protocolo de señalización de estado, voz numérica y control remoto para hasta **4 jugadores** (`1P` Host + `2P`, `3P`, `4P` Invitados) con topología estricta en estrella:

```text
Host (PC OBS) <── WSS ──> Relay Server <── WSS ──> Guest (2P / 3P / 4P)
```

> **Regla de oro:** El Relay **nunca** reenvía mensajes entre invitados. Tanto el Host como el cliente web tratan al Relay como intermediario no confiable y validan esquemas, tipos y permisos localmente.

---

## 1. Transporte, Orden de Validación y Privacidad

- **Transporte:** Exclusivamente `wss://` (TLS ≥ 1.2). Sin fallback a `ws://`.
- **Frames:** Solo frames de **texto UTF-8** válido (binarios → `1003`). `permessage-deflate` desactivado.
- **Validación de origen:** Invitados requieren `Origin` en allowlist (sin cookies). El Host Python **no** debe enviar `Origin`.
- **Orden determinista de validación en el Relay:**
  `1. Frame texto` → `2. Tamaño máx.` → `3. UTF-8` → `4. JSON (sin NaN/Infinity)` → `5. v` → `6. t` → `7. Origen permitido para t` → `8. Rate limit` → `9. Esquema exacto` → `10. Semántica/KDF`.
- **Timeout de autenticación:** `5 s` tras abrir el socket (`4001`).
- **Heartbeat y Presencia:** El **Relay** inicia `ping` cada `20 s` (timeout `45 s`). En móviles, el cliente usa `Wake Lock API` y puede enviar `presence` (`<= 1 msg/5s`) para indicar segundo plano; en el Host, tras `400 ms` sin `voice`, el slot vuelve a silencio (`0.0`).
- **Privacidad y Logs:** Nunca se registran `IP`, `display_name`, `invite_token`, `session_token`, `host_secret` ni `pin` (el logger los enmascara por defecto).

---

## 2. Identidad, Salas y Credenciales

| Concepto | Quién lo genera | Formato / Entropía | Almacenamiento y Reglas |
|---|---|---|---|
| `room_code` | **Relay** | 8–10 chars Base32 (≥ 40 bits) | En memoria (TTL máx. `12 h`, o `15 min` sin Host) |
| `host_secret` | **Host** | ≥ 128 bits | Solo `SHA-256(host_secret)` (tiempo constante) |
| `invite_token` | **Host** | ≥ 128 bits (en `#` URL) | `invite_token_hash`: **64 hex exactos** (obligatorio al crear sala, opcional al retomar) |
| `pin_kdf` (opcional) | **Host** | `{alg:"scrypt", salt, params:{N,r,p}, hash}` | `N <= 16384` (`2^14`), `r <= 8`, `p <= 1`; tasa limitada **antes** de ejecutar KDF |
| `session_token` | **Relay** | ≥ 128 bits, ligado a `(room, slot)` | TTL `4–6 h`, **rotado al reconectar** con ventana de gracia `60 s` |

- **Ventana de gracia y detección de robo (`session_token`):**
  - Tras rotar en `joined`, el token anterior sigue siendo válido **una sola vez durante `60 s`** (por si la red cae antes de recibir `joined`).
  - Si se presenta el token antiguo **después** de que el nuevo ya se haya usado, el Relay asume posible robo: invalida ambos tokens, cierra el slot (`4006`) y notifica al Host (`guest_left` con `session_reuse_detected: true`).
  - Si dos sockets presentan el mismo `session_token` simultáneamente: gana el primero; el segundo cierra con `4002`.
- **Indistinguibilidad total en `join` (anti-enumeración):**
  - Ante **cualquier** `join` sin `session_token` válido (sala inexistente, Host offline, `invite_token`/PIN inválido, sala llena), el Relay responde **siempre** `join_pending` de inmediato y, si no es válido o expira el lobby (`45 s`), cierra con **`4002`** tras el timeout fijo (sin filtrar estado).
  - Solo si `invite_token` y `pin` son válidos **y** el Host está conectado, el Relay envía `join_request` al Host (con `suggested_slot: null` si la sala está llena).
  - `4003` y `4004` solo se envían a clientes ya autenticados (`session_token` válido).
- **Persistencia en Host:** El Host persiste `room_code` + `host_secret`. Si `auth_host` trae `room_code` existente, verifica `SHA-256(host_secret)` antes de actualizar `invite_token_hash` o reemplazar socket. Si el Host envía un mensaje inválido, se cierra su socket (`1008`) pero la sala persiste `15 min` (`host_offline`).

---

## 3. Límites de Tamaño, Conexiones y Rate Limiting

| Recurso / Dirección | Límite | Acción |
|---|---|---|
| Conexiones **sin autenticar** | Máx. `2` por IP | `429` / `1013` |
| Conexiones **por sala** | Máx. `8` por `(sala, IP)` y **`12` totales** por sala (incl. pendientes) | `1008` / `1013` |
| Creación de salas (`auth_host`) | `5` por IP/hora, `3` activas por IP, tope global | `4007` (cuota) |
| Sobrecarga temporal del servidor | Saturación global | `1013` (backoff + jitter) |
| Lobby (`join_request`) | Máx. `3` pendientes por sala, `1` por IP, timeout `45 s`, cooldown tras rechazo | Descarte / `4002` |
| Reconexión de slot | TTL de gracia `30 s` tras desconexión | Liberación de slot |
| Guest → Relay (`voice`) | Máx. `512 B`, `30 msg/s` | `1009` / `1008` |
| Guest → Relay (`action`) | Máx. `512 B`, `4 msg/s` (ráfaga `3`) + cooldown `300 ms`/acción | `1009` / `1008` / drop |
| Host → Relay (`control`) | Máx. `1 KB`, `5 msg/s` | `E_RATE` / `1008` |
| Host → Relay (`state_sync`) | Máx. `8 KB`, `2 msg/s` por invitado (solo cambios / `state_version`) | Drop / `1008` |
| Host offline | Sin buffering de `voice`/`action` | Descarte silencioso |

---

## 4. Matriz de Origen por Tipo de Mensaje

| Mensaje (`t`) | Solo puede enviarlo |
|---|---|
| `auth_host`, `join_decision`, `permissions`, `kick`, `kick_all`, `rotate_invite`, `state_sync` | **Host autenticado** (otro origen → `1008`) |
| `join`, `voice`, `action`, `presence` | **Guest** (`join` en pendiente/reconexión; resto solo aprobado) |
| `room_created`, `joined`, `join_pending`, `join_request`, `guest_joined`, `guest_left`, `host_offline`, `host_online`, `room_closed`, `error` | **Solo el Relay** |

---

## 5. Esquemas y Ciclo de Vida (`additionalProperties: false`)

- **`auth_host`:** `{v:1, t:"auth_host", host_secret, room_code: null|str, invite_token_hash: 64-hex (obligatorio si room_code==null), pin_kdf?: {alg:"scrypt", salt, params:{N,r,p}, hash}}`
- **`join`:** `{v:1, t:"join", room_code, invite_token, pin?:str, display_name, session_token: null|str}`
- **`join_request` (Relay → Host):** `req_id` (≥16 bytes Base64URL, un solo uso), `display_name` (NFKC, ≤24 chars, sin controles/bidi), `tag` (**estable** durante la sesión, derivado de `HMAC(session_token)` o `req_id`), `suggested_slot: 2|3|4|null`.
- **`join_decision` (Host → Relay):** `req_id` válido de la sala, `allow: bool`, `slot ∈ {2,3,4}` libre, `permissions` booleanos.
- **Cancelación de pendientes:** `kick_all`, `rotate_invite` y caída del Host (`host_offline`) cancelan todos los `join_request` pendientes cerrándolos con `4002`.
- **`rotate_invite`:** `{v:1, t:"rotate_invite", invite_token_hash: 64-hex}`. Revoca `invite_token` anterior y cancela pendientes; mantiene conectados salvo `kick_all`.
- **`kick`:** `{v:1, t:"kick", slot: 2|3|4, ban: bool}` (`4006`). Si `ban: true`, revoca `invite_token` y el `session_token` (el nombre es solo informativo, no bloqueo real).
- **`presence` (Guest → Relay → Host):** `{v:1, t:"presence", seq, foreground: bool}` (`<= 1 msg/5s`).
- **`guest_left` (Relay → Host):** `{v:1, t:"guest_left", slot: 2|3|4, session_reuse_detected?: bool}` → el Host fuerza voz `0.0` e inactiva el slot.
- **`voice` / `action` / `state_sync` / `seq`:** `seq` monótono estrictamente creciente (`0 <= seq < 2^31`), sin toggles (`enabled: bool`), `id` entero en `set_prop`/`set_emotion`/`set_character`, `to == state.slot` y etiquetas normalizadas NFKC sin bidi en `state_sync`. Los permisos del Host son la única autoridad (`GuestCommand`, *default-deny*).
- **`error` (Relay → Cliente):** `{v:1, t:"error", code: "E_SCHEMA"|"E_RATE"|"E_FORBIDDEN"|"E_SLOT"}` (informativo; en `E_FORBIDDEN` el cliente no reintenta automáticamente).

---

## 6. Códigos de Cierre WebSocket

| Código | Quién lo recibe | Significado |
|---|---|---|
| `1003` | cualquiera | Frame binario o UTF-8 inválido |
| `1008` | cualquiera | Esquema inválido, origen de mensaje inválido, acción prohibida o rate limit |
| `1009` | cualquiera | Mensaje excede tamaño máximo (`512 B` / `1 KB` / `8 KB`) |
| `1013` | cualquiera | Sobrecarga temporal del servidor (aplicar backoff + jitter) |
| `4001` | cualquiera | Timeout de autenticación inicial (`> 5 s`) |
| `4002` | **no autenticado** | Fallo genérico uniforme (sala/token/PIN inválido, Host offline, rechazo o timeout lobby) |
| `4003` | autenticado | Sala expirada o cerrada por el Host |
| `4004` | autenticado | Slot ocupado o sala llena |
| `4005` | autenticado | Reemplazado por una conexión más reciente del mismo slot (`session_token`) |
| `4006` | autenticado | Expulsado (`kick`) o baneado (`ban`) por el Host |
| `4007` | Host | Cuota de creación de salas excedida |
| `4008` | cualquiera | Versión de protocolo (`v`) no soportada — actualizar cliente |
