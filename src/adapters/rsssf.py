"""RSSSF: backfill historico (goleadores, planteles) desde paginas configuradas a mano.

RSSSF no tiene formato uniforme: cada pagina se agrega en config/rsssf_pages.yaml con
el parser a usar. Se incluye un parser de listas de goleadores del tipo
'Nombre (Club)   25'. El resto de las paginas se guarda en crudo para parsers futuros.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..common import store
from ..common.config import CONFIG_DIR
from ..common.http import PoliteClient

TOPSCORER = re.compile(r"^\s*(?:\d+\.\s*)?([A-ZÁÉÍÓÚÑÜ][\w'\.\- ÁÉÍÓÚÑÜáéíóúñü]+?)\s+\(([^)]+)\)\s+(\d{1,3})\s*$")


def parse_topscorers(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = TOPSCORER.match(re.sub(r"<[^>]+>", "", line))
        if m:
            out.append({"player": m.group(1).strip(), "club": m.group(2).strip(), "goals": int(m.group(3))})
    return out


class RSSSFAdapter:
    source = "rsssf"

    def __init__(self, refresh=False, offline=False):
        self.http = PoliteClient(self.source, refresh=refresh, offline=offline)
        p = CONFIG_DIR / "rsssf_pages.yaml"
        self.pages = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("pages", []) if p.exists() else []

    def download(self):
        for pg in self.pages:
            r = self.http.get(pg["url"])
            recs = parse_topscorers(r.text) if pg.get("parser") == "topscorers" else []
            store.write_item(self.source, pg.get("parser", "raw"), pg["id"],
                             [{**x, "page_id": pg["id"], "country": pg.get("country"), "season": pg.get("season"),
                               **r.provenance()} for x in recs])
