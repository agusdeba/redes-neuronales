"""StatsBomb Open Data (GitHub): validacion de tiros/xG en los torneos cubiertos.

Licencia: uso no comercial con atribucion a StatsBomb. Une por nombre + pais
(las alineaciones no traen fecha de nacimiento), por eso solo se usa para validar.
"""
from __future__ import annotations

from collections import defaultdict

from ..common import store
from ..common.http import PoliteClient
from ..common.logs import get_logger

BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
COUNTRIES = {"Argentina", "Brazil", "Chile", "Uruguay", "Paraguay", "Colombia", "Ecuador"}


class StatsBombAdapter:
    source = "statsbomb"

    def __init__(self, refresh=False, offline=False):
        self.http = PoliteClient(self.source, refresh=refresh, offline=offline)
        self.log = get_logger("adapter.statsbomb")

    def competitions(self):
        return self.http.get(f"{BASE}/competitions.json").json()

    def download(self, only_men=True, limit_matches=None):
        for comp in self.competitions():
            if only_men and comp.get("competition_gender") != "male":
                continue
            cid, sid = comp["competition_id"], comp["season_id"]
            item = f"{cid}_{sid}"
            matches = self.http.get(f"{BASE}/matches/{cid}/{sid}.json").json()
            agg = defaultdict(lambda: {"shots": 0, "goals": 0, "xg": 0.0, "matches": set()})
            meta = {}
            for mt in matches[: limit_matches or None]:
                mid = mt["match_id"]
                for team in self.http.get(f"{BASE}/lineups/{mid}.json").json():
                    for p in team.get("lineup", []):
                        country = (p.get("country") or {}).get("name")
                        if country in COUNTRIES:
                            meta[p["player_id"]] = {"name": p.get("player_name"), "nickname": p.get("player_nickname"),
                                                    "country": country}
                ev = self.http.get(f"{BASE}/events/{mid}.json")
                for e in ev.json():
                    pid = (e.get("player") or {}).get("id")
                    if pid not in meta:
                        continue
                    agg[pid]["matches"].add(mid)
                    if (e.get("type") or {}).get("name") == "Shot":
                        s = e.get("shot") or {}
                        agg[pid]["shots"] += 1
                        agg[pid]["xg"] += float(s.get("statsbomb_xg") or 0)
                        agg[pid]["goals"] += int((s.get("outcome") or {}).get("name") == "Goal")
            recs = [{"statsbomb_id": pid, **meta[pid], "competition": comp.get("competition_name"),
                     "season": comp.get("season_name"), "matches": len(a["matches"]), "shots": a["shots"],
                     "goals": a["goals"], "xg": round(a["xg"], 3), "source": self.source,
                     "source_url": f"{BASE}/matches/{cid}/{sid}.json"} for pid, a in agg.items()]
            store.write_item(self.source, "player_competition", item, recs)
            self.log.info(f"{comp.get('competition_name')} {comp.get('season_name')}: {len(recs)} jugadores")
