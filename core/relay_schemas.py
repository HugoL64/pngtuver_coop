"""Esquemas y validadores estrictos compartidos para el protocolo Relay v1.2.

Tanto el Host (GuestInbox / GuestCommand) como el servidor Relay usan estas reglas
(`additionalProperties: false`, rechazo de NaN/Infinity, bool != int, NFKC y sin bidi).
"""

import json
import math
import re
import unicodedata

PROTOCOL_VERSION = 1
MAX_SEQ = (1 << 31) - 1
VALID_SLOTS = (2, 3, 4)
PERMISSION_KEYS = ("emotion", "prop", "flip_x", "scream", "character")
GUEST_ACTIONS = ("set_emotion", "set_prop", "flip_x", "scream", "set_character")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_SCRYPT_N = 16384  # 2^14
MAX_SCRYPT_R = 8
MAX_SCRYPT_P = 1

# Caracteres bidireccionales peligrosos para spoofing visual
_BIDI_CODEPOINTS = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A)) | {0x200E, 0x200F, 0x061C}


class SchemaError(ValueError):
    """Error de validación de esquema del protocolo."""

    def __init__(self, message, close_code=1008, app_code="E_SCHEMA"):
        super().__init__(message)
        self.close_code = close_code
        self.app_code = app_code


def _reject_constant(val):
    raise SchemaError(f"Constante JSON prohibida: {val}")


def parse_json_strict(raw, max_bytes):
    """Decodifica UTF-8 + JSON rechazando tamaños excesivos y NaN/Infinity."""
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > max_bytes:
            raise SchemaError("Mensaje demasiado grande", close_code=1009, app_code="E_SIZE")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SchemaError("UTF-8 inválido", close_code=1003, app_code="E_ENCODING") from exc
    elif isinstance(raw, str):
        encoded = raw.encode("utf-8", errors="strict")
        if len(encoded) > max_bytes:
            raise SchemaError("Mensaje demasiado grande", close_code=1009, app_code="E_SIZE")
        text = raw
    else:
        raise SchemaError("Frame debe ser texto", close_code=1003, app_code="E_FRAME")

    try:
        obj = json.loads(text, parse_constant=_reject_constant)
    except SchemaError:
        raise
    except Exception as exc:
        raise SchemaError("JSON inválido") from exc

    if not isinstance(obj, dict):
        raise SchemaError("El mensaje raíz debe ser un objeto JSON")
    return obj


def _require_exact_keys(obj, required, optional=()):
    allowed = set(required) | set(optional)
    keys = set(obj.keys())
    missing = set(required) - keys
    if missing:
        raise SchemaError(f"Faltan campos obligatorios: {sorted(missing)}")
    extra = keys - allowed
    if extra:
        raise SchemaError(f"Campos no permitidos: {sorted(extra)}")


def _require_int(val, min_val=None, max_val=None, name="int"):
    if isinstance(val, bool) or not isinstance(val, int):
        raise SchemaError(f"{name} debe ser entero")
    if min_val is not None and val < min_val:
        raise SchemaError(f"{name} fuera de rango (< {min_val})")
    if max_val is not None and val > max_val:
        raise SchemaError(f"{name} fuera de rango (> {max_val})")
    return val


def _require_bool(val, name="bool"):
    if not isinstance(val, bool):
        raise SchemaError(f"{name} debe ser booleano")
    return val


def _require_finite_float(val, min_val=0.0, max_val=100.0, name="float"):
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise SchemaError(f"{name} debe ser numérico")
    num = float(val)
    if not math.isfinite(num):
        raise SchemaError(f"{name} no finito")
    if num < min_val or num > max_val:
        raise SchemaError(f"{name} fuera de rango [{min_val}, {max_val}]")
    return num


def sanitize_label(raw, max_len=40, allow_empty=False):
    """Normaliza NFKC y elimina controles y marcas bidireccionales."""
    if not isinstance(raw, str):
        raise SchemaError("Etiqueta debe ser texto")
    norm = unicodedata.normalize("NFKC", raw)
    cleaned = "".join(
        ch for ch in norm
        if ord(ch) >= 0x20 and ord(ch) != 0x7F and ord(ch) not in _BIDI_CODEPOINTS
    ).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].strip()
    if not allow_empty and not cleaned:
        raise SchemaError("Etiqueta vacía tras sanitizar")
    return cleaned


def validate_permissions(obj):
    if not isinstance(obj, dict):
        raise SchemaError("permissions debe ser objeto")
    _require_exact_keys(obj, PERMISSION_KEYS)
    return {k: _require_bool(obj[k], name=f"permissions.{k}") for k in PERMISSION_KEYS}


def validate_guest_voice(msg):
    """Valida mensaje `voice` del invitado y devuelve copia limpia."""
    _require_exact_keys(msg, ("v", "t", "seq", "level"))
    v = _require_int(msg["v"], name="v")
    if v != PROTOCOL_VERSION:
        raise SchemaError("Versión no soportada", close_code=4008, app_code="E_VERSION")
    if msg["t"] != "voice":
        raise SchemaError("Tipo inválido")
    seq = _require_int(msg["seq"], 0, MAX_SEQ, name="seq")
    level = _require_finite_float(msg["level"], 0.0, 100.0, name="level")
    return {"v": PROTOCOL_VERSION, "t": "voice", "seq": seq, "level": level}


def validate_guest_action(msg):
    """Valida mensaje `action` del invitado (additionalProperties: false) y devuelve copia limpia."""
    if not isinstance(msg, dict):
        raise SchemaError("Mensaje inválido")
    v = _require_int(msg.get("v"), name="v")
    if v != PROTOCOL_VERSION:
        raise SchemaError("Versión no soportada", close_code=4008, app_code="E_VERSION")
    if msg.get("t") != "action":
        raise SchemaError("Tipo inválido")
    seq = _require_int(msg.get("seq"), 0, MAX_SEQ, name="seq")
    action = msg.get("action")
    if action not in GUEST_ACTIONS:
        raise SchemaError(f"Acción no permitida: {action}")

    if action in ("set_emotion", "set_character"):
        _require_exact_keys(msg, ("v", "t", "seq", "action", "id"))
        item_id = _require_int(msg["id"], 0, 100000, name="id")
        return {"v": PROTOCOL_VERSION, "t": "action", "seq": seq, "action": action, "id": item_id}

    if action == "set_prop":
        _require_exact_keys(msg, ("v", "t", "seq", "action", "id", "enabled"))
        item_id = _require_int(msg["id"], 0, 100000, name="id")
        enabled = _require_bool(msg["enabled"], name="enabled")
        return {
            "v": PROTOCOL_VERSION,
            "t": "action",
            "seq": seq,
            "action": action,
            "id": item_id,
            "enabled": enabled,
        }

    # flip_x, scream
    _require_exact_keys(msg, ("v", "t", "seq", "action", "enabled"))
    enabled = _require_bool(msg["enabled"], name="enabled")
    return {"v": PROTOCOL_VERSION, "t": "action", "seq": seq, "action": action, "enabled": enabled}


def validate_state_sync(msg):
    """Valida `state_sync` del Host: to == state.slot, IDs únicos, etiquetas sanitizadas."""
    _require_exact_keys(msg, ("v", "t", "to", "state_version", "state"))
    v = _require_int(msg["v"], name="v")
    if v != PROTOCOL_VERSION:
        raise SchemaError("Versión no soportada", close_code=4008, app_code="E_VERSION")
    if msg["t"] != "state_sync":
        raise SchemaError("Tipo inválido")
    to_slot = _require_int(msg["to"], 2, 4, name="to")
    state_ver = _require_int(msg["state_version"], 0, MAX_SEQ, name="state_version")
    st = msg["state"]
    if not isinstance(st, dict):
        raise SchemaError("state debe ser objeto")
    _require_exact_keys(
        st,
        (
            "slot",
            "active_character_id",
            "characters",
            "active_emotion",
            "emotions",
            "props",
            "flip_x",
            "screaming",
            "permissions",
        ),
    )
    slot = _require_int(st["slot"], 2, 4, name="state.slot")
    if slot != to_slot:
        raise SchemaError("to != state.slot")

    def _clean_catalog(items, key_name):
        if not isinstance(items, list) or len(items) > 64:
            raise SchemaError(f"{key_name} inválido o excede 64 elementos")
        seen_ids = set()
        out = []
        for item in items:
            if not isinstance(item, dict):
                raise SchemaError(f"Elemento inválido en {key_name}")
            if key_name == "props":
                _require_exact_keys(item, ("id", "name", "enabled"))
            else:
                _require_exact_keys(item, ("id", "name"))
            iid = _require_int(item["id"], 0, 100000, name=f"{key_name}.id")
            if iid in seen_ids:
                raise SchemaError(f"ID duplicado en {key_name}: {iid}")
            seen_ids.add(iid)
            entry = {"id": iid, "name": sanitize_label(item["name"], max_len=40)}
            if key_name == "props":
                entry["enabled"] = _require_bool(item["enabled"], name="props.enabled")
            out.append(entry)
        return out

    return {
        "v": PROTOCOL_VERSION,
        "t": "state_sync",
        "to": to_slot,
        "state_version": state_ver,
        "state": {
            "slot": slot,
            "active_character_id": _require_int(st["active_character_id"], 0, 100000, name="active_character_id"),
            "characters": _clean_catalog(st["characters"], "characters"),
            "active_emotion": _require_int(st["active_emotion"], 0, 100000, name="active_emotion"),
            "emotions": _clean_catalog(st["emotions"], "emotions"),
            "props": _clean_catalog(st["props"], "props"),
            "flip_x": _require_bool(st["flip_x"], name="flip_x"),
            "screaming": _require_bool(st["screaming"], name="screaming"),
            "permissions": validate_permissions(st["permissions"]),
        },
    }


def _require_hex64(val, name="hash"):
    if not isinstance(val, str) or not HEX64_RE.match(val.lower()):
        raise SchemaError(f"{name} debe ser SHA-256 hex de 64 caracteres")
    return val.lower()


def validate_pin_kdf(obj):
    if not isinstance(obj, dict):
        raise SchemaError("pin_kdf debe ser objeto")
    _require_exact_keys(obj, ("alg", "salt", "params", "hash"))
    if obj["alg"] != "scrypt":
        raise SchemaError("Algoritmo pin_kdf no soportado")
    if not isinstance(obj["salt"], str) or not (16 <= len(obj["salt"]) <= 64):
        raise SchemaError("pin_kdf.salt inválido")
    params = obj["params"]
    if not isinstance(params, dict):
        raise SchemaError("pin_kdf.params debe ser objeto")
    _require_exact_keys(params, ("N", "r", "p"))
    n = _require_int(params["N"], 1024, MAX_SCRYPT_N, name="N")
    if n & (n - 1) != 0:
        raise SchemaError("pin_kdf.N debe ser potencia de 2")
    r = _require_int(params["r"], 1, MAX_SCRYPT_R, name="r")
    p = _require_int(params["p"], 1, MAX_SCRYPT_P, name="p")
    h = _require_hex64(obj["hash"], name="pin_kdf.hash")
    return {"alg": "scrypt", "salt": obj["salt"], "params": {"N": n, "r": r, "p": p}, "hash": h}


def validate_auth_host(msg):
    _require_exact_keys(msg, ("v", "t", "host_secret", "room_code"), ("invite_token_hash", "pin_kdf"))
    v = _require_int(msg["v"], name="v")
    if v != PROTOCOL_VERSION:
        raise SchemaError("Versión no soportada", close_code=4008, app_code="E_VERSION")
    if msg["t"] != "auth_host":
        raise SchemaError("Tipo inválido")
    sec = msg["host_secret"]
    if not isinstance(sec, str) or not (22 <= len(sec) <= 128):
        raise SchemaError("host_secret inválido")
    rc = msg["room_code"]
    if rc is not None and (not isinstance(rc, str) or not (6 <= len(rc) <= 16)):
        raise SchemaError("room_code inválido")
    inv_hash = msg.get("invite_token_hash")
    if rc is None and inv_hash is None:
        raise SchemaError("invite_token_hash obligatorio al crear sala")
    out = {"v": PROTOCOL_VERSION, "t": "auth_host", "host_secret": sec, "room_code": rc}
    if inv_hash is not None:
        out["invite_token_hash"] = _require_hex64(inv_hash, name="invite_token_hash")
    if "pin_kdf" in msg and msg["pin_kdf"] is not None:
        out["pin_kdf"] = validate_pin_kdf(msg["pin_kdf"])
    return out


def validate_join(msg):
    _require_exact_keys(msg, ("v", "t", "room_code", "invite_token", "display_name"), ("pin", "session_token"))
    v = _require_int(msg["v"], name="v")
    if v != PROTOCOL_VERSION:
        raise SchemaError("Versión no soportada", close_code=4008, app_code="E_VERSION")
    if msg["t"] != "join":
        raise SchemaError("Tipo inválido")
    rc = msg["room_code"]
    inv = msg["invite_token"]
    if not isinstance(rc, str) or not (6 <= len(rc) <= 16):
        raise SchemaError("room_code inválido")
    if not isinstance(inv, str) or not (16 <= len(inv) <= 128):
        raise SchemaError("invite_token inválido")
    dname = sanitize_label(msg["display_name"], max_len=24)
    pin = msg.get("pin")
    if pin is not None and (not isinstance(pin, str) or len(pin) > 16):
        raise SchemaError("pin inválido")
    st = msg.get("session_token")
    if st is not None and (not isinstance(st, str) or not (16 <= len(st) <= 128)):
        raise SchemaError("session_token inválido")
    return {
        "v": PROTOCOL_VERSION,
        "t": "join",
        "room_code": rc,
        "invite_token": inv,
        "pin": pin,
        "display_name": dname,
        "session_token": st,
    }


def validate_join_decision(msg):
    _require_exact_keys(msg, ("v", "t", "req_id", "allow", "slot", "permissions"))
    v = _require_int(msg["v"], name="v")
    if v != PROTOCOL_VERSION:
        raise SchemaError("Versión no soportada", close_code=4008, app_code="E_VERSION")
    if msg["t"] != "join_decision":
        raise SchemaError("Tipo inválido")
    req_id = msg["req_id"]
    if not isinstance(req_id, str) or not (16 <= len(req_id) <= 64):
        raise SchemaError("req_id inválido")
    allow = _require_bool(msg["allow"], name="allow")
    slot = _require_int(msg["slot"], 2, 4, name="slot")
    perms = validate_permissions(msg["permissions"])
    return {"v": PROTOCOL_VERSION, "t": "join_decision", "req_id": req_id, "allow": allow, "slot": slot, "permissions": perms}


def validate_rotate_invite(msg):
    _require_exact_keys(msg, ("v", "t", "invite_token_hash"))
    v = _require_int(msg["v"], name="v")
    if v != PROTOCOL_VERSION:
        raise SchemaError("Versión no soportada", close_code=4008, app_code="E_VERSION")
    if msg["t"] != "rotate_invite":
        raise SchemaError("Tipo inválido")
    return {"v": PROTOCOL_VERSION, "t": "rotate_invite", "invite_token_hash": _require_hex64(msg["invite_token_hash"], "invite_token_hash")}


def validate_kick(msg):
    _require_exact_keys(msg, ("v", "t", "slot", "ban"))
    v = _require_int(msg["v"], name="v")
    if v != PROTOCOL_VERSION:
        raise SchemaError("Versión no soportada", close_code=4008, app_code="E_VERSION")
    if msg["t"] != "kick":
        raise SchemaError("Tipo inválido")
    return {
        "v": PROTOCOL_VERSION,
        "t": "kick",
        "slot": _require_int(msg["slot"], 2, 4, name="slot"),
        "ban": _require_bool(msg["ban"], name="ban"),
    }


def validate_presence(msg):
    _require_exact_keys(msg, ("v", "t", "seq", "foreground"))
    v = _require_int(msg["v"], name="v")
    if v != PROTOCOL_VERSION:
        raise SchemaError("Versión no soportada", close_code=4008, app_code="E_VERSION")
    if msg["t"] != "presence":
        raise SchemaError("Tipo inválido")
    return {
        "v": PROTOCOL_VERSION,
        "t": "presence",
        "seq": _require_int(msg["seq"], 0, MAX_SEQ, name="seq"),
        "foreground": _require_bool(msg["foreground"], name="foreground"),
    }
