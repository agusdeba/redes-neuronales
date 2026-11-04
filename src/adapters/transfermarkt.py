"""Transfermarkt: identidad, posicion, carrera partido a partido, caps, planteles, transferencias.

Basado en scrape_tm_career.py (endpoints tmapi probados por el usuario), con:
  - cliente HTTP responsable (cache, manifest, backoff, Retry-After, circuit breaker);
  - perfil HTML parseado completo (DOB, nacionalidades, posicion principal/secundarias,
    pie, altura, caps, retiro);
  - partidos con 0 minutos conservados (convocatorias) y marcados;
  - juveniles separados de mayores;
  - planteles por club/temporada para enumerar la cohorte (semilla de ligas).

Los parsers HTML son defensivos: si TM cambia el markup, el campo queda nulo y se
registra, nunca se inventa.
"""
from __future__ import annotations

import html as htmllib
import re
import urllib.parse
from datetime import datetime

from bs4 import BeautifulSoup

from ..common import store
from ..common.config import cohort
from ..common.http import PoliteClient, manifest
from ..common.logs import get_logger
from ..common.textnorm import norm_name

WEB = "https://www.transfermarkt.com"
TMAPI = "https://tmapi.transfermarkt.technology"

DATE_PATTERNS = ("%b %d, %Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %b %Y", "%B %d, %Y")


def parse_date(s: str | None) -> str | None:
    if not s:
        return None
    s = re.sub(r"\(.*?\)", "", htmllib.unescape(s)).strip()
    for f in DATE_PATTERNS:
        try:
            return datetime.strptime(s, f).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def flatten(d, prefix="") -> dict:
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(d, list):
        out[prefix[:-1]] = d
    else:
        out[prefix[:-1]] = d
    return out


def pick(flat: dict, *needles, default=None):
    """Primer valor cuya clave (minusculas) contiene todas las agujas."""
    for k, v in flat.items():
        kl = k.lower()
        if all(n in kl for n in needles) and v is not None:
            return v
    return default


# --------------------------------------------------------------------- parsers
def parse_search(html: str) -> list[dict]:
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="/([^"/]+)/profil/spieler/(\d+)"[^>]*>([^<]+)</a>', html):
        slug, pid, nm = m.groups()
        if pid in seen:
            continue
        seen.add(pid)
        out.append({"tm_id": pid, "slug": slug, "name": htmllib.unescape(nm).strip()})
    return out


def parse_profile(html: str) -> dict:
    """Perfil de jugador. Lee la tabla 'info-table' (label -> valor) y el bloque de posiciones."""
    soup = BeautifulSoup(html, "lxml")
    info: dict[str, str] = {}
    for lab in soup.select("span.info-table__content--regular"):
        val = lab.find_next_sibling("span")
        if val is not None:
            info[" ".join(lab.get_text(" ").split()).rstrip(":").lower()] = " ".join(val.get_text(" ").split())
    nat_tags = []
    for lab in soup.select("span.info-table__content--regular"):
        if "citizenship" in lab.get_text().lower():
            val = lab.find_next_sibling("span")
            if val is not None:
                nat_tags = [img.get("title") for img in val.select("img[title]")]
    text = " ".join(soup.get_text(" ").split())

    def grab(label_regex):
        m = re.search(label_regex, text, flags=re.I)
        return m.group(1).strip() if m else None

    main_pos, other = None, []
    for b in soup.select(".detail-position__box"):
        t = " ".join(b.get_text(" ").split()).lower()
        vals = [" ".join(x.get_text(" ").split()) for x in b.select("dd")]
        if t.startswith("main position") and vals:
            main_pos = vals[0]
        elif t.startswith("other position"):
            other = vals
    if not main_pos:
        main_pos = grab(r"Main position:\s*([A-Z][A-Za-z\-]+(?: [A-Z][a-z]+)?)")
    caps = goals = None
    mc = re.search(r"Caps/Goals:\s*(\d+)\s*/\s*(\d+)", text)
    if mc:
        caps, goals = int(mc.group(1)), int(mc.group(2))
    h1 = soup.select_one("h1")
    name = " ".join(h1.get_text(" ").split()) if h1 else None
    if name:
        name = re.sub(r"^#\d+\s*", "", name)
    dob_txt = info.get("date of birth/age") or info.get("date of birth") or grab(r"Date of birth/Age:\s*([A-Za-z0-9,/. ]+?\(\d+\))")
    height = info.get("height")
    hm = re.search(r"(\d)[,.](\d{2})", height or "")
    return {
        "name": name,
        "full_name": info.get("name in home country") or info.get("full name"),
        "dob": parse_date(dob_txt),
        "place_of_birth": info.get("place of birth"),
        "citizenship": nat_tags or ([info["citizenship"]] if info.get("citizenship") else []),
        "position_raw": info.get("position"),
        "position_main": main_pos,
        "position_other": other,
        "foot": info.get("foot"),
        "height_cm": int(hm.group(1)) * 100 + int(hm.group(2)) if hm else None,
        "current_club": info.get("current club"),
        "retired_since": parse_date(info.get("retired since")) if info.get("retired since") else None,
        "caps_profile": caps,           # None = no aparece en el perfil (no es lo mismo que 0)
        "nt_goals_profile": goals,
        "caps_parsed": mc is not None,
    }


def parse_league_clubs(html: str, season: int) -> list[dict]:
    out, seen = [], set()
    pat = re.compile(r'href="/([^"/]+)/startseite/verein/(\d+)(?:/saison_id/(\d+))?"[^>]*>([^<]*)<')
    for slug, cid, sid, nm in pat.findall(html):
        if cid in seen or (sid and int(sid) != season):
            continue
        seen.add(cid)
        out.append({"club_id": cid, "club_slug": slug, "club_name": htmllib.unescape(nm).strip() or slug})
    return out


def parse_squad(html: str) -> list[dict]:
    """Plantel (club o seleccion). Una fila por jugador con id, nombre, posicion, DOB, nacionalidades."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    table = soup.select_one("table.items")
    if table is None:
        return rows
    for tr in table.select("tbody > tr"):
        if "odd" not in (tr.get("class") or []) and "even" not in (tr.get("class") or []):
            continue
        a = tr.select_one('a[href*="/profil/spieler/"]')
        if a is None:
            continue
        m = re.search(r"/([^/]+)/profil/spieler/(\d+)", a.get("href", ""))
        if not m:
            continue
        inline = tr.select("table.inline-table tr")
        position = None
        if len(inline) >= 2:
            position = " ".join(inline[-1].get_text(" ").split()) or None
        dob = None
        for td in tr.select("td.zentriert"):
            d = parse_date(td.get_text(" ").strip())
            if d:
                dob = d
                break
        nats = [img.get("title") for img in tr.select("img.flaggenrahmen[title]")]
        rows.append({"tm_id": m.group(2), "slug": m.group(1), "name": " ".join(a.get_text(" ").split()),
                     "position": position, "dob": dob, "nationalities": nats})
    return rows


class TransfermarktAdapter:
    source = "transfermarkt"

    def __init__(self, refresh=False, offline=False):
        self.http = PoliteClient(self.source, refresh=refresh, offline=offline)
        self.log = get_logger("adapter.transfermarkt")
        self.cfg = cohort()

    # ------------------------------------------------------------- endpoints
    def search(self, name: str) -> list[dict]:
        q = urllib.parse.quote(name.encode("utf-8"))
        r = self.http.get(f"{WEB}/schnellsuche/ergebnis/schnellsuche?query={q}")
        return parse_search(r.text) if r.ok else []

    def profile(self, tm_id: str, slug: str = "x"):
        r = self.http.get(f"{WEB}/{slug or 'x'}/profil/spieler/{tm_id}")
        if not r.ok:
            return None, r
        return parse_profile(r.text), r

    def api_player(self, tm_id: str):
        r = self.http.get(f"{TMAPI}/player/{tm_id}")
        return (r.json().get("data") if r.ok else None), r

    def performance(self, tm_id: str):
        r = self.http.get(f"{TMAPI}/player/{tm_id}/performance-game")
        if not r.ok:
            return [], r
        data = r.json().get("data") or {}
        return data.get("performance") or [], r

    def competition(self, cid: str):
        r = self.http.get(f"{TMAPI}/competition/{cid}")
        return (r.json().get("data") if r.ok else None), r

    def transfers(self, tm_id: str):
        r = self.http.get(f"{WEB}/ceapi/transferHistory/list/{tm_id}")
        if not r.ok:
            return [], r
        try:
            return r.json().get("transfers") or [], r
        except ValueError:
            return [], r

    def league_clubs(self, code: str, season: int):
        r = self.http.get(f"{WEB}/x/startseite/wettbewerb/{code}/plus/?saison_id={season}")
        return (parse_league_clubs(r.text, season) if r.ok else []), r

    def squad(self, club_id: str, season: int):
        r = self.http.get(f"{WEB}/x/kader/verein/{club_id}/saison_id/{season}/plus/1")
        return (parse_squad(r.text) if r.ok else []), r

    # ------------------------------------------------------------- semillas
    def seed_leagues(self, countries: list[str], season_from: int, season_to: int, limit_clubs=None):
        """Semilla 3: todos los jugadores de planteles de 1a division (cualquier posicion;
        la posicion se filtra despues)."""
        m = manifest()
        for c in countries:
            for code in self.cfg["countries"][c]["tm_league_codes"]:
                for y in range(season_from, season_to + 1):
                    item = f"{code}_{y}"
                    if m.task_status("tm_league_seed", item) == "done" and not self.http.refresh:
                        continue
                    clubs, r = self.league_clubs(code, y)
                    if limit_clubs:
                        clubs = clubs[:limit_clubs]
                    recs = []
                    for cl in clubs:
                        sq, r2 = self.squad(cl["club_id"], y)
                        for p in sq:
                            recs.append({**p, "club_id": cl["club_id"], "club_name": cl["club_name"],
                                         "league_code": code, "season": y, "country": c,
                                         "seed": "tm_league", **r2.provenance()})
                    store.write_item(self.source, "squads", item, recs)
                    m.set_task("tm_league_seed", item, "done", f"{len(clubs)} clubes, {len(recs)} jugadores")
                    self.log.info(f"{item}: {len(clubs)} clubes, {len(recs)} jugadores")

    def seed_national_teams(self, countries: list[str], season_from: int, season_to: int):
        """Semilla 4: planteles de seleccion mayor por temporada."""
        m = manifest()
        for c in countries:
            ntid = self.cfg["countries"][c].get("tm_national_team_id")
            if not ntid:
                continue
            for y in range(season_from, season_to + 1):
                item = f"NT_{c}_{y}"
                if m.task_status("tm_nt_seed", item) == "done" and not self.http.refresh:
                    continue
                sq, r = self.squad(str(ntid), y)
                recs = [{**p, "club_id": str(ntid), "club_name": f"Seleccion {c}", "season": y,
                         "country": c, "seed": "tm_national_team", **r.provenance()} for p in sq]
                store.write_item(self.source, "nt_squads", item, recs)
                m.set_task("tm_nt_seed", item, "done", f"{len(recs)} jugadores")

    # ------------------------------------------------------------- resolver por nombre
    def resolve(self, name: str, birth_year: int | None, dob: str | None = None) -> dict:
        """Busca un tm_id por nombre. Exige confirmacion por fecha/anio de nacimiento:
        nunca acepta un candidato solo por nombre (bug del script anterior)."""
        from rapidfuzz import fuzz
        cands = self.search(name)
        scored = sorted(((fuzz.WRatio(norm_name(name), norm_name(c["name"])), c) for c in cands),
                        key=lambda x: -x[0])
        confirmed = []
        for score, c in scored[:4]:
            if score < 85:
                break
            prof, _ = self.profile(c["tm_id"], c["slug"])
            pdob = (prof or {}).get("dob")
            if dob and pdob == dob:
                confirmed.append((score, c, "dob_exact"))
            elif not dob and birth_year and pdob and abs(int(pdob[:4]) - int(birth_year)) == 0:
                confirmed.append((score, c, "birth_year"))
        if len(confirmed) == 1:
            s, c, how = confirmed[0]
            return {"status": "mapped", "tm_id": c["tm_id"], "slug": c["slug"], "score": s, "method": how}
        if len(confirmed) > 1:
            return {"status": "ambiguous", "candidates": [c["tm_id"] for _, c, _ in confirmed]}
        return {"status": "no_match", "candidates": [c["tm_id"] for _, c in scored[:4]]}

    # ------------------------------------------------------------- carrera completa
    def fetch_player(self, tm_id: str, slug: str = "x", with_transfers: bool = True) -> dict:
        """Descarga perfil + carrera partido a partido + metadata de competiciones + transferencias.
        Escribe interim/transfermarkt/{profile,matches,transfers}/<tm_id>.json."""
        prof, rp = self.profile(tm_id, slug)
        api, ra = self.api_player(tm_id)
        prof = prof or {}
        if api:
            fa = flatten(api)
            prof.setdefault("api_name", pick(fa, "name"))
            api_dob = pick(fa, "dateofbirth")
            if api_dob and not prof.get("dob"):
                prof["dob"] = str(api_dob)[:10]
        store.write_item(self.source, "profile", tm_id, [{"tm_id": tm_id, "slug": slug, **prof, **rp.provenance()}])

        perfs, rperf = self.performance(tm_id)
        comps = {}
        rows = []
        for p in perfs:
            gi = p.get("gameInformation") or {}
            st = p.get("statistics") or {}
            fs = flatten(st)
            cid = gi.get("competitionId") or ""
            if cid and cid not in comps:
                comps[cid] = self.competition_meta(cid)
            club = (p.get("clubsInformation") or {}).get("club") or {}
            opp = (p.get("clubsInformation") or {}).get("opponent") or {}
            rows.append({
                "tm_id": tm_id,
                "game_id": gi.get("gameId"),
                "date": ((gi.get("date") or {}).get("dateTimeUTC") or "")[:10] or None,
                "season_id": gi.get("seasonId"),
                "season": (gi.get("season") or {}).get("display") or gi.get("seasonId"),
                "competition_id": cid,
                "competition_type_id": gi.get("competitionTypeId"),
                "is_national_game": gi.get("isNationalGame"),
                "club_id": club.get("clubId"),
                "opponent_id": opp.get("clubId"),
                "home_away": "home" if gi.get("isHomeGame") is True else ("away" if gi.get("isHomeGame") is False else None),
                "minutes": pick(fs, "playedminutes", default=0) or 0,
                "goals": pick(fs, "goalsscoredtotal", default=0) or 0,
                "assists": pick(fs, "assists", default=0) or 0,
                "yellow": pick(fs, "yellow"),
                "red": pick(fs, "red"),
                "is_starting": pick(fs, "starting"),
                "position_played": pick(fs, "position"),
                "age": pick(fs, "age"),
                "participation": pick(fs, "participation") or pick(fs, "state"),
                **rperf.provenance(),
            })
        store.write_item(self.source, "matches", tm_id, rows)
        if with_transfers:
            tr, rt = self.transfers(tm_id)
            trows = [{"tm_id": tm_id, "date": t.get("dateUnformatted") or parse_date(t.get("date")),
                      "season": t.get("season"),
                      "from_club": (t.get("from") or {}).get("clubName"),
                      "to_club": (t.get("to") or {}).get("clubName"),
                      "fee": t.get("fee"), "is_loan": "loan" in str(t.get("fee", "")).lower(),
                      **rt.provenance()} for t in tr]
            store.write_item(self.source, "transfers", tm_id, trows)
        return {"profile": prof, "n_matches": len(rows)}

    def competition_meta(self, cid: str) -> dict:
        cached = store.read_item(self.source, "competitions", cid)
        if cached:
            return cached[0]
        d, r = self.competition(cid)
        d = d or {}
        rec = {"competition_id": cid, "name": d.get("name"), "type_id": d.get("typeId"),
               "country_id": (d.get("originDetails") or {}).get("countryId"),
               "confederation_id": (d.get("originDetails") or {}).get("confederationId"),
               "relative_url": d.get("relativeUrl"), **r.provenance()}
        store.write_item(self.source, "competitions", cid, [rec])
        return rec
