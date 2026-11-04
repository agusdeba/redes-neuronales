from src.pipeline import identity, positions as pos


def ev(**kw):
    e = pos.PositionEvidence()
    for src, (prim, sec, raw) in kw.items():
        e.add(src, prim, sec, raw)
    return e


def test_classify_labels():
    assert pos.classify_label("transfermarkt", "Attack - Centre-Forward") == "attack"
    assert pos.classify_label("transfermarkt", "Left Winger") == "attack"
    assert pos.classify_label("transfermarkt", "Attacking Midfield") == "ambiguous"
    assert pos.classify_label("transfermarkt", "Defensive Midfield") == "midfield"
    assert pos.classify_label("transfermarkt", "Goalkeeper") == "goalkeeper"
    assert pos.classify_label("fbref", "FW,MF") == "attack"
    assert pos.classify_label("wikipedia", "Delantero") == "attack"
    assert pos.classify_label("wikipedia", "Arquero") == "goalkeeper"


def test_fbref_groups():
    assert pos.fbref_groups("MF,FW") == ("midfield", ["attack"])
    assert pos.fbref_groups("FW") == ("attack", [])


def test_decide_primary_attack_included():
    s, g, _ = pos.decide(ev(transfermarkt=("attack", ["attack"], "Centre-Forward")))
    assert s == "included" and g == "attack"


def test_decide_secondary_attack_goes_to_review():
    s, g, r = pos.decide(ev(fbref=("midfield", ["attack"], "MF,FW")))
    assert s == "review" and g == "attack_secondary"


def test_decide_conflict_goes_to_review():
    s, g, _ = pos.decide(ev(transfermarkt=("ambiguous", [], "Attacking Midfield"), fbref=("attack", [], "FW")))
    assert s == "review"


def test_decide_defender_excluded():
    s, g, _ = pos.decide(ev(transfermarkt=("defense", [], "Centre-Back")))
    assert s == "excluded" and g == "defense"


def test_decide_no_evidence():
    assert pos.decide(pos.PositionEvidence())[0] == "unknown"


def test_uid_deterministic_and_anchor_priority():
    a = identity.make_uid(tm_id="111", qid="Q1")
    assert a == identity.make_uid(tm_id="111") and a != identity.make_uid(qid="Q1")


def test_cluster_by_shared_ids():
    recs = [{"tm_id": "111", "qid": "Q1"}, {"qid": "Q1", "fbref_id": "abcd"}, {"fbref_id": "abcd"}, {"tm_id": "222"}]
    roots = identity.cluster_records(recs)
    assert roots[0] == roots[1] == roots[2] and roots[3] != roots[0]


CANDS = [
    {"uid": "u1", "names": ["Juan Pérez"], "birth_year": 1990, "nationality": "PAR", "dob": "1990-03-05",
     "club_seasons": {("olimpia", 2015)}},
    {"uid": "u2", "names": ["Juan Peres"], "birth_year": 1991, "nationality": "PAR", "dob": None, "club_seasons": set()},
]


def test_fuzzy_requires_second_field():
    r = identity.fuzzy_attach({"name": "Juan Perez", "birth_year": 1990, "nationality": "PAR"}, CANDS)
    assert r["status"] == "review"  # nombre solo no alcanza


def test_fuzzy_confirms_by_club_season():
    r = identity.fuzzy_attach({"name": "Juan Perez", "birth_year": 1990, "nationality": "PAR",
                               "club_seasons": {("olimpia", 2015)}}, CANDS)
    assert r["status"] == "mapped" and r["uid"] == "u1" and r["method"] == "fuzzy+club_season"


def test_fuzzy_blocks_by_birth_year_and_nation():
    r = identity.fuzzy_attach({"name": "Juan Perez", "birth_year": 1985, "nationality": "PAR"}, CANDS)
    assert r["status"] == "new"
    r = identity.fuzzy_attach({"name": "Juan Perez", "birth_year": 1990, "nationality": "ARG", "dob": "1990-03-05"}, CANDS)
    assert r["status"] == "new"
