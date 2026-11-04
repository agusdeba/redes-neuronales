"""FBref: tablas "Player Standard Stats" por competicion y temporada.

Cambios respecto de los scripts anteriores:
  - Sin SeleniumBase UC ni uc_gui_handle_captcha: requests con cache y rate limit
    (~1 request cada 7 s, por debajo del limite publicado por Sports Reference).
  - Si FBref responde con un desafio de Cloudflare, la fuente queda BLOCKED y el
    pipeline sigue con las demas fuentes (TM cubre minutos/goles/asistencias).
  - Alternativa legal y manual: exportar "Share & Export -> Get table as CSV" desde el
    navegador y dejar el archivo en data/manual/fbref/<COMP>_<temporada>.csv; se
    ingiere con procedencia method=manual_export.
  - Desde enero de 2026 FBref no tiene datos avanzados de Opta: solo se leen las
    columnas que existan, sin asumir un numero fijo.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup, Comment

from ..common import store
from ..common.config import MANUAL, load_yaml
from ..common.http import PoliteClient, manifest
from ..common.logs import get_logger

SITE = "https://fbref.com"

COLMAP = {"Player": "player", "Nation": "nation", "Pos": "pos", "Squad": "team", "Age": "age",
          "Born": "born", "MP": "mp", "Starts": "starts", "Min": "minutes", "90s": "nineties",
          "Gls": "goals", "Ast": "assists", "G+A": "g_plus_a", "G-PK": "g_minus_pk", "PK": "pk",
          "PKatt": "pkatt", "CrdY": "crdy", "CrdR": "crdr", "xG": "xg", "npxG": "npxg", "xAG": "xag",
          "PrgC": "prgc", "PrgP": "prgp", "PrgR": "prgr", "Comp": "comp"}


def seasons_for(cfg: dict) -> list[str]:
    years = cfg.get("years") or list(range(cfg["first"], cfg["last"] + 1))
    if cfg["kind"] == "two_year":
        return [f"{y}-{y + 1}" for y in years]
    return [str(y) for y in years]


def build_url(cfg: dict, season: str) -> str:
    path = cfg.get("path", "stats")
    return f"{SITE}/en/comps/{cfg['id']}/{season}/{path}/{season}-{cfg['slug']}-Stats"


def _find_table(html: str, table_id: str = "stats_standard"):
    soup = BeautifulSoup(html, "lxml")
    t = soup.find("table", id=table_id)
    if t is not None:
        return t
    for c in soup.find_all(string=lambda x: isinstance(x, Comment)):  # FBref comenta tablas
        if table_id in c:
            t = BeautifulSoup(str(c), "lxml").find("table", id=table_id)
            if t is not None:
                return t
    return None


def parse_stats_table(html: str) -> pd.DataFrame:
    """Parsea #stats_standard (cabecera de 2 niveles). Devuelve columnas canonicas + player_fbref_id."""
    t = _find_table(html)
    if t is None:
        return pd.DataFrame()
    head_rows = t.select("thead tr")
    header = [th.get("data-stat") or th.get_text(strip=True) for th in head_rows[-1].find_all(["th", "td"])] if head_rows else []
    labels = [th.get_text(strip=True) for th in head_rows[-1].find_all(["th", "td"])] if head_rows else []
    rows = []
    for tr in t.select("tbody tr"):
        if "thead" in (tr.get("class") or []) or "over_header" in (tr.get("class") or []):
            continue
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        rec = {}
        for c in cells:
            stat = c.get("data-stat")
            if stat:
                rec[stat] = c.get_text(" ", strip=True)
            if stat == "player":
                a = c.find("a", href=True)
                m = re.search(r"/players/([0-9a-f]{8})/", a["href"]) if a else None
                rec["player_fbref_id"] = m.group(1) if m else None
        if rec.get("player"):
            rows.append(rec)
    df = pd.DataFrame(rows)
    # data-stat de FBref -> nombres canonicos del proyecto
    stat_map = {"player": "player", "nationality": "nation", "position": "pos", "team": "team",
                "age": "age", "birth_year": "born", "games": "mp", "games_starts": "starts",
                "minutes": "minutes", "minutes_90s": "nineties", "goals": "goals", "assists": "assists",
                "goals_assists": "g_plus_a", "goals_pens": "g_minus_pk", "pens_made": "pk",
                "pens_att": "pkatt", "cards_yellow": "crdy", "cards_red": "crdr", "xg": "xg",
                "npxg": "npxg", "xg_assist": "xag", "comp_level": "comp", "ranker": None, "matches": None}
    keep = {k: v for k, v in stat_map.items() if v and k in df.columns}
    out = df[list(keep) + (["player_fbref_id"] if "player_fbref_id" in df.columns else [])].rename(columns=keep)
    for c in ("age", "born", "mp", "starts", "minutes", "nineties", "goals", "assists", "g_plus_a",
              "g_minus_pk", "pk", "pkatt", "crdy", "crdr", "xg", "npxg", "xag"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c].astype(str).str.replace(",", "").str.split("-").str[0], errors="coerce")
    if "nation" in out.columns:
        out["nation"] = out["nation"].astype(str).str.split().str[-1].str.upper()
    return out


def parse_manual_csv(path: Path) -> pd.DataFrame:
    """CSV exportado a mano desde FBref (2 lineas de cabecera, filas repetidas de header)."""
    txt = path.read_text(encoding="utf-8-sig")
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    hidx = next(i for i, ln in enumerate(lines) if ln.startswith("Rk,") or ",Player," in ln)
    df = pd.read_csv(io.StringIO("\n".join(lines[hidx:])))
    df = df[df.get("Player", pd.Series(dtype=str)).astype(str) != "Player"]
    # columnas duplicadas (per 90) quedan como Gls.1 etc. y se descartan
    df = df[[c for c in df.columns if c in COLMAP]].rename(columns=COLMAP)
    if "nation" in df.columns:
        df["nation"] = df["nation"].astype(str).str.split().str[-1].str.upper()
    return df


class FBrefAdapter:
    source = "fbref"

    def __init__(self, refresh=False, offline=False):
        self.http = PoliteClient(self.source, refresh=refresh, offline=offline)
        self.comps = load_yaml("fbref_competitions.yaml")["competitions"]
        self.log = get_logger("adapter.fbref")

    def download(self, only: list[str] | None = None, limit: int | None = None):
        m = manifest()
        for key, cfg in self.comps.items():
            if only and key not in only:
                continue
            seasons = seasons_for(cfg)[: limit or None]
            for season in seasons:
                item = f"{key}_{season}"
                if m.task_status("fbref_comp", item) == "done" and not self.http.refresh:
                    continue
                r = self.http.get(build_url(cfg, season))
                if r.status in (404, 410):
                    m.set_task("fbref_comp", item, "not_found")
                    continue
                df = parse_stats_table(r.text)
                df["competition"] = key
                df["season"] = season
                df["competition_type"] = cfg.get("type")
                for k, v in r.provenance().items():
                    df[k] = v
                df["method"] = "requests"
                store.write_item(self.source, "season_stats", item, df.to_dict("records"))
                m.set_task("fbref_comp", item, "done", f"{len(df)} filas")
                self.log.info(f"{item}: {len(df)} filas")
        self.ingest_manual()

    def ingest_manual(self):
        d = MANUAL / "fbref"
        if not d.exists():
            return
        for p in sorted(d.glob("*.csv")):
            key, _, season = p.stem.rpartition("_")
            df = parse_manual_csv(p)
            df["competition"] = key
            df["season"] = season
            df["competition_type"] = (self.comps.get(key) or {}).get("type")
            df["source"] = "fbref"
            df["source_url"] = f"manual:{p.name}"
            df["retrieved_at"] = pd.Timestamp(p.stat().st_mtime, unit="s").strftime("%Y-%m-%dT%H:%M:%SZ")
            df["raw_ref"] = str(p)
            df["method"] = "manual_export"
            store.write_item(self.source, "season_stats", f"manual_{p.stem}", df.to_dict("records"))
            self.log.info(f"manual {p.name}: {len(df)} filas")
