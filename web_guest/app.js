"use strict";

(() => {
  // URL del Relay (mismo origen en producción/túnel o localhost)
  const RELAY_WS_URL = (() => {
    const host = window.location.host;
    if (window.location.protocol === "https:") {
      return `wss://${host}/ws`;
    }
    if (window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost") {
      if (window.location.port === "8000") {
        return "ws://127.0.0.1:8766";
      }
      return `ws://${host}/ws`;
    }
    return `wss://${host}/ws`;
  })();

  const PROTOCOL_VERSION = 1;
  const VOICE_INTERVAL_MS = 50; // 20 Hz
  const ACTION_COOLDOWN_MS = 300;
  const MAX_CATALOG_ITEMS = 64;
  const MAX_LABEL_LEN = 40;

  // Eliminación de controles y marcas bidireccionales (U+202A..202E, U+2066..2069, etc.)
  const BIDI_RE = /[\u0000-\u001F\u007F\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/g;

  function sanitizeLabel(raw, maxLen = MAX_LABEL_LEN) {
    if (typeof raw !== "string") return "";
    const norm = raw.normalize("NFKC").replace(BIDI_RE, "").trim();
    return norm.slice(0, maxLen).trim();
  }

  // Estado local en memoria (sin prototypes mutables)
  let ws = null;
  let seq = 0;
  let mySlot = null;
  let lastStateVersion = -1;
  let lastActionAt = 0;
  let reconnectAttempts = 0;
  let reconnectTimer = null;
  let intentionalClose = false;
  let lastJoinParams = null;

  // Audio local (solo nivel numérico RMS)
  let audioCtx = null;
  let micStream = null;
  let analyser = null;
  let voiceTimer = null;
  let sentSilence = true;
  let wakeLock = null;
  let lastPresenceAt = 0;

  let currentState = {
    active_character_id: 0,
    characters: [],
    active_emotion: 1,
    emotions: [],
    props: [],
    flip_x: false,
    screaming: false,
    permissions: Object.create(null),
  };

  // Referencias DOM
  const $ = (id) => document.getElementById(id);
  const statusText = $("statusText");
  const slotBadge = $("slotBadge");
  const alertBanner = $("alertBanner");
  const joinView = $("joinView");
  const pendingView = $("pendingView");
  const controlView = $("controlView");

  const roomInput = $("roomInput");
  const inviteInput = $("inviteInput");
  const pinInput = $("pinInput");
  const nameInput = $("nameInput");
  const joinBtn = $("joinBtn");
  const cancelPendingBtn = $("cancelPendingBtn");
  const leaveBtn = $("leaveBtn");

  const micBtn = $("micBtn");
  const micMeter = $("micMeter");
  const micStatus = $("micStatus");

  const emotionsGrid = $("emotionsGrid");
  const propsGrid = $("propsGrid");
  const charsCard = $("charsCard");
  const charsGrid = $("charsGrid");
  const flipBtn = $("flipBtn");
  const screamBtn = $("screamBtn");

  function setStatus(text) {
    statusText.textContent = text;
  }

  function showBanner(text) {
    if (!text) {
      alertBanner.classList.add("hidden");
      alertBanner.textContent = "";
      return;
    }
    alertBanner.textContent = text;
    alertBanner.classList.remove("hidden");
  }

  function showView(viewName) {
    joinView.classList.toggle("hidden", viewName !== "join");
    pendingView.classList.toggle("hidden", viewName !== "pending");
    controlView.classList.toggle("hidden", viewName !== "control");
  }

  function nextSeq() {
    seq += 1;
    return seq;
  }

  function readFragmentSecrets() {
    const hash = window.location.hash || "";
    if (!hash.startsWith("#")) return;
    const params = new URLSearchParams(hash.slice(1));
    const room = params.get("room");
    const invite = params.get("invite");
    if (room) roomInput.value = sanitizeLabel(room, 16);
    if (invite) inviteInput.value = invite.slice(0, 128);
    // Limpiar secretos de la URL inmediatamente
    try {
      window.history.replaceState(null, "", window.location.pathname);
    } catch (_) {}
  }

  function getSessionToken() {
    try {
      return window.sessionStorage.getItem("coop_session_token");
    } catch (_) {
      return null;
    }
  }

  function setSessionToken(tok) {
    try {
      if (tok) window.sessionStorage.setItem("coop_session_token", String(tok));
      else window.sessionStorage.removeItem("coop_session_token");
    } catch (_) {}
  }

  function sendJson(obj) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(obj));
    return true;
  }

  function sendAction(action, extra) {
    const now = Date.now();
    if (now - lastActionAt < ACTION_COOLDOWN_MS) return;
    lastActionAt = now;
    const payload = { v: PROTOCOL_VERSION, t: "action", seq: nextSeq(), action };
    if (extra && typeof extra.id === "number") payload.id = extra.id;
    if (extra && typeof extra.enabled === "boolean") payload.enabled = extra.enabled;
    sendJson(payload);
  }

  function validateCatalog(rawList, withEnabled) {
    if (!Array.isArray(rawList)) return [];
    const seen = new Set();
    const out = [];
    for (let i = 0; i < rawList.length && out.length < MAX_CATALOG_ITEMS; i++) {
      const item = rawList[i];
      if (!item || typeof item !== "object") continue;
      if (typeof item.id !== "number" || !Number.isInteger(item.id) || item.id < 0) continue;
      if (seen.has(item.id)) continue;
      const name = sanitizeLabel(item.name, MAX_LABEL_LEN);
      if (!name) continue;
      seen.add(item.id);
      const entry = { id: item.id, name };
      if (withEnabled) entry.enabled = Boolean(item.enabled);
      out.push(entry);
    }
    return out;
  }

  function renderControls() {
    const perms = currentState.permissions;

    // Emociones (solo createElement + textContent, cero innerHTML)
    emotionsGrid.replaceChildren();
    for (const em of currentState.emotions) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn" + (em.id === currentState.active_emotion ? " active" : "");
      btn.textContent = em.name;
      btn.disabled = !perms.emotion;
      btn.addEventListener("click", () => sendAction("set_emotion", { id: em.id }));
      emotionsGrid.appendChild(btn);
    }

    // Props (estado absoluto, nunca toggle null)
    propsGrid.replaceChildren();
    for (const pr of currentState.props) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn" + (pr.enabled ? " active" : "");
      btn.textContent = pr.name;
      btn.disabled = !perms.prop;
      btn.addEventListener("click", () => sendAction("set_prop", { id: pr.id, enabled: !pr.enabled }));
      propsGrid.appendChild(btn);
    }

    flipBtn.classList.toggle("active", Boolean(currentState.flip_x));
    flipBtn.disabled = !perms.flip_x;

    screamBtn.classList.toggle("active", Boolean(currentState.screaming));
    screamBtn.disabled = !perms.scream;

    // Personajes (solo si está permitido)
    charsCard.classList.toggle("hidden", !perms.character || currentState.characters.length === 0);
    charsGrid.replaceChildren();
    if (perms.character) {
      for (const ch of currentState.characters) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn" + (ch.id === currentState.active_character_id ? " active" : "");
        btn.textContent = ch.name;
        btn.addEventListener("click", () => sendAction("set_character", { id: ch.id }));
        charsGrid.appendChild(btn);
      }
    }
  }

  function applyStateSync(msg) {
    if (typeof msg.state_version !== "number" || msg.state_version <= lastStateVersion) return;
    const st = msg.state;
    if (!st || typeof st !== "object" || st.slot !== mySlot) return;
    lastStateVersion = msg.state_version;

    const perms = Object.create(null);
    if (st.permissions && typeof st.permissions === "object") {
      perms.emotion = Boolean(st.permissions.emotion);
      perms.prop = Boolean(st.permissions.prop);
      perms.flip_x = Boolean(st.permissions.flip_x);
      perms.scream = Boolean(st.permissions.scream);
      perms.character = Boolean(st.permissions.character);
    }

    currentState = {
      active_character_id: Number.isInteger(st.active_character_id) ? st.active_character_id : 0,
      characters: validateCatalog(st.characters, false),
      active_emotion: Number.isInteger(st.active_emotion) ? st.active_emotion : 1,
      emotions: validateCatalog(st.emotions, false),
      props: validateCatalog(st.props, true),
      flip_x: Boolean(st.flip_x),
      screaming: Boolean(st.screaming),
      permissions: perms,
    };
    renderControls();
  }

  function connect(params, isReconnect = false) {
    intentionalClose = false;
    lastJoinParams = params;
    seq = 0;

    console.debug("[GUEST] Conectando a", RELAY_WS_URL);
    try {
      ws = new WebSocket(RELAY_WS_URL);
    } catch (err) {
      console.error("[GUEST] Error creando WebSocket:", err);
      setStatus("No se pudo conectar al Relay");
      return;
    }

    setStatus(isReconnect ? "Reconectando..." : "Conectando...");

    ws.addEventListener("open", () => {
      reconnectAttempts = 0;
      console.debug("[GUEST] WS abierto, enviando join", {
        room_code: params.room_code,
        display_name: params.display_name,
        has_session: Boolean(getSessionToken()),
      });
      const joinMsg = {
        v: PROTOCOL_VERSION,
        t: "join",
        room_code: params.room_code,
        invite_token: params.invite_token,
        display_name: params.display_name,
        session_token: getSessionToken(),
      };
      if (params.pin) joinMsg.pin = params.pin;
      sendJson(joinMsg);
    });

    ws.addEventListener("message", (ev) => {
      if (typeof ev.data !== "string" || ev.data.length > 16384) return;
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (_) {
        return;
      }
      if (!msg || typeof msg !== "object") return;
      console.debug("[GUEST] WS <-", msg.t, msg.code || msg.slot || "");

      if (msg.t === "join_pending") {
        showBanner("");
        setStatus("Esperando aprobación...");
        showView("pending");
      } else if (msg.t === "joined") {
        mySlot = msg.slot;
        setSessionToken(msg.session_token);
        slotBadge.textContent = "Jugador " + String(mySlot) + "P";
        slotBadge.classList.remove("hidden");
        setStatus("Conectado");
        showBanner("");
        showView("control");
        requestWakeLock();
      } else if (msg.t === "state_sync") {
        applyStateSync(msg);
      } else if (msg.t === "permissions" && msg.permissions) {
        currentState.permissions = {
          emotion: Boolean(msg.permissions.emotion),
          prop: Boolean(msg.permissions.prop),
          flip_x: Boolean(msg.permissions.flip_x),
          scream: Boolean(msg.permissions.scream),
          character: Boolean(msg.permissions.character),
        };
        renderControls();
      } else if (msg.t === "host_offline") {
        showBanner("El streamer perdió conexión temporalmente. Esperando reconexión...");
      } else if (msg.t === "host_online") {
        showBanner("");
      } else if (msg.t === "error") {
        if (msg.code === "E_FORBIDDEN") {
          showBanner("Acción no permitida por el streamer.");
        } else if (msg.code === "E_RATE") {
          showBanner("Vas muy rápido, espera un momento.");
        }
      }
    });

    ws.addEventListener("error", (ev) => {
      console.error("[GUEST] WS error:", ev);
    });

    ws.addEventListener("close", (ev) => {
      console.debug("[GUEST] WS cerrado:", { code: ev.code, reason: ev.reason, intentional: intentionalClose });
      ws = null;
      if (intentionalClose) {
        setStatus("Desconectado");
        return;
      }
      if (ev.code === 4008) {
        showBanner("Versión desactualizada. Actualiza la página.");
        stopMic();
        showView("join");
        return;
      }
      if (ev.code === 4002 || ev.code === 4003 || ev.code === 4006) {
        setSessionToken(null);
        mySlot = null;
        slotBadge.classList.add("hidden");
        stopMic();
        showBanner("Sesión cerrada o no autorizada (" + String(ev.code) + ").");
        setStatus("Desconectado");
        showView("join");
        return;
      }
      // Reconexión con backoff + jitter en caídas de red o 1013
      const base = Math.min(15000, 1000 * Math.pow(2, reconnectAttempts));
      const delay = base + Math.floor(Math.random() * 500);
      reconnectAttempts += 1;
      setStatus("Reconectando en " + Math.ceil(delay / 1000) + "s...");
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(() => {
        if (lastJoinParams) connect(lastJoinParams, true);
      }, delay);
    });
  }

  // Web Audio API: solo nivel numérico RMS (nunca conectado a destination)
  async function startMic() {
    if (micStream) {
      stopMic();
      return;
    }
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const src = audioCtx.createMediaStreamSource(micStream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser); // NO conectar a audioCtx.destination

      const buf = new Uint8Array(analyser.fftSize);
      micBtn.textContent = "Apagar Micrófono";
      micBtn.classList.add("active");
      micStatus.textContent = "Micrófono activo (solo enviando nivel 0–100)";
      sentSilence = false;

      voiceTimer = setInterval(() => {
        if (!analyser) return;
        analyser.getByteTimeDomainData(buf);
        let sumSq = 0;
        for (let i = 0; i < buf.length; i++) {
          const norm = (buf[i] - 128) / 128;
          sumSq += norm * norm;
        }
        const rms = Math.sqrt(sumSq / buf.length);
        const level = Math.min(100, Math.round(rms * 250 * 10) / 10);
        micMeter.style.width = String(level) + "%";

        if (level < 1.5) {
          if (!sentSilence) {
            sendJson({ v: PROTOCOL_VERSION, t: "voice", seq: nextSeq(), level: 0.0 });
            sentSilence = true;
          }
        } else {
          sentSilence = false;
          sendJson({ v: PROTOCOL_VERSION, t: "voice", seq: nextSeq(), level });
        }
      }, VOICE_INTERVAL_MS);
    } catch (_) {
      showBanner("No se pudo acceder al micrófono. Revisa los permisos del navegador.");
      stopMic();
    }
  }

  function stopMic() {
    clearInterval(voiceTimer);
    voiceTimer = null;
    if (micStream) {
      for (const track of micStream.getTracks()) track.stop();
      micStream = null;
    }
    if (audioCtx) {
      audioCtx.close().catch(() => {});
      audioCtx = null;
    }
    analyser = null;
    micMeter.style.width = "0%";
    micBtn.textContent = "Activar Micrófono";
    micBtn.classList.remove("active");
    micStatus.textContent = "Micrófono apagado";
    if (ws && ws.readyState === WebSocket.OPEN) {
      sendJson({ v: PROTOCOL_VERSION, t: "voice", seq: nextSeq(), level: 0.0 });
    }
  }

  async function requestWakeLock() {
    if (!("wakeLock" in navigator)) return;
    try {
      wakeLock = await navigator.wakeLock.request("screen");
    } catch (_) {}
  }

  document.addEventListener("visibilitychange", () => {
    const fg = !document.hidden;
    if (fg && mySlot !== null) requestWakeLock();
    const now = Date.now();
    if (ws && ws.readyState === WebSocket.OPEN && mySlot !== null && now - lastPresenceAt > 4000) {
      lastPresenceAt = now;
      sendJson({ v: PROTOCOL_VERSION, t: "presence", seq: nextSeq(), foreground: fg });
    }
    if (!fg && micStream) {
      showBanner("Pestaña en segundo plano: el navegador puede pausar el micrófono.");
    }
  });

  window.addEventListener("beforeunload", () => {
    intentionalClose = true;
    stopMic();
    if (wakeLock) wakeLock.release().catch(() => {});
    if (ws) ws.close(1000, "Saliendo");
  });

  // Eventos de UI
  joinBtn.addEventListener("click", () => {
    const room_code = sanitizeLabel(roomInput.value, 16).toUpperCase();
    const invite_token = inviteInput.value.trim();
    const pin = pinInput.value.trim();
    const display_name = sanitizeLabel(nameInput.value, 24) || "Invitado";
    if (!room_code || !invite_token) {
      showBanner("Ingresa el código de sala y el token de invitación.");
      return;
    }
    connect({ room_code, invite_token, pin, display_name }, false);
  });

  function disconnectAll() {
    intentionalClose = true;
    clearTimeout(reconnectTimer);
    stopMic();
    setSessionToken(null);
    mySlot = null;
    slotBadge.classList.add("hidden");
    if (ws) ws.close(1000, "Salida manual");
    showView("join");
  }

  cancelPendingBtn.addEventListener("click", disconnectAll);
  leaveBtn.addEventListener("click", disconnectAll);
  micBtn.addEventListener("click", startMic);

  flipBtn.addEventListener("click", () => {
    sendAction("flip_x", { enabled: !currentState.flip_x });
  });

  screamBtn.addEventListener("click", () => {
    sendAction("scream", { enabled: !currentState.screaming });
  });

  readFragmentSecrets();
})();
