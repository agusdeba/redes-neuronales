#!/usr/bin/env python3
"""Descarga la tabla "Player Standard Stats" de la Liga AUF Uruguaya (FBref).

Temporadas: 2014-2015, 2015-2016 y luego anios calendario 2016..2025.
URL patron (comps/45):
  https://fbref.com/en/comps/45/2014-2015/stats/2014-2015-Liga-AUF-Uruguaya-Stats
  https://fbref.com/en/comps/45/2015-2016/stats/2015-2016-Liga-AUF-Uruguaya-Stats
  https://fbref.com/en/comps/45/2016/stats/2016-Liga-AUF-Uruguaya-Stats ...

Estrategia (igual que fbref_competiciones.py / fbref_friendlies.py):
  - SeleniumBase en modo UC (undetected-chromedriver), Chrome visible, sortea el
    anti-bot de Cloudflare / Turnstile (uc_open_with_reconnect + uc_gui_handle_captcha).
  - Si la tabla de jugadores esta colapsada, cliquea "Show Player Standard Stats".
  - Intenta primero "Share & Export -> Get table as CSV (for Excel)" (clics reales
    sobre el menu del header de #stats_standard). Si el navegador automatizado no
    produce la descarga (el handler suele requerir gesto de usuario real), reconstruye
    el CSV leyendo #stats_standard del DOM, cuyo contenido es el mismo que genera el
    export de FBref.

Salida: csv/uruguay/uruguay_<temporada>.csv  (formato 2 cabeceras tipo FBref),
que luego se unifica con unificar_arg_bra.py a uruguay_2014_2025.csv.

  python descargar_uruguay.py              # las 12 temporadas
  python descargar_uruguay.py --limit 1    # solo la primera (prueba)
"""

import argparse
import base64
import json
import logging
import os
import random
import sys
import time
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CSV_DIR = BASE_DIR / "csv" / "uruguay"
TMP_DIR = CSV_DIR / "_tmp_downloads"
LOG_FILE = BASE_DIR / "download.log"
TABLE_ID = "stats_standard"
SITE = "https://fbref.com"

logger = logging.getLogger("fbref")

USE_SHARE_EXPORT = True  # intenta primero el boton; si falla -> DOM


def setup_logging():
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)


def build_seasons():
    two_year = ["2014-2015", "2015-2016"]
    calendar = [str(y) for y in range(2016, 2026)]
    return two_year + calendar


def build_url(label: str) -> str:
    return f"{SITE}/en/comps/45/{label}/stats/{label}-Liga-AUF-Uruguaya-Stats"


# ---------------------------------------------------------------------------
# helper navegador
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
    """Lee #stats_standard del DOM. Expande celdas colspan (filas de grupo de
    cabecera) y rellena a ancho uniforme, imitando el export de FBref."""
    js = r"""
    var tbl = document.getElementById('stats_standard');
    if (!tbl) return null;
    var rows = tbl.querySelectorAll('tr');
    var data = [];
    var width = 0;
    for (var i = 0; i < rows.length; i++) {
        var cells = rows[i].querySelectorAll('td,th');
        var line = [];
        for (var j = 0; j < cells.length; j++) {
            var cs = parseInt(cells[j].getAttribute('colspan') || '1', 10);
            line.push(cells[j].innerText || '');
            for (var k = 1; k < cs; k++) line.push('');
        }
        if (line.length > width) width = line.length;
        data.push(line);
    }
    for (var i = 0; i < data.length; i++) {
        while (data[i].length < width) data[i].push('');
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


def set_cdp_downloads(sb, path):
    path = str(Path(path).resolve())
    try:
        sb.driver.execute_cdp_cmd("Page.setDownloadBehavior", {
            "behavior": "allow", "downloadPath": path,
        })
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Share & Export -> CSV (intento real)
# ---------------------------------------------------------------------------

def decode_data_uri(uri: str):
    """'data:text/csv;charset=utf-8,<texto>' o ';base64,...' -> str (csv)."""
    if not uri.startswith("data:"):
        return None
    try:
        header, _, payload = uri.partition(",")
        mime = header[5:].split(";")[0].strip().lower()
        if "csv" not in mime and "text" not in mime:
            return None
        if ";base64" in header:
            return base64.b64decode(payload).decode("utf-8", errors="replace")
        return urllib.parse.unquote(payload)
    except Exception:
        return None


def trigger_share_export(sb, timeout: int = 8):
    """Abre 'Share & Export' y cliquea 'Get table as CSV (for Excel)' del header
    de #stats_standard. Devuelve el texto CSV si el navegador lo genera."""
    csv_text = {"value": None}
    try:
        # 1) abrir dropdown "Share & Export" correspondiente a #stats_standard
        opened = sb.execute_script(r"""
        var spans = document.querySelectorAll('.hasmore span');
        for (var i = 0; i < spans.length; i++) {
            var t = (spans[i].textContent || '').trim();
            if (t.indexOf('Share') !== -1 && t.indexOf('Export') !== -1 &&
                spans[i].closest('table') &&
                spans[i].closest('table').id === 'stats_standard') {
                spans[i].click();
                return 'opened';
            }
        }
        return 'no-span';
        """)
        if opened != "opened":
            return None
        sb.sleep(1)

        # 2) instrumentar captura (window.open / anclas download / clipboard)
        sb.execute_script(r"""
        window.__cap = {open: [], dlink: [], blob: null};
        var _w = window.open.bind(window);
        window.open = function(u, t, f) {
            window.__cap.open.push(String(u).slice(0, 400));
            return null;
        };
        var protoClick = HTMLAnchorElement.prototype.click;
        HTMLAnchorElement.prototype.click = function() {
            if (this.download) {
                window.__cap.dlink.push(this.href);
            }
            return protoClick.apply(this, arguments);
        };
        """)

        # 3) etiquetar y llevar al viewport el boton CSV del header correcto
        tagged = sb.execute_script(r"""
        var btns = document.querySelectorAll('button');
        var found = null;
        for (var i = 0; i < btns.length; i++) {
            var t = (btns[i].textContent || '').trim();
            if (t.indexOf('Get table as CSV (for Excel)') !== -1 &&
                btns[i].closest('table') && btns[i].closest('table').id === 'stats_standard') {
                found = btns[i];
                break;
            }
        }
        if (!found) return 'no-button';
        found.id = '__csv_btn';
        found.style.position = 'fixed';
        found.style.left = '30px';
        found.style.top = '300px';
        found.style.zIndex = '999999';
        found.style.visibility = 'visible';
        found.style.opacity = '1';
        return 'tagged';
        """)
        if tagged != "tagged":
            return None
        sb.sleep(1)

        sb.click("#__csv_btn", timeout=12)
        time.sleep(timeout)

        # 4) recoger dlink / datos capturados
        dlink = sb.execute_script(
            "var a = document.getElementById('dlink'); return a ? a.getAttribute('href') : null;"
        )
        cap = sb.execute_script(
            "return window.__cap ? JSON.stringify(window.__cap) : '{}'"
        )
        csv_text["value"] = decode_data_uri(dlink) if dlink else None
        if not csv_text["value"] and cap:
            try:
                c = json.loads(cap)
                for href in c.get("dlink", []) or []:
                    txt = decode_data_uri(href)
                    if txt:
                        csv_text["value"] = txt
                        break
                if csv_text["value"] is None and c.get("open"):
                    raw = c["open"][0]
                    if raw.startswith("data:"):
                        csv_text["value"] = decode_data_uri(raw)
            except Exception:
                pass
    except Exception:
        return None
    return csv_text["value"]


# ---------------------------------------------------------------------------
# escritura CSV
# ---------------------------------------------------------------------------

def write_csv(data, out_path: Path) -> bool:
    def field(value) -> str:
        v = " ".join(str(value).split())
        if "," in v or '"' in v or "\n" in v:
            v = '"' + v.replace('"', '""') + '"'
        return v

    lines = [",".join(field(c) for c in row) for row in data]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return validate_csv(out_path, len(data))


def validate_csv(path: Path, expected_rows: int, min_bytes: int = 200) -> bool:
    if not path.is_file() or path.stat().st_size < min_bytes:
        return False
    head = path.read_bytes()[:4000].decode("utf-8", errors="replace")
    if "Player" not in head:
        return False
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        nrows = sum(1 for _ in fh)
    return nrows >= 3 and nrows >= expected_rows * 0.9


def save_export_text(csv_text, out_path: Path, expected_rows: int) -> bool:
    if not csv_text:
        return False
    try:
        out_path.write_text(csv_text, encoding="utf-8")
    except Exception:
        return False
    return validate_csv(out_path, expected_rows)


# ---------------------------------------------------------------------------
# temporada
# ---------------------------------------------------------------------------

def process_season(sb, label: str, retries: int = 2, use_share_export: bool = True) -> bool:
    url = build_url(label)
    out_path = CSV_DIR / f"uruguay_{label}.csv"
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
                raise RuntimeError("la tabla de jugadores no aparecio (CAPTCHA, URL invalida o temporada sin stats)")

            expected = None
            ok = False

            if use_share_export:
                logger.info(f"[{label}] Share & Export -> Get table as CSV (for Excel)...")
                data = read_table_cells(sb)
                expected = len(data) if data else 3
                csv_text = trigger_share_export(sb)
                if csv_text:
                    ok = save_export_text(csv_text, out_path, expected)
                    logger.info(f"[{label}] export via boton: {ok} ({out_path.stat().st_size if out_path.is_file() else 0} bytes)")

            if not ok:
                data = read_table_cells(sb)
                if not data or len(data) < 3:
                    raise RuntimeError("no se pudieron leer las celdas de la tabla")
                expected = len(data)
                if not write_csv(data, out_path):
                    raise RuntimeError("el CSV generado no supero la validacion")

            logger.info(f"[{label}] OK -> {out_path.name} ({expected} filas, {out_path.stat().st_size} bytes)")
            return True
        except Exception as exc:
            logger.error(f"[{label}] error en intento {attempt}: {exc}")
            if attempt < retries:
                delay = random.uniform(12, 20)
                logger.info(f"[{label}] esperando {delay:.0f}s antes de reintentar")
                sb.sleep(delay)
    return False


def main():
    parser = argparse.ArgumentParser(description="Descarga Player Standard Stats de la Liga AUF Uruguaya (FBref).")
    parser.add_argument("--limit", type=int, default=0, help="Solo las primeras N temporadas (prueba rapida).")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-share-export", action="store_true",
                        help="Saltear el boton Share & Export y usar solo la reconstruccion del DOM.")
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    setup_logging()
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    seasons = build_seasons()
    if args.limit:
        seasons = seasons[: args.limit]
    logger.info(f"Liga AUF Uruguaya (comps/45) | {len(seasons)} temporadas -> {seasons}")

    from seleniumbase import SB

    use_se = USE_SHARE_EXPORT and not args.no_share_export
    results = {}
    with SB(uc=True, headed=not args.headless, locale="en", time_limit=14400) as sb:
        set_cdp_downloads(sb, TMP_DIR)
        n = len(seasons)
        for idx, label in enumerate(seasons):
            results[label] = process_season(sb, label, retries=args.retries, use_share_export=use_se)
            if idx < n - 1:
                delay = random.uniform(8, 15)
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