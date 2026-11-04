"""WorldFootball.net: carrera por competicion/temporada (contraste para jugadores con poca cobertura FBref).

El slug viene de Wikidata (P2020). Parser defensivo sobre tablas 'standard_tabelle'.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..common import store
from ..common.http import PoliteClient

BASE = "https://www.worldfootball.net/player_summary/{slug}/"


def parse_summary(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for t in soup.select("table.standard_tabelle"):
        heads = [th.get_text(" ", strip=True).lower() for th in t.find_all("th")]
        if not heads:
            continue
        for tr in t.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) < 4:
                continue
            nums = [int(x) for x in tds if re.fullmatch(r"\d+", x)]
            out.append({"cells": tds, "headers": heads, "numbers": nums})
    return out


class WorldFootballAdapter:
    source = "worldfootball"

    def __init__(self, refresh=False, offline=False):
        self.http = PoliteClient(self.source, refresh=refresh, offline=offline)

    def fetch(self, slug: str, qid: str | None = None):
        r = self.http.get(BASE.format(slug=slug))
        rows = parse_summary(r.text) if r.ok else []
        recs = [{"worldfootball_id": slug, "qid": qid, **x, **r.provenance()} for x in rows]
        store.write_item(self.source, "summary", slug, recs)
        return recs
