"""Normalizacion de nombres y textos."""
from __future__ import annotations

import re
import unicodedata


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c))


def norm_name(s) -> str:
    """'Sergio Agüero' -> 'sergio aguero' (minusculas, sin acentos ni puntuacion, espacios simples)."""
    s = strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def norm_key(s) -> str:
    """Clave compacta sin espacios (compatible con norm() de los scripts legacy)."""
    return norm_name(s).replace(" ", "")


def norm_label(s) -> str:
    """Para comparar etiquetas de posicion: minusculas, sin acentos, guiones conservados."""
    s = strip_accents(s).lower().strip()
    s = re.sub(r"[^a-z0-9\- ]+", " ", s)
    return " ".join(s.split())
