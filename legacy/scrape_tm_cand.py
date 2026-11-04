# -*- coding: utf-8 -*-
"""
FASE C: scrape de Transfermarkt para la cohorte de delanteros sudamericanos.

Por cada jugador resuelve su pid de Transfermarkt y descarga TODA su carrera
partido a partido (minutos por competicion/temporada) + caps de seleccion mayor.

Salidas en csv/ml/:
  - tm_players.csv        : mapa jugador -> tm_id + caps (estado por jugador, resume)
  - tm_career.csv         : detalle por partido (min, competicion, temporada, club)
  - tm_summary.csv        : agregado por jugador (min elite, puente, etc.)
  - tm_competitions.json  : metadatos de competicion encontrados (cache)
  - tm_classification.csv : reporte de clasificacion por competicion (para auditar)

Uso:
  python scrape_tm_career.py                      # los 783 delanteros
  python scrape_tm_career.py --only-cohorta-madura
  python scrape_tm_career.py --limit 20 --skip 100
  python scrape_tm_career.py --delay 1.0          # politeness
  python scrape_tm_career.py --refresh            # re-descarga todo (ignora estado)
"""

import argparse
import csv
import html as htmllib
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.parse

import requests
import pandas as pd
from rapidfuzz import fuzz

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))
BEST = os.path.join(ROOT, "csv", "ml")
ROSTER = os.path.join(BEST, "tm_candidatos_8594.csv")
PLAYERS_CSV = os.path.join(BEST, "tm_players.csv")
CAREER_CSV = os.path.join(BEST, "tm_career.csv")
SUMMARY_CSV = os.path.join(BEST, "tm_summary.csv")
COMPS_JSON = os.path.join(BEST, "tm_competitions.json")
CLASSIF_CSV = os.path.join(BEST, "tm_classification.csv")

# ---------------- clasificacion de competiciones -------------------
# Codigos de liga de TRANSFERMARKT (top flights de cada pais).
# ELITE: Big Five + Portugal.  PUENTE: resto de Europa (excluye USA/Mexico).
ELITE_LEAGUE_CODES = {"GB1", "ES1", "IT1", "FR1", "L1", "PO1"}
PUENTE_LEAGUE_CODES = {
    "NL1",   # Eredivisie (Paises Bajos)
    "BE1",   # Jupiler Pro League (Belgica)
    "SC1",   # Scottish Premiership (Escocia)
    "TR1",   # Super Lig (Turquia)
    "GR1",   # Super League 1 (Grecia)
    "RU1",   # Premier Liga (Rusia)
    "UKR1",  # Premier Liga (Ucrania)
    "PL1",   # PKO BP Ekstraklasa (Polonia)
    "DK1",   # Superliga (Dinamarca)
    "NO1",   # Eliteserien (Noruega)
    "SE1",   # Allsvenskan (Suecia)
    "FI1",   # Veikkausliiga (Finlandia)
    "RO1",   # SuperLiga (Rumania)
    "AZ1",   # Premyer Liqa (Azerbaiyan)
    "IS1",   # Besta deild (Islandia)
    "SLO1",  # Niké Liga (Eslovaquia)
    "GEO1",  # Umaghlesi Liga (Georgia)
}
# Copas continentales (se reportan por separado, NO suman a elite+puente)
CONTINENTAL_CODES = {"CL", "CLQ", "EL", "ELQ", "CS", "CLI", "UCOL", "ECLQ", "USC", "CWC", "FCWC", "FIC1", "RECO", "USMX", "ACLE", "ACL2", "ACL", "CCL"}
# Selecciones mayores (solo informativo; los caps salen del perfil)
NT_SENIOR_CODES = {"FS", "WMQ1", "WMQ4", "WMQ6", "WMQ", "EMQ", "COPA", "FIWC", "AFT", "CF1", "ASL1", "AFC", "EURO", "CONC", "GOCU", "UNLA", "UNLB", "UNLC", "UNLD", "UNFI", "UNPO", "OLYM", "OLCF", "ACQU", "AU2C", "FARQ", "POWM", "WMQ3", "U17Q", "U19Q", "U21Q", "CNLA", "CNLB", "CNNF"}

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.transfermarkt.com/",
}
TMAPI = "https://tmapi.transfermarkt.technology"


def norm(v):
    s = unicodedata.normalize("NFKD", str(v or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


_META_CACHE = None


def _meta():
    global _META_CACHE
    if _META_CACHE is None:
        _META_CACHE = {}
        if os.path.exists(COMPS_JSON):
            try:
                with open(COMPS_JSON, "r", encoding="utf-8") as f:
                    _META_CACHE = json.load(f)
            except Exception:
                _META_CACHE = {}
    return _META_CACHE


def classify_competition(cid):
    """Devuelve la categoria de una competicion.

    Prioridad: codigos explicitos (top-6 elite, etc.) y luego regla UEFA:
    cualquier 1a division con confederacion UEFA (6) cuenta como 'puente'
    (o 'elite' si su codigo esta en ELITE_LEAGUE_CODES).
    """
    cid = str(cid)
    if cid in ELITE_LEAGUE_CODES:
        return "elite"
    if cid in PUENTE_LEAGUE_CODES:
        return "puente"
    if cid in CONTINENTAL_CODES:
        return "continental"
    if cid in NT_SENIOR_CODES:
        return "seleccion"
    if cid == "KLUB":
        return "amistoso_club"
    m = _meta().get(cid)
    if m and str(m.get("type_id")) == "1" and int(m.get("confederation_id") or 0) == 6:
        return "elite" if cid in ELITE_LEAGUE_CODES else "puente"
    return "otra"


def get_json(url, session, delay, tries=3):
    for it in range(tries):
        try:
            r = session.get(url, headers=HDRS, timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2.0 * (it + 1))
        except requests.RequestException:
            if it == tries - 1:
                raise
            time.sleep(2.0 * (it + 1))
    return None


def get_text(url, session, delay, tries=3):
    for it in range(tries):
        try:
            r = session.get(url, headers=HDRS, timeout=60)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2.0 * (it + 1))
        except requests.RequestException:
            if it == tries - 1:
                raise
            time.sleep(2.0 * (it + 1))
    return None


def search_tm(name, session, delay):
    """Busca en schnellsuche y devuelve [(pid, slug, name)]."""
    q = urllib.parse.quote(name.encode("utf-8"))
    html = get_text(f"https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche?query={q}", session, delay)
    time.sleep(delay + random.uniform(0.1, 0.4))
    if html is None:
        raise RuntimeError("schnellsuche: sin respuesta")
    out = []
    for m in re.finditer(r'<a[^>]+href="/([^"/]+)/profil/spieler/(\d+)"[^>]*>([^<]+)</a>', html):
        slug, pid, nm = m.groups()
        out.append((pid, slug, htmllib.unescape(nm).strip()))
    return out


def player_birth(pid, session, delay):
    """Fecha de nacimiento del pid via /player/{id} (para pin de desambiguacion)."""
    d = get_json(f"{TMAPI}/player/{pid}", session, delay)
    time.sleep(delay + random.uniform(0.1, 0.4))
    if d and d.get("data"):
        return d["data"].get("lifeDates", {}).get("dateOfBirth")
    return None


def choose_pid(nname, born, cands, session=None, delay=0.0):
    """Elige el mejor candidato por similitud de nombre (+ pin por nacimiento)."""
    if not cands:
        return None, "no_match"
    scored = []
    for pid, slug, nm in cands:
        ratio = fuzz.WRatio(nname, norm(nm))
        scored.append((ratio, nm, pid, slug))
    scored.sort(key=lambda x: -x[0])
    best = scored[0]
    if best[0] < 82:
        return None, "no_match"
    if len(scored) > 1 and best[0] - scored[1][0] <= 8:
        # ambiguedad -> pin por fecha de nacimiento entre los 2 mejores
        for ratio, nm, pid, slug in scored[:2]:
            dob = player_birth(pid, session, delay)
            by = int(dob[:4]) if dob else None
            if by and abs(by - int(born or 0)) <= 1:
                return (pid, slug, nm), "mapped"
        return None, "ambiguous"
    return (best[2], best[3], best[1]), "mapped"


def career_birth_hint(perfs):
    """Nacimiento estimado = min(temporada - edad en partido)."""
    years = []
    for p in perfs:
        gi = p["gameInformation"]
        age = (p.get("statistics", {}).get("generalStatistics", {}) or {}).get("age")
        sid = gi.get("seasonId")
        if age is not None and sid:
            years.append(int(sid) - int(age))
    return min(years) if years else None


def fetch_performance(pid, session, delay):
    data = get_json(f"{TMAPI}/player/{pid}/performance-game", session, delay)
    time.sleep(delay + random.uniform(0.1, 0.4))
    if data is None:
        raise RuntimeError(f"performance-game {pid}: sin respuesta")
    if not data.get("data"):
        return []
    return data["data"].get("performance") or []


def fetch_comps(pid, perfs, session, delay):
    """Recolecta metadata de competiciones -> {cid: {...}} (cache global)."""
    meta = {}
    if os.path.exists(COMPS_JSON):
        with open(COMPS_JSON, "r", encoding="utf-8") as f:
            meta = json.load(f)
    for p in perfs:
        cid = p["gameInformation"].get("competitionId")
        if not cid or cid in meta:
            continue
        d = get_json(f"{TMAPI}/competition/{cid}", session, delay)
        time.sleep(delay + random.uniform(0.1, 0.4))
        if d and d.get("data"):
            dd = d["data"]
            meta[cid] = {
                "name": dd.get("name"),
                "type_id": dd.get("typeId"),
                "country_id": dd.get("originDetails", {}).get("countryId"),
                "confederation_id": dd.get("originDetails", {}).get("confederationId"),
                "relative_url": dd.get("relativeUrl"),
            }
        else:
            meta[cid] = {"name": None, "type_id": None, "country_id": None, "confederation_id": None, "relative_url": None}
        with open(COMPS_JSON, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
    return meta


def fetch_caps(pid, slug, session, delay):
    """Caps/goals de seleccion mayor desde el perfil: 'Caps/Goals: 84 / 40'."""
    html = get_text(f"https://www.transfermarkt.com/{slug}/profil/spieler/{pid}", session, delay)
    time.sleep(delay + random.uniform(0.1, 0.4))
    if html is None:
        raise RuntimeError(f"profil {pid} ({slug}): sin respuesta")
    i = html.find("Caps/Goals:")
    if i == -1:
        return 0, 0
    seg = re.sub(r"<[^>]+>", " ", html[i:i + 500])
    m = re.search(r"Caps/Goals:\s*(\d+)\s*/\s*(\d+)", seg)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def load_roster(only_cohorta):
    df = pd.read_csv(ROSTER)
    if only_cohorta:
        df = df[df["cohort_mature"] == 1]
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "pid_global": str(r["player_id_global"] if "player_id_global" in r else r["pid"]),
            "player": str(r["player"]),
            "born": r["born"],
        })
    rows.sort(key=lambda x: x["pid_global"])
    return rows


def read_state():
    state = {}
    if os.path.exists(PLAYERS_CSV):
        with open(PLAYERS_CSV, "r", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                state[r["player_id_global"]] = r
    return state


def write_players(rows):
    cols = ["player_id_global", "player", "born", "tm_id", "tm_slug", "tm_name", "tm_born",
            "caps", "nt_goals", "status", "n_games", "note"]
    newf = not os.path.exists(PLAYERS_CSV)
    with open(PLAYERS_CSV, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if newf:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def write_career(rows):
    cols = ["player_id_global", "tm_id", "season", "date", "competition_id",
            "competition_name", "competition_type_id", "is_national_game",
            "club_id", "minutes", "goals", "assists", "category"]
    newf = not os.path.exists(CAREER_CSV)
    with open(CAREER_CSV, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if newf:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def purge_career(pid_global_head):
    if not os.path.exists(CAREER_CSV):
        return
    keep = []
    with open(CAREER_CSV, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["player_id_global"] != pid_global_head:
                keep.append(r)
    cols = None
    if keep:
        cols = list(keep[0].keys())
    with open(CAREER_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols) if cols else csv.writer(f)
        if cols:
            w.writeheader()
            w.writerows(keep)


def build_player(rec, state, session, delay):
    """Devuelve (player_row, career_rows) o player_row con estado de error."""
    nname = norm(rec["player"])
    # --- resolucion del pid
    if rec["pid_global"] in state and state[rec["pid_global"]].get("tm_id"):
        pid = state[rec["pid_global"]]["tm_id"]
        slug = state[rec["pid_global"]].get("tm_slug", "")
        tm_name = state[rec["pid_global"]].get("tm_name", "")
        mapped = False
    else:
        cands = search_tm(rec["player"], session, delay)
        pick, status = choose_pid(nname, rec["born"], cands, session, delay)
        if status in ("ambiguous", "no_match"):
            return ({"player_id_global": rec["pid_global"], "player": rec["player"], "born": rec["born"],
                     "tm_id": "", "tm_slug": "", "tm_name": "", "tm_born": "", "caps": "", "nt_goals": "",
                     "status": status, "n_games": 0, "note": f"candidatos={len(cands)}"}), []
        pid, slug, tm_name = pick
        mapped = True

    # --- performance-game (carrera completa)
    perfs = fetch_performance(pid, session, delay)
    meta = fetch_comps(pid, perfs, session, delay)

    career = []
    for p in perfs:
        gi = p["gameInformation"]
        st = p.get("statistics", {})
        mins = st.get("playingTimeStatistics", {}).get("playedMinutes") or 0
        if mins <= 0:
            continue
        goals = st.get("goalStatistics", {}).get("goalsScoredTotal") or 0
        assists = st.get("goalStatistics", {}).get("assists") or 0
        cid = gi.get("competitionId") or ""
        career.append({
            "player_id_global": rec["pid_global"], "tm_id": pid,
            "season": (gi.get("season") or {}).get("display") or str(gi.get("seasonId")),
            "date": ((gi.get("date") or {}).get("dateTimeUTC") or ""),
            "competition_id": cid,
            "competition_name": (meta.get(cid) or {}).get("name") or "",
            "competition_type_id": gi.get("competitionTypeId"),
            "is_national_game": gi.get("isNationalGame"),
            "club_id": (p.get("clubsInformation", {}).get("club", {}) or {}).get("clubId") or "",
            "minutes": mins, "goals": goals, "assists": assists,
            "category": classify_competition(cid),
        })

    # --- validacion ligera: nacimiento estimado desde la carrera
    hint = career_birth_hint(perfs)
    note = f"matched={tm_name}"
    if hint:
        note += f" birth_hint={hint}"
    if not mapped:
        note += " (resumido)"

    # --- caps desde el perfil
    caps, nt_goals = fetch_caps(pid, slug, session, delay)

    prow = {
        "player_id_global": rec["pid_global"], "player": rec["player"], "born": rec["born"],
        "tm_id": pid, "tm_slug": slug, "tm_name": tm_name, "tm_born": "",
        "caps": caps, "nt_goals": nt_goals,
        "status": "ok" if perfs else "no_career", "n_games": len(career),
        "note": note,
    }
    return prow, career


def recompute_summary():
    if not os.path.exists(PLAYERS_CSV):
        return None
    players = pd.read_csv(PLAYERS_CSV, dtype=str).fillna("")
    if not os.path.exists(CAREER_CSV):
        return None
    car = pd.read_csv(CAREER_CSV, dtype={"player_id_global": str})
    car["category"] = car["competition_id"].map(classify_competition)

    elite = car.loc[car["category"] == "elite", "minutes"].groupby(car["player_id_global"]).sum()
    puente = car.loc[car["category"] == "puente", "minutes"].groupby(car["player_id_global"]).sum()
    cont = car.loc[car["category"] == "continental", "minutes"].groupby(car["player_id_global"]).sum()
    nt_m = car.loc[car["category"] == "seleccion", "minutes"].groupby(car["player_id_global"]).sum()
    g = car.groupby("player_id_global")

    out = []
    for _, r in players.iterrows():
        pid = r["player_id_global"]
        el = float(elite.get(pid, 0)); pu = float(puente.get(pid, 0))
        nt = float(nt_m.get(pid, 0)); ct = float(cont.get(pid, 0))
        subs = g.get_group(pid) if pid in g.groups else None
        out.append({
            "player_id_global": pid, "player": r["player"], "born": r["born"],
            "tm_id": r["tm_id"], "caps": r["caps"], "nt_goals": r["nt_goals"],
            "tm_min_elite": round(el), "tm_min_puente": round(pu),
            "tm_min_elite_puente": round(el + pu), "tm_min_continental": round(ct),
            "tm_min_seleccion": round(nt),
            "tm_n_games": int(len(subs)) if subs is not None else 0,
        }, )
    df = pd.DataFrame(out)
    df.to_csv(SUMMARY_CSV, index=False, encoding="utf-8")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-cohorta-madura", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.6)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    if args.summary_only:
        df2 = recompute_summary()
        if df2 is not None:
            nz = df2[df2["tm_min_elite_puente"] > 0]
            print(f"[FASE C] summary -> {SUMMARY_CSV}")
            print(f"  jugadores con min elite+puente > 0: {len(nz)} / {len(df2)}")
            if len(nz):
                print(f"  mediana min elite+puente (solo >0): {nz['tm_min_elite_puente'].median():.0f}")
            print(f"  jugadores con caps >= 15: {(pd.to_numeric(df2['caps'], errors='coerce').fillna(0) >= 15).sum()}")
            print(f"  jugadores con caps >= 30: {(pd.to_numeric(df2['caps'], errors='coerce').fillna(0) >= 30).sum()}")
        report_classification()
        return

    roster = load_roster(args.only_cohorta_madura)
    if args.skip:
        roster = roster[args.skip:]
    if args.limit:
        roster = roster[:args.limit]
    state = read_state() if not args.refresh else {}
    if args.refresh:
        for f in (CAREER_CSV,):
            if os.path.exists(f):
                os.remove(f)

    career_ids = set()
    if os.path.exists(CAREER_CSV):
        with open(CAREER_CSV, "r", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                career_ids.add(r["player_id_global"])

    session = requests.Session()
    session.headers.update(HDRS)

    done = skipped = errs = 0
    t0 = time.time()
    print(f"[FASE C] jugadores a procesar: {len(roster)}  (delay={args.delay}s)")
    for i, rec in enumerate(roster, 1):
        pidg = rec["pid_global"]
        if pidg in state and not args.refresh and state[pidg].get("status") in ("ok", "no_career", "no_match", "ambiguous"):
            skipped += 1
            continue
        try:
            if not args.refresh and pidg in career_ids:
                purge_career(pidg)
            prow, career = build_player(rec, state, session, args.delay)
            write_players([prow])
            if career:
                write_career(career)
            done += 1
            flag = "" if prow["status"] == "ok" else f" ({prow['status']})"
            print(f"  [{i}/{len(roster)}] {rec['player']} -> tm {prow['tm_id']} "
                  f"caps={prow['caps']} partidos={len(career)}{flag}")
        except KeyboardInterrupt:
            print("\ninterrumpido; el estado se conserva")
            break
        except Exception as e:
            errs += 1
            prev = state.get(pidg, {})
            write_players([{"player_id_global": pidg, "player": rec["player"], "born": rec["born"],
                            "tm_id": prev.get("tm_id", ""), "tm_slug": prev.get("tm_slug", ""),
                            "tm_name": prev.get("tm_name", ""), "tm_born": prev.get("tm_born", ""),
                            "caps": prev.get("caps", ""), "nt_goals": prev.get("nt_goals", ""),
                            "status": "error", "n_games": 0, "note": repr(e)[:200]}])
            print(f"  [{i}/{len(roster)}] ERROR {rec['player']}: {e!r}")

    print(f"\n[FASE C] ok={done} skip={skipped} errores={errs}  tiempo={time.time()-t0:.0f}s")

    df = recompute_summary()
    if df is not None:
        nz = df[df["tm_min_elite_puente"] > 0]
        print(f"\n[FASE C] summary -> {SUMMARY_CSV}")
        print(f"  jugadores con min elite+puente > 0: {len(nz)} / {len(df)}")
        if len(nz):
            print(f"  mediana min elite+puente (solo >0): {nz['tm_min_elite_puente'].median():.0f}")
        print(f"  jugadores con caps >= 15: {(pd.to_numeric(df['caps'], errors='coerce').fillna(0) >= 15).sum()}")
        print(f"  jugadores con caps >= 30: {(pd.to_numeric(df['caps'], errors='coerce').fillna(0) >= 30).sum()}")

    report_classification()


def report_classification():
    if not os.path.exists(COMPS_JSON):
        return
    with open(COMPS_JSON, "r", encoding="utf-8") as f:
        meta = json.load(f)
    rows = []
    for cid, m in sorted(meta.items()):
        rows.append({"competition_id": cid, "name": m.get("name"), "type_id": m.get("type_id"),
                     "country_id": m.get("country_id"), "category": classify_competition(cid)})
    pd.DataFrame(rows).to_csv(CLASSIF_CSV, index=False, encoding="utf-8")
    nclass = [r for r in rows if r["category"] == "otra"]
    print(f"\n[FASE C] clasificacion -> {CLASSIF_CSV}")
    if nclass:
        print("  competiciones SIN clasificar (revisar y ampliar set si es liga europea):")
        for r in nclass:
            print(f"    {r['competition_id']} - {r['name']} (type={r['type_id']})")


if __name__ == "__main__":
    main()