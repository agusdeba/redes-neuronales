"""Extremo a extremo con datos sinteticos en interim: normalize -> features -> targets -> validate -> report.
Verifica: sin duplicados, idempotencia, filtro de posicion, separacion juveniles/mayores, umbral 1000 min."""
import pandas as pd

from src.common import store
from src.pipeline import features, normalize, report, targets, validate

PROV = {"source_url": "https://example.org", "retrieved_at": "2026-11-04T00:00:00Z", "raw_ref": "x"}


def match(tm_id, date, season, comp, club, minutes, goals=0, nt=False, opp="9"):
    return {"tm_id": tm_id, "game_id": f"{tm_id}{date}", "date": date, "season_id": season, "season": season,
            "competition_id": comp, "competition_type_id": 1, "is_national_game": nt, "club_id": club,
            "opponent_id": opp, "home_away": "home", "minutes": minutes, "goals": goals, "assists": 0,
            "yellow": 0, "red": 0, "is_starting": minutes >= 60, "position_played": None, "age": None,
            "participation": None, "source": "transfermarkt", **PROV}


def seed_interim():
    store.write_item("wikidata", "players", "PAR_1990", [
        {"qid": "Q1", "name": "Juan Pérez", "dob": "1990-03-05", "birth_year": 1990, "dob_confidence": "exact",
         "nationality": "PAR", "positions": ["forward"], "aliases": [], "tm_id": "111", "fbref_id": "abcd1234",
         "nft_id": None, "source": "wikidata", **PROV},
        {"qid": "Q2", "name": "Pedro Gómez", "dob": "1991-01-02", "birth_year": 1991, "dob_confidence": "exact",
         "nationality": "PAR", "positions": ["defender"], "aliases": [], "tm_id": "222", "source": "wikidata", **PROV},
        {"qid": "Q9", "name": "Viejo", "dob": "1975-01-01", "birth_year": 1975, "dob_confidence": "exact",
         "nationality": "PAR", "positions": ["forward"], "aliases": [], "source": "wikidata", **PROV},
    ])
    store.write_item("transfermarkt", "squads", "PR1A_2010", [
        {"tm_id": "111", "name": "Juan Pérez", "position": "Centre-Forward", "dob": "1990-03-05", "nationalities": ["Paraguay"],
         "club_id": "500", "club_name": "Olimpia", "season": 2010, "country": "PAR", "seed": "tm_league", **PROV},
        {"tm_id": "333", "name": "Luis Díaz", "position": "Attacking Midfield", "dob": "1992-07-07",
         "nationalities": ["Paraguay"], "club_id": "500", "club_name": "Olimpia", "season": 2010, "country": "PAR",
         "seed": "tm_league", **PROV},
    ])
    store.write_item("transfermarkt", "profile", "111", [
        {"tm_id": "111", "slug": "juan-perez", "name": "Juan Pérez", "dob": "1990-03-05", "citizenship": ["Paraguay"],
         "position_main": "Centre-Forward", "position_other": [], "caps_profile": 24, "nt_goals_profile": 7,
         "caps_parsed": True, **PROV}])
    store.write_item("transfermarkt", "competitions", "PR1A", [{"competition_id": "PR1A", "name": "Primera Division", "type_id": 1, "country_id": 133, "confederation_id": 2}])
    store.write_item("transfermarkt", "competitions", "ES1", [{"competition_id": "ES1", "name": "LaLiga", "type_id": 1, "country_id": 157, "confederation_id": 6}])
    store.write_item("transfermarkt", "competitions", "FS", [{"competition_id": "FS", "name": "Friendlies", "type_id": 4, "country_id": None, "confederation_id": None}])
    store.write_item("transfermarkt", "competitions", "U21Q", [{"competition_id": "U21Q", "name": "U21", "type_id": 4}])
    rows = [match("111", f"2009-0{m}-10", "2009", "PR1A", "500", 90, 1) for m in range(1, 10)]          # 810 min a los 19
    rows += [match("111", f"2011-0{m}-10", "2011", "PR1A", "500", 45) for m in range(1, 6)]             # +225
    rows += [match("111", f"2014-0{m}-10", "13/14", "ES1", "600", 90) for m in range(1, 9)] * 1        # elite (24 anios)
    rows += [match("111", "2012-06-01", "2012", "FS", "3581", 30, nt=True),                              # seleccion mayor
             match("111", "2009-06-01", "2009", "U21Q", "9999", 90, nt=True)]                            # juvenil
    store.write_item("transfermarkt", "matches", "111", rows)


def test_end_to_end():
    seed_interim()
    t = normalize.run()
    pa = t["players_all"]
    assert set(pa["canonical_name"]) == {"Juan Pérez", "Pedro Gómez", "Luis Díaz"}  # 1975 fuera de cohorte
    assert pa.set_index("canonical_name").loc["Juan Pérez", "inclusion_status"] == "included"
    assert pa.set_index("canonical_name").loc["Pedro Gómez", "inclusion_status"] == "excluded"
    assert pa.set_index("canonical_name").loc["Luis Díaz", "inclusion_status"] == "review"
    assert list(t["players"]["canonical_name"]) == ["Juan Pérez"]
    assert not t["players"]["player_uid"].duplicated().any()
    assert len(t["national_team_caps"]) == 1 and len(t["youth_caps"]) == 1
    assert (t["career_stints"]["source_url"].notna()).all()

    f = features.run()["sa_clubs"]
    assert len(f) == 1
    r = f.iloc[0]
    assert r["club_minutes"] == 810 + 225 and r["nt_minutes"] == 30 and r["minutes_u23_total"] == 1065
    assert r["club_minutes_season_max"] == 810 and pd.isna(r["club_pk"])
    assert list(f.columns) == features.OUT_COLS

    tg = targets.run()["targets"]
    jp = tg.iloc[0]
    assert jp["min_elite"] == 720 and jp["caps"] == 24 and jp["target_standard"] == 1 and jp["target_elite"] == 0

    v = validate.run()
    assert "coverage" in v
    assert "Cola de revision" in report.run(v)

    # idempotencia: volver a correr no cambia el resultado
    t2 = normalize.run()
    assert len(t2["players_all"]) == len(pa) and len(t2["match_performance"]) == len(t["match_performance"])


def test_manual_decision_overrides_review():
    from src.common.config import MANUAL
    pa = store.read_table("players_all")
    uid = pa.set_index("canonical_name").loc["Luis Díaz", "player_uid"]
    (MANUAL / "position_decisions.csv").write_text(f"player_uid,decision,note\n{uid},include,lo vi jugar de 9\n", encoding="utf-8")
    t = normalize.run()
    assert "Luis Díaz" in set(t["players"]["canonical_name"])
    (MANUAL / "position_decisions.csv").unlink()
