#!/usr/bin/env python3
"""Descarga los CSVs de "Player Standard Stats" de una competición de FBref.

Estrategia (igual que soccerdata): evita depender del clic de exportación de FBref.
  - Abre cada temporada con SeleniumBase en modo UC (undetected-chromedriver) y
    Chrome visible, que sortea el anti-bot de Cloudflare / Turnstile.
  - Si la tabla de jugadores está colapsada, cliquea "Show Player Standard Stats".
  - Lee la tabla #stats_standard del DOM y reconstruye el CSV con el mismo
    contenido que genera "Share & Export -> Get table as CSV (for Excel)".

Ejemplos:
  python fbref_friendlies.py                                     # amistosos 2014-2025
  python fbref_friendlies.py --comp-id 8 --slug Champions-League \
      --start 1995 --end 2025 --two-year --prefix fbref_champions
"""

import argparse
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CSV_DIR = BASE_DIR / "csv"
LOG_FILE = BASE_DIR / "download.log"

TABLE_ID = "stats_standard"

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


def build_url(comp_id: str, slug: str, season_start: int, season_end: int, two_year: bool) -> str:
    if two_year:
        seg = f"{season_start}-{season_end}"
        return f"https://fbref.com/en/comps/{comp_id}/{seg}/stats/{seg}-{slug}-Stats"
    return f"https://fbref.com/en/comps/{comp_id}/{season_start}/stats/{season_start}-{slug}-Stats"


def season_label(season_start: int, season_end: int, two_year: bool) -> str:
    if two_year:
        return f"{season_start}-{season_end}"
    return str(season_start)


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
    """Cliquea 'Show Player Standard Stats' si la tabla está colapsada."""
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
    """Lee del DOM las celdas (innerText) de todas las filas de la tabla de jugadores."""
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


def process_season(sb, comp_id: str, slug: str, s_start: int, s_end: int,
                   two_year: bool, prefix: str, retries: int = 2) -> bool:
    url = build_url(comp_id, slug, s_start, s_end, two_year)
    label = season_label(s_start, s_end, two_year)
    out_path = CSV_DIR / f"{prefix}_{label}.csv"
    for attempt in range(1, retries + 1):
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
            if not wait_for_table(sb, timeout=90):
                raise RuntimeError("la tabla de jugadores no apareció (posible CAPTCHA, página sin datos o temporada sin stats)")

            data = read_table_cells(sb)
            if not data or len(data) < 3:
                raise RuntimeError("no se pudieron leer las celdas de la tabla de jugadores")

            if not write_csv(data, out_path):
                raise RuntimeError("el CSV generado no superó la validación")

            logger.info(f"[{label}] OK -> {out_path.name} ({len(data)} filas, {out_path.stat().st_size} bytes)")
            return True
        except Exception as exc:
            logger.error(f"[{label}] error en intento {attempt}: {exc}")
            if attempt < retries:
                delay = random.uniform(12, 20)
                logger.info(f"[{label}] esperando {delay:.0f}s antes de reintentar")
                sb.sleep(delay)
    return False


def main():
    parser = argparse.ArgumentParser(description="Descarga CSVs de Player Standard Stats de FBref.")
    parser.add_argument("--comp-id", default="218", help="Id de competición (218=Amistosos, 8=Champions League).")
    parser.add_argument("--slug", default="Friendlies-M", help="Slug de la competición en la URL.")
    parser.add_argument("--start", type=int, default=2014, help="Temporada inicial (año).")
    parser.add_argument("--end", type=int, default=2025, help="Temporada final (año).")
    parser.add_argument("--two-year", action="store_true",
                        help="Usar temporadas dobles en la URL (ej. 1995-1996).")
    parser.add_argument("--prefix", default="fbref_friendlies",
                        help="Prefijo del nombre de archivo CSV.")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--headless", action="store_true",
                        help="Usar Chrome sin ventana (aumenta riesgo de bloqueo).")
    parser.add_argument("--delay", type=float, default=0,
                        help="Delay fijo extra entre años; por defecto aleatorio 8-15s.")
    args = parser.parse_args()

    setup_logging()
    CSV_DIR.mkdir(parents=True, exist_ok=True)

    season_range = range(args.start, args.end + 1)
    seasons = [(y, y + 1) for y in season_range] if args.two_year else [(y, None) for y in season_range]
    logger.info(f"Competición: comps/{args.comp_id} ({args.slug}) | temporadas: "
                f"{season_label(*seasons[0][:2] if args.two_year else seasons[0], args.two_year)}"
                f" -> {season_label(*seasons[-1][:2] if args.two_year else seasons[-1], args.two_year)}"
                f" ({len(seasons)} páginas)")

    from seleniumbase import SB

    results = {}
    with SB(uc=True, headed=not args.headless, locale="en", time_limit=7200) as sb:
        for idx, (s_start, s_end) in enumerate(seasons):
            results[season_label(s_start, s_end if s_end else s_start + 1, args.two_year)] = process_season(
                sb, args.comp_id, args.slug, s_start, s_end, args.two_year, args.prefix, retries=args.retries
            )
            if idx < len(seasons) - 1:
                delay = args.delay or random.uniform(8, 15)
                logger.info(f"esperando {delay:.0f}s antes de la siguiente temporada")
                sb.sleep(delay)

    oks = [k for k, ok in results.items() if ok]
    fails = [k for k, ok in results.items() if not ok]
    logger.info("=" * 60)
    logger.info(f"OK ({len(oks)}): {oks}")
    if fails:
        logger.info(f"FALLIDOS ({len(fails)}): {fails}")
    logger.info(f"CSV guardados en: {CSV_DIR}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())