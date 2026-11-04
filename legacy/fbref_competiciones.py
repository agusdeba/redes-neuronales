#!/usr/bin/env python3
"""Descarga la tabla "Player Standard Stats" de varias competiciones de FBref.

Misma estrategia probada que fbref_friendlies.py:
  - SeleniumBase en modo UC (undetected-chromedriver), Chrome visible.
  - Cliquea "Show Player Standard Stats" si la tabla esta colapsada.
  - Lee la tabla #stats_standard del DOM y la guarda como CSV.

Estructura de salida (dentro de fbref/):
  Big5EuropeanLeague/    fbref_big5_1995-1996.csv ... + Big5EuropeanLeague1995_2026.csv
  portugal/              fbref_portugal_2000-2001.csv ... + portugal_2000_2026.csv
  world_cup/             fbref_worldcup_1994.csv ...     + world_cup_1994_2026.csv
  wcq_conmebol/          fbref_wcq_conmebol_2002.csv ... + wcq_conmebol_2002_2026.csv
  wcq_uefa/              fbref_wcq_uefa_1998.csv ...     + wcq_uefa_1998_2026.csv

Ejemplo:
  python fbref_competiciones.py                        # todas las competiciones
  python fbref_competiciones.py --only portugal        # solo una
"""

import argparse
import csv
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "download.log"
TABLE_ID = "stats_standard"
SITE = "https://fbref.com"

logger = logging.getLogger("fbref")


def setup_logging():
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)


# ---------------------------------------------------------------------------
# Configuracion de competiciones
# ---------------------------------------------------------------------------

def seasons_two_year(start: int, end: int):
    return [(y, "{}-{}".format(y, y + 1)) for y in range(start, end + 1)]


def seasons_single(years):
    return [(y, str(y)) for y in years]


COMPETITIONS = {
    "big5": {
        "label": "Big5EuropeanLeague",
        "folder": "Big5EuropeanLeague",
        "seg": "Big5",
        "slug": "Big-5-European-Leagues",
        "kind": "two_year",
        "seasons": seasons_two_year(1995, 2025),
        "prefix": "fbref_big5",
        "merge_out": "Big5EuropeanLeague1995_2026.csv",
        "player_path": "stats/player",
    },
    "portugal": {
        "label": "portugal",
        "folder": "portugal",
        "seg": "32",
        "slug": "Primeira-Liga",
        "kind": "two_year",
        "seasons": seasons_two_year(2000, 2025),
        "prefix": "fbref_portugal",
        "merge_out": "portugal_2000_2026.csv",
    },
    "world_cup": {
        "label": "world_cup",
        "folder": "world_cup",
        "seg": "1",
        "slug": "World-Cup",
        "kind": "single",
        "seasons": seasons_single([1994, 1998, 2002, 2006, 2010, 2014, 2018, 2022, 2026]),
        "prefix": "fbref_worldcup",
        "merge_out": "world_cup_1994_2026.csv",
    },
    "wcq_conmebol": {
        "label": "wcq_conmebol",
        "folder": "wcq_conmebol",
        "seg": "4",
        "slug": "WCQ----CONMEBOL-M",
        "kind": "single",
        "seasons": seasons_single([2002, 2006, 2010, 2014, 2018, 2022, 2026]),
        "prefix": "fbref_wcq_conmebol",
        "merge_out": "wcq_conmebol_2002_2026.csv",
    },
    "wcq_uefa": {
        "label": "wcq_uefa",
        "folder": "wcq_uefa",
        "seg": "6",
        "slug": "WCQ----UEFA-M",
        "kind": "single",
        "seasons": seasons_single([2006, 2010, 2014, 2018, 2022, 2026]),
        "prefix": "fbref_wcq_uefa",
        "merge_out": "wcq_uefa_2006_2026.csv",
    },
}


def build_urls(cfg, year, label):
    seg = cfg["seg"]
    slug = cfg["slug"]
    if cfg["kind"] == "two_year":
        seg2 = f"{year}-{year + 1}"
        player_path = cfg.get("player_path", "stats")
        primary = f"{SITE}/en/comps/{seg}/{seg2}/{player_path}/{seg2}-{slug}-Stats"
        alt = f"{SITE}/en/comps/{seg}/{seg2}/stats/{seg2}-{slug}-Stats"
    else:
        primary = f"{SITE}/en/comps/{seg}/{year}/stats/{year}-{slug}-Stats"
        alt = f"{SITE}/en/comps/{seg}/{year}/{year}-{slug}-Stats"
    return primary, alt


# ---------------------------------------------------------------------------
# Extraccion (reutiliza la logica probada de fbref_friendlies.py)
# ---------------------------------------------------------------------------

def page_has_captcha(sb) -> bool:
    markers = [
        "challenge-platform", "Turnstile", "Just a moment",
        "cf-chl-widget", "challenges.cloudflare.com", "Attention Required",
    ]
    try:
        src = sb.get_page_source()
    except Exception:
        return False
    return any(m in src for m in markers)


def wait_for_table(sb, timeout: int = 90) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            present = sb.execute_script(
                "return !!document.getElementById(%s);" % json.dumps(TABLE_ID)
            )
            if present:
                time.sleep(2)
                return True
        except Exception:
            pass
        time.sleep(1.5)
    return False


def reveal_player_table(sb) -> str:
    """Cliquea 'Show Player Standard Stats' si la tabla esta colapsada."""
    js = """
    var c = document.getElementById('stats_standard_control');
    if (c) { c.click(); return 'control'; }
    var btns = document.querySelectorAll('button, [role=button], a, div.button');
    for (var i = 0; i < btns.length; i++) {
        var t = (btns[i].textContent || '').trim();
        if (t.indexOf('Show Player Standard Stats') !== -1) {
            btns[i].click();
            return 'text';
        }
    }
    return 'none';
    """
    try:
        return sb.execute_script(js)
    except Exception:
        return "none"


def read_table_cells(sb):
    js = r"""
    var tbl = document.getElementById('stats_standard');
    if (!tbl) return null;
    var rows = tbl.querySelectorAll('tr');
    var data = [];
    for (var i = 0; i < rows.length; i++) {
        var cells = rows[i].querySelectorAll('td,th');
        var line = [];
        for (var j = 0; j < cells.length; j++) {
            line.push(cells[j].innerText || '');
        }
        data.push(line);
    }
    return JSON.stringify(data);
    """
    raw = sb.execute_script(js)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def write_csv(data, out_path: Path) -> bool:
    def field(value: str) -> str:
        v = " ".join(value.split())
        if "," in v or '"' in v or "\n" in v:
            v = '"' + v.replace('"', '""') + '"'
        return v

    lines = [",".join(field(c) for c in row) for row in data]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return validate_csv(out_path, len(data))


def validate_csv(path: Path, expected_rows: int) -> bool:
    if not path.is_file() or path.stat().st_size < 200:
        return False
    head = path.read_bytes()[:4000].decode("utf-8", errors="replace")
    if "Player" not in head:
        return False
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        nrows = sum(1 for _ in fh)
    return nrows >= 3 and nrows >= expected_rows * 0.9


def process_season(sb, cfg, year, label, out_path, retries: int = 2) -> bool:
    primary, alt = build_urls(cfg, year, label)
    urls = [primary] + ([alt] if alt != primary else [])
    for attempt in range(1, retries + 1):
        url = urls[min(attempt - 1, len(urls) - 1)]
        logger.info(f"[{label}] intento {attempt}/{retries}: {url}")
        try:
            sb.uc_open_with_reconnect(url, reconnect_time=7)
            sb.sleep(3)
            if page_has_captcha(sb):
                logger.info(f"[{label}] challenge/CAPTCHA detectado, intentando resolver...")
                try:
                    sb.uc_gui_handle_captcha()
                except Exception as exc:
                    logger.warning(f"[{label}] uc_gui_handle_captcha: {exc}")
                sb.sleep(2)

            time.sleep(2)
            revealed = reveal_player_table(sb)
            logger.info(f"[{label}] show-player-stats: {revealed}")
            if not wait_for_table(sb, timeout=60):
                raise RuntimeError("la tabla de jugadores no aparecio (posible CAPTCHA o URL invalida)")

            data = read_table_cells(sb)
            if not data or len(data) < 3:
                raise RuntimeError("no se pudieron leer las celdas de la tabla")

            if not write_csv(data, out_path):
                raise RuntimeError("el CSV generado no supero la validacion")

            logger.info(f"[{label}] OK -> {out_path.name} ({len(data)} filas, {out_path.stat().st_size} bytes)")
            return True
        except Exception as exc:
            logger.error(f"[{label}] error en intento {attempt}: {exc}")
            if attempt < retries:
                delay = random.uniform(12, 20)
                logger.info(f"[{label}] esperando {delay:.0f}s antes de reintentar")
                sb.sleep(delay)
    return False


# ---------------------------------------------------------------------------
# Merge por competicion
# ---------------------------------------------------------------------------

def merge_competition(cfg, saved):
    """Une los CSV por temporada en un unico archivo con columna Season."""
    folder = BASE_DIR / cfg["folder"]
    out_path = folder / cfg["merge_out"]
    if not saved:
        logger.warning(f"merge {cfg['label']}: no hay temporadas descargadas, se omite")
        return

    header = None
    rows = []
    for label, path in saved:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.reader(fh)
            lines = list(reader)
        if len(lines) < 2:
            logger.warning(f"merge {cfg['label']}: {label} sin cabecera completa, se omite")
            continue
        if header is None:
            header = lines[1]
        data_lines = lines[2:]
        for row in data_lines:
            if not row or all(not c.strip() for c in row):
                continue
            rows.append([label] + row)

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Season"] + header)
        writer.writerows(rows)
    logger.info(f"merge {cfg['label']}: {len(rows)} filas -> {out_path}")
    return len(rows)


# ---------------------------------------------------------------------------

def run_competition(cfg, sb, retries: int = 2, limit=None):
    folder = BASE_DIR / cfg["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    seasons = cfg["seasons"]
    if limit:
        seasons = seasons[:limit]
    logger.info(f"=== {cfg['label']}: {len(seasons)} paginas -> {folder}/ ===")

    saved = []
    results = {}
    n = len(seasons)
    for idx, (year, label) in enumerate(seasons):
        out_path = folder / f"{cfg['prefix']}_{label}.csv"
        ok = process_season(sb, cfg, year, label, out_path, retries=retries)
        results[label] = ok
        if ok:
            saved.append((label, out_path))
        if idx < n - 1:
            delay = random.uniform(8, 15)
            logger.info(f"esperando {delay:.0f}s antes de la siguiente temporada")
            sb.sleep(delay)

    oks = [k for k, ok in results.items() if ok]
    fails = [k for k, ok in results.items() if not ok]
    logger.info(f"{cfg['label']}: OK ({len(oks)}) = {oks}")
    if fails:
        logger.info(f"{cfg['label']}: FALLIDOS ({len(fails)}) = {fails}")
    merge_competition(cfg, saved)
    return fails


def main():
    parser = argparse.ArgumentParser(description="Descarga Player Standard Stats de FBref por competicion.")
    parser.add_argument("--only", nargs="*", default=None,
                        help="Solo estas competiciones: big5 portugal world_cup wcq_conmebol wcq_uefa")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--limit", type=int, default=0,
                        help="Procesar solo las primeras N paginas de cada competicion (prueba rapida).")
    args = parser.parse_args()

    setup_logging()

    names = list(COMPETITIONS)
    if args.only:
        for n in args.only:
            if n not in COMPETITIONS:
                logger.error(f"Competicion desconocida: {n} (opciones: {names})")
                return 2
        names = args.only

    from seleniumbase import SB

    all_fails = {}
    with SB(uc=True, headed=not args.headless, locale="en", time_limit=14400) as sb:
        for name in names:
            fails = run_competition(COMPETITIONS[name], sb, retries=args.retries,
                                    limit=args.limit or None)
            if fails:
                all_fails[name] = fails

    logger.info("=" * 60)
    if all_fails:
        logger.info(f"FALLIDOS totales: {all_fails}")
        return 1
    logger.info("Todas las competiciones completadas OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())