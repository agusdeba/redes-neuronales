"""National-Football-Teams.com: caps y goles de seleccion mayor por anio (contraste).

El id viene de Wikidata (P2574, forma '<num>/<Nombre>'). Parser defensivo: busca la
tabla cuyo encabezado contiene 'Year' y 'Matches'/'Caps'. Si el markup cambia, el
resultado queda vacio (nulo), no inventado.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..common import store
from ..common.http import PoliteClient

BASE = "https://www.national-football-teams.com/player/{id}.html"


def parse_player(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    years = []
    for t in soup.find_all("table"):
        heads = [th.get_text(" ", strip=True).lower() for th in t.find_all("th")]
        if not heads or not any("year" in h for h in heads):
            continue
        idx_m = next((i for i, h in enumerate(heads) if h in ("matches", "caps", "apps", "m")), None)
        idx_g = next((i for i, h in enumerate(heads) if h in ("goals", "g")), None)
        if idx_m is None:
            continue
        for tr in t.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) <= idx_m or not re.match(r"^(19|20)\d{2}$", tds[0]):
                continue
            num = lambda s: int(s) if s and s.isdigit() else None
            years.append({"year": int(tds[0]), "matches": num(tds[idx_m]),
                          "goals": num(tds[idx_g]) if idx_g is not None and idx_g < len(tds) else None})
        if years:
            break
    total_m = sum(y["matches"] or 0 for y in years) if years else None
    total_g = sum(y["goals"] or 0 for y in years) if years else None
    return {"years": years, "caps_total": total_m, "goals_total": total_g}


class NFTAdapter:
    source = "nft"

    def __init__(self, refresh=False, offline=False):
        self.http = PoliteClient(self.source, refresh=refresh, offline=offline)

    def fetch(self, nft_id: str, qid: str | None = None):
        r = self.http.get(BASE.format(id=nft_id))
        rec = {"nft_id": nft_id, "qid": qid, **(parse_player(r.text) if r.ok else {"years": []}), **r.provenance()}
        store.write_item(self.source, "caps", nft_id.replace("/", "_"), [rec])
        return rec
