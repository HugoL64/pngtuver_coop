"""Utilidades para resolver rutas de archivos de personajes sin salir de su carpeta."""

import os


def is_within(base_dir, target_path):
    """True si `target_path` (resuelto con realpath) está dentro de `base_dir`."""
    if not base_dir or not target_path:
        return False
    try:
        base_real = os.path.realpath(base_dir)
        target_real = os.path.realpath(target_path)
        return os.path.commonpath([base_real, target_real]) == base_real
    except (ValueError, OSError):
        # Distinta unidad en Windows, rutas vacías o inválidas
        return False


def safe_join_within(base_dir, rel_path):
    """Une `rel_path` a `base_dir` y devuelve la ruta absoluta solo si queda dentro de la carpeta.

    Rechaza rutas absolutas, con unidad (`C:`), con `..` que escapen de la carpeta, o enlaces
    simbólicos que apunten fuera. Devuelve None si la ruta no es segura.
    """
    if not base_dir or not isinstance(rel_path, str) or not rel_path.strip():
        return None
    rel = rel_path.strip().replace("\\", "/")
    drive, _ = os.path.splitdrive(rel)
    if drive or os.path.isabs(rel) or rel.startswith("/"):
        return None
    cand = os.path.abspath(os.path.join(base_dir, rel))
    return cand if is_within(base_dir, cand) else None
