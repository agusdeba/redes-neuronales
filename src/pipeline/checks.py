"""check-config: verifica en vivo (pocas requests) los codigos de liga TM, ids de seleccion y
competiciones FBref configurados, e imprime lo que devuelve cada fuente."""
from __future__ import annotations

from ..common.config import cohort, load_yaml
from ..common.http import SourceBlocked, SourceDown


def check_config():
    from ..adapters.transfermarkt import TransfermarktAdapter
    tm = TransfermarktAdapter()
    c = cohort()
    print("== Transfermarkt: codigos de liga y selecciones ==")
    for code, cfg in c["countries"].items():
        for lc in cfg["tm_league_codes"]:
            try:
                meta = tm.competition_meta(lc)
                clubs, _ = tm.league_clubs(lc, 2015)
                print(f"  {code} liga {lc}: nombre={meta.get('name')!r} pais_id={meta.get('country_id')} clubes_2015={len(clubs)}")
            except (SourceBlocked, SourceDown) as e:
                print("  TM detenido:", e)
                return
        sq, _ = tm.squad(str(cfg["tm_national_team_id"]), 2015)
        print(f"  {code} seleccion {cfg['tm_national_team_id']}: {len(sq)} jugadores en 2015 (ej: {[p['name'] for p in sq[:3]]})")
    print("== FBref: una temporada por competicion ==")
    from ..adapters.fbref import FBrefAdapter, build_url, parse_stats_table, seasons_for
    fb = FBrefAdapter()
    for key, cfg in load_yaml("fbref_competitions.yaml")["competitions"].items():
        s = seasons_for(cfg)[-2]
        try:
            r = fb.http.get(build_url(cfg, s))
            print(f"  {key} {s}: HTTP {r.status}, filas={len(parse_stats_table(r.text)) if r.ok else 0}")
        except SourceBlocked as e:
            print("  FBref BLOQUEADO (no se evade):", e)
            break
