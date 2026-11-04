from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

from src.adapters import fbref, transfermarkt as tm, wikipedia, wikidata


def test_tm_profile():
    p = tm.parse_profile((FIXTURES / "tm_profile.html").read_text(encoding="utf-8"))
    assert p["dob"] == "1990-03-05"
    assert p["position_main"] == "Centre-Forward"
    assert p["position_other"] == ["Second Striker", "Left Winger"]
    assert p["citizenship"] == ["Paraguay", "Spain"]
    assert p["caps_profile"] == 24 and p["nt_goals_profile"] == 7
    assert p["height_cm"] == 182
    assert p["foot"] == "right"
    assert p["full_name"] == "Juan Carlos Pérez Gómez"


def test_tm_profile_without_caps_is_null_not_zero():
    p = tm.parse_profile("<html><body><h1>X</h1></body></html>")
    assert p["caps_profile"] is None and p["caps_parsed"] is False


def test_tm_squad():
    rows = tm.parse_squad((FIXTURES / "tm_squad.html").read_text(encoding="utf-8"))
    assert [r["tm_id"] for r in rows] == ["111", "222", "333"]
    assert rows[0]["position"] == "Centre-Forward" and rows[0]["dob"] == "1990-03-05"
    assert rows[2]["nationalities"] == ["Paraguay", "Argentina"]


def test_tm_search():
    c = tm.parse_search((FIXTURES / "tm_search.html").read_text(encoding="utf-8"))
    assert [x["tm_id"] for x in c] == ["111", "999"]


def test_tm_flatten_pick():
    f = tm.flatten({"playingTimeStatistics": {"playedMinutes": 90}, "goalStatistics": {"goalsScoredTotal": 1, "assists": 0}})
    assert tm.pick(f, "playedminutes") == 90 and tm.pick(f, "assists") == 0


def test_fbref_commented_table():
    df = fbref.parse_stats_table((FIXTURES / "fbref_table.html").read_text(encoding="utf-8"))
    assert len(df) == 2
    r = df.iloc[0]
    assert r["player"] == "Juan Pérez" and r["player_fbref_id"] == "abcd1234"
    assert r["minutes"] == 2150 and r["nation"] == "PAR" and r["age"] == 25 and r["pk"] == 3
    assert df.iloc[1]["pos"] == "MF,FW"


def test_wikipedia_infobox():
    ib = wikipedia.parse_infobox((FIXTURES / "infobox_en.txt").read_text(encoding="utf-8"), "en")
    assert ib["birth_date"] == "1990-03-05"
    assert ib["position"] == "Striker"
    assert ib["clubs"][1]["club"] == "Sevilla" and ib["national_teams"][0]["caps"] == "24"


def test_wikidata_grouping():
    b = [
        {"p": {"value": "http://www.wikidata.org/entity/Q1"}, "pLabel": {"value": "Juan Pérez"},
         "dob": {"value": "1990-03-05T00:00:00Z"}, "prec": {"value": "11"}, "posLabel": {"value": "forward"},
         "tm_id": {"value": "111"}},
        {"p": {"value": "http://www.wikidata.org/entity/Q1"}, "pLabel": {"value": "Juan Pérez"},
         "dob": {"value": "1990-03-05T00:00:00Z"}, "prec": {"value": "11"}, "posLabel": {"value": "winger"},
         "alias": {"value": "Juanito"}},
        {"p": {"value": "http://www.wikidata.org/entity/Q2"}, "pLabel": {"value": "Otro"},
         "dob": {"value": "1990-01-01T00:00:00Z"}, "prec": {"value": "9"}},
    ]
    recs = {r["qid"]: r for r in wikidata.WikidataAdapter.parse_players(b, {"source": "wikidata"}, "PAR")}
    assert recs["Q1"]["positions"] == ["forward", "winger"] and recs["Q1"]["tm_id"] == "111"
    assert recs["Q1"]["aliases"] == ["Juanito"] and recs["Q1"]["dob_confidence"] == "exact"
    assert recs["Q2"]["dob"] is None and recs["Q2"]["birth_year"] == 1990 and recs["Q2"]["dob_confidence"] == "year_only"
