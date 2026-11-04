"""API-Football (api-sports.io): API oficial con clave. Contraste de temporadas recientes.

Se activa solo si existe API_FOOTBALL_KEY en .env. Plan gratuito: 100 requests/dia.
"""
from __future__ import annotations

import os

from ..common import store
from ..common.http import PoliteClient

BASE = "https://v3.football.api-sports.io"


class APIFootballAdapter:
    source = "api_football"

    def __init__(self, refresh=False, offline=False):
        self.key = os.environ.get("API_FOOTBALL_KEY", "").strip()
        if not self.key and not offline:
            raise RuntimeError("API_FOOTBALL_KEY no configurada en .env")
        self.http = PoliteClient(self.source, refresh=refresh, offline=offline)
        self.http.session.headers["x-apisports-key"] = self.key

    def search_profiles(self, name: str):
        r = self.http.get(f"{BASE}/players/profiles", params={"search": name})
        return (r.json().get("response") or []), r

    def player_season(self, player_id: int, season: int):
        r = self.http.get(f"{BASE}/players", params={"id": player_id, "season": season})
        resp = r.json().get("response") or []
        recs = []
        for x in resp:
            p = x.get("player") or {}
            for s in x.get("statistics") or []:
                g = s.get("games") or {}
                recs.append({"api_football_id": p.get("id"), "name": p.get("name"),
                             "dob": (p.get("birth") or {}).get("date"), "nationality": p.get("nationality"),
                             "team": (s.get("team") or {}).get("name"), "league": (s.get("league") or {}).get("name"),
                             "season": season, "position": g.get("position"), "appearances": g.get("appearences"),
                             "starts": g.get("lineups"), "minutes": g.get("minutes"),
                             "goals": (s.get("goals") or {}).get("total"), "assists": (s.get("goals") or {}).get("assists"),
                             "shots": (s.get("shots") or {}).get("total"),
                             "yellow": (s.get("cards") or {}).get("yellow"), "red": (s.get("cards") or {}).get("red"),
                             **r.provenance()})
        store.write_item(self.source, "player_season", f"{player_id}_{season}", recs)
        return recs
