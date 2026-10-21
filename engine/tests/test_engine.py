import json
from pathlib import Path

import pytest

from recourse import hashing as H
from recourse.decide import Matcher, decisive_sets, outcome_of
from recourse.explain import guard, template_explanation
from recourse.world import World

RULES = Path(__file__).resolve().parents[1] / "rules"


@pytest.fixture(scope="module")
def world():
    return World(seed=7, households=40)


def rules(v):
    return json.loads((RULES / f"{v}.json").read_text())


def spot(world, key):
    return world.households[world.spotlight[key] - 1]


def test_canonical_sorts_keys_and_keeps_unicode():
    assert H.canonical({"b": 1, "a": ["ఆమినా", None, True]}) == '{"a":["ఆమినా",null,true],"b":1}'.encode()


def test_canonical_refuses_floats():
    with pytest.raises(TypeError):
        H.canonical({"score": 0.8})


@pytest.mark.parametrize("n", range(1, 10))
def test_every_proof_folds_to_the_root(n):
    leaves = [H.keccak(bytes([i])) for i in range(n)]
    root, proofs = H.merkle(leaves)
    for lf, pr in zip(leaves, proofs):
        assert H.root_of(lf, pr) == root


def test_leaf_carries_the_outcome():
    h = H.keccak(b"receipt")
    assert H.leaf(H.DENIED, h) != H.leaf(H.ELIGIBLE, h)
    assert H.leaf(H.DENIED, h) == H.keccak(bytes([2]) + h)


def test_amina_is_refused_only_under_v2(world):
    hh = spot(world, "amina")
    assert outcome_of(Matcher(world, rules("v1")).matches(hh)) == "ELIGIBLE"
    ev = Matcher(world, rules("v2")).matches(hh)
    assert outcome_of(ev) == "DENIED"
    assert [e.record.rid for e in ev] == ["TS09EX4521"]
    assert ev[0].member.status == "deceased"


def test_v2_catches_the_car_registered_elsewhere(world):
    hh = spot(world, "prakash")
    ids = [e.record.rid for e in Matcher(world, rules("v2")).matches(hh)]
    assert "TS07FK2290" in ids


def test_both_versions_refuse_the_real_government_job(world):
    hh = spot(world, "joseph")
    for v in ("v1", "v2"):
        assert "EMP-TSG-418820" in [e.record.rid for e in Matcher(world, rules(v)).matches(hh)]


def test_lakshmi_is_eligible_under_both(world):
    hh = spot(world, "lakshmi")
    for v in ("v1", "v2"):
        assert Matcher(world, rules(v)).matches(hh) == []


def test_two_records_must_both_fall(world):
    ev = Matcher(world, rules("v2")).matches(spot(world, "imran"))
    ids = {e.record.rid for e in ev}
    assert {"TS10AB7731", "ITR-AY2025-26-604418"} <= ids
    sets = decisive_sets(ev)
    assert len(sets) == 1 and len(sets[0]) == len(ev)


def _core(world):
    from recourse.decide import evidence_view
    hh = spot(world, "amina")
    r = rules("v2")
    ev = Matcher(world, r).matches(hh)
    return {"application": hh.application, "card": hh.card, "locality": hh.locality, "members": [],
            "outcome": outcome_of(ev), "reasons": [evidence_view(e, r) for e in ev],
            "decisive": decisive_sets(ev), "previous": {"rulesetId": 1, "outcome": "ELIGIBLE"},
            "decidedOn": "2026-10-22", "rulesetId": 2}, r


def test_guard_passes_the_template(world):
    core, r = _core(world)
    assert guard(template_explanation(core, r), core, r) == []


def test_guard_catches_an_invented_number(world):
    core, r = _core(world)
    text = template_explanation(core, r) + " You must reply within 15 days."
    assert "number not in the receipt: 15" in guard(text, core, r)


def test_guard_catches_an_invented_record_and_a_missing_one(world):
    core, r = _core(world)
    problems = guard("Record TS09EX9999 decided it.", core, r)
    assert "record ID not in the receipt: TS09EX9999" in problems
    assert "decisive record not mentioned: TS09EX4521" in problems


def test_guard_allows_what_the_family_said(world):
    core, r = _core(world)
    told = "He died in 2019 and drove a rickshaw for 31 years."
    text = template_explanation(core, r) + " " + told
    assert guard(text, core, r, told) == []
