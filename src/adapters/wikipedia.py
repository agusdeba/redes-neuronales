"""Wikipedia (es/pt/en) via API MediaWiki: descubrimiento por categorias y validacion por infobox.

Nunca se usa como fuente estadistica primaria. Si contradice a TM/FBref, se registra
el conflicto en la tabla conflicts.
"""
from __future__ import annotations

import re

from ..common import store
from ..common.http import PoliteClient, manifest
from ..common.logs import get_logger

API = "https://{lang}.wikipedia.org/w/api.php"

# Categorias de descubrimiento (se recorren sin recursion; las subcategorias por club
# se pueden agregar aca).
CATEGORIES = {
    "ARG": [("es", "Categoría:Futbolistas de Argentina"), ("en", "Category:Argentine footballers")],
    "BRA": [("pt", "Categoria:Futebolistas do Brasil"), ("en", "Category:Brazilian footballers")],
    "CHI": [("es", "Categoría:Futbolistas de Chile"), ("en", "Category:Chilean footballers")],
    "URU": [("es", "Categoría:Futbolistas de Uruguay"), ("en", "Category:Uruguayan footballers")],
    "PAR": [("es", "Categoría:Futbolistas de Paraguay"), ("en", "Category:Paraguayan footballers")],
    "COL": [("es", "Categoría:Futbolistas de Colombia"), ("en", "Category:Colombian footballers")],
    "ECU": [("es", "Categoría:Futbolistas de Ecuador"), ("en", "Category:Ecuadorian footballers")],
}

INFOBOX_FIELDS = {
    "en": {"position": "position", "birth_date": "birth_date"},
    "es": {"position": "posición", "birth_date": "fecha de nacimiento"},
    "pt": {"position": "posição", "birth_date": "data de nascimento"},
}


def parse_infobox(wikitext: str, lang: str) -> dict:
    """Extrae campos simples del primer infobox. Para en: clubsN/yearsN/capsN/goalsN y nationalteamN/capsN."""
    fields: dict[str, str] = {}
    for m in re.finditer(r"^\s*\|\s*([^=|\n]+?)\s*=\s*(.*)$", wikitext, flags=re.M):
        k = m.group(1).strip().lower()
        if k not in fields:
            fields[k] = m.group(2).strip()
    clean = lambda v: re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", re.sub(r"<ref.*?(/>|</ref>)", "", v or "")).strip()
    out = {"position": clean(fields.get(INFOBOX_FIELDS[lang]["position"], "")) or None,
           "birth_date_raw": fields.get(INFOBOX_FIELDS[lang]["birth_date"])}
    m = re.search(r"(\d{4})\|(\d{1,2})\|(\d{1,2})", out["birth_date_raw"] or "")
    out["birth_date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None
    clubs, nts = [], []
    for i in range(1, 40):
        if f"clubs{i}" in fields:
            clubs.append({"years": clean(fields.get(f"years{i}")), "club": clean(fields.get(f"clubs{i}")),
                          "caps": clean(fields.get(f"caps{i}")), "goals": clean(fields.get(f"goals{i}"))})
        if f"nationalteam{i}" in fields:
            nts.append({"years": clean(fields.get(f"nationalyears{i}")), "team": clean(fields.get(f"nationalteam{i}")),
                        "caps": clean(fields.get(f"nationalcaps{i}")), "goals": clean(fields.get(f"nationalgoals{i}"))})
    out["clubs"], out["national_teams"] = clubs, nts
    return out


class WikipediaAdapter:
    source = "wikipedia"

    def __init__(self, refresh=False, offline=False):
        self.http = PoliteClient(self.source, refresh=refresh, offline=offline)
        self.log = get_logger("adapter.wikipedia")

    def category_members(self, lang: str, category: str):
        out, cont = [], {}
        while True:
            params = {"action": "query", "format": "json", "generator": "categorymembers",
                      "gcmtitle": category, "gcmlimit": "500", "gcmtype": "page", "prop": "pageprops",
                      "ppprop": "wikibase_item", "maxlag": "5", **cont}
            r = self.http.get(API.format(lang=lang), params=params)
            d = r.json()
            for p in (d.get("query") or {}).get("pages", {}).values():
                out.append({"lang": lang, "title": p.get("title"), "pageid": p.get("pageid"),
                            "qid": (p.get("pageprops") or {}).get("wikibase_item"), "category": category,
                            **r.provenance()})
            if "continue" not in d:
                return out
            cont = {k: v for k, v in d["continue"].items()}

    def discover(self, countries: list[str]):
        m = manifest()
        for c in countries:
            for lang, cat in CATEGORIES.get(c, []):
                item = f"{c}_{lang}"
                if m.task_status("wikipedia_cat", item) == "done" and not self.http.refresh:
                    continue
                mem = self.category_members(lang, cat)
                for x in mem:
                    x["country"] = c
                store.write_item(self.source, "category_members", item, mem)
                m.set_task("wikipedia_cat", item, "done", f"{len(mem)} paginas")
                self.log.info(f"{item}: {len(mem)} paginas")

    def infobox(self, lang: str, title: str) -> dict:
        r = self.http.get(API.format(lang=lang), params={"action": "parse", "format": "json", "page": title,
                                                           "prop": "wikitext", "section": "0", "redirects": "1",
                                                           "maxlag": "5"})
        wt = ((r.json().get("parse") or {}).get("wikitext") or {}).get("*", "")
        return {**parse_infobox(wt, lang), "lang": lang, "title": title, **r.provenance()}
