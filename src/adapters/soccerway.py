"""Soccerway: NO se descarga por defecto.

Soccerway aplica anti-bot agresivo y sus ToS restringen el acceso automatizado. El
adaptador solo existe para documentar la decision: si se habilita en sources.yaml y
devuelve un desafio, el cliente HTTP marca la fuente BLOCKED y no reintenta.
"""
from __future__ import annotations

from ..common.http import PoliteClient


class SoccerwayAdapter:
    source = "soccerway"

    def __init__(self, refresh=False, offline=False):
        self.http = PoliteClient(self.source, refresh=refresh, offline=offline)

    def fetch(self, url: str):
        return self.http.get(url)
