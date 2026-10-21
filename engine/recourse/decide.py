"""Apply a published ruleset to a household, and work out which records decided it.

Every number that ends up in a receipt is an integer in basis points (10000 = 1.0),
so the receipt hashes the same in Python and in the browser.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations

from .world import Household, Person, Record, World

REGISTRY_LABEL = {"vehicles": "Transport Dept. vehicle registry", "income_tax": "Income-tax returns",
                  "payroll": "State government payroll"}


def tokens(name: str, aliases: dict) -> list[str]:
    out = []
    for t in re.sub(r"[^a-z ]", " ", name.lower()).split():
        out.append(aliases.get(t, t))
    return sorted(out)


def _same_token(a: str, b: str, fuzzy: float) -> bool:
    return a == b or (min(len(a), len(b)) >= 5 and SequenceMatcher(None, a, b).ratio() >= fuzzy)


def name_bp(a: str, b: str, m: dict) -> int:
    """Dice overlap of name tokens; a name wholly inside a longer one scores subset_score_bp."""
    ta, tb = tokens(a, m["aliases"]), tokens(b, m["aliases"])
    if not ta or not tb:
        return 0
    fuzzy = m["token_fuzzy_bp"] / 10000
    unused = list(tb)
    matched = 0
    for t in ta:
        for i, u in enumerate(unused):
            if _same_token(t, u, fuzzy):
                matched += 1
                del unused[i]
                break
    dice = 2 * matched / (len(ta) + len(tb))
    short = min(len(ta), len(tb))
    subset = m["subset_score_bp"] / 10000 if short >= 2 and matched == short else 0.0
    return round(max(dice, subset) * 10000)


@dataclass
class Evidence:
    rule: str
    member: Person
    record: Record
    name: int
    relative: int
    locality: int
    score: int
    threshold: int


class Matcher:
    """Indexes the registries once; scores a person against them under one ruleset."""

    def __init__(self, world: World, rules: dict):
        self.rules = rules
        self.m = rules["matching"]
        self.common = set(self.m["common_tokens"])
        self.by_registry_token: dict[tuple[str, str], list[Record]] = {}
        for r in world.records:
            for t in set(tokens(r.name, self.m["aliases"])) - self.common:
                self.by_registry_token.setdefault((r.registry, t), []).append(r)

    def candidates(self, registry: str, person: Person) -> list[Record]:
        seen, out = set(), []
        for t in set(tokens(person.name, self.m["aliases"])) - self.common:
            for r in self.by_registry_token.get((registry, t), []):
                if r.rid not in seen:
                    seen.add(r.rid)
                    out.append(r)
        return out

    def score(self, rule: str, person: Person, hh: Household, rec: Record) -> Evidence:
        w = self.m["weights_bp"]
        n = name_bp(person.name, rec.name, self.m)
        rel = name_bp(person.relative, rec.relative, self.m)
        loc = 10000 if rec.locality == hh.locality else 0
        total = (w["name"] * n + w["relative"] * rel + w["locality"] * loc) // 10000
        return Evidence(rule, person, rec, n, rel, loc, total, self.m["threshold_bp"])

    def matches(self, hh: Household) -> list[Evidence]:
        """Every record that counts against this household under the rules."""
        found = []
        for ex in self.rules["exclusions"]:
            for person in hh.members:
                for rec in self.candidates(ex["registry"], person):
                    ev = self.score(ex["rule"], person, hh, rec)
                    if ev.score < ev.threshold:
                        continue
                    if self.m["require_same_locality"] and not ev.locality:
                        continue
                    found.append(ev)
        found.sort(key=lambda e: (-e.score, e.record.rid))
        return found


def outcome_of(evidence: list[Evidence]) -> str:
    # The exclusion rules are an OR: one counted record is enough to deny.
    return "DENIED" if evidence else "ELIGIBLE"


def decisive_sets(evidence: list[Evidence], max_size: int = 3) -> list[list[int]]:
    """The smallest sets of records that, if each were shown not to be this family's,
    would change the outcome. A record that changes nothing isn't a reason.

    The rules here are an OR, so for a denial this is one set holding every counted
    record. The search is written generally so that a ruleset with scores or
    combinations gets the same test without changing the receipt format.
    """
    if outcome_of(evidence) == "ELIGIBLE":
        return []
    idx = list(range(len(evidence)))
    found: list[list[int]] = []
    for size in range(1, min(max_size, len(idx)) + 1):
        for combo in combinations(idx, size):
            if any(set(f) <= set(combo) for f in found):
                continue
            rest = [e for i, e in enumerate(evidence) if i not in combo]
            if outcome_of(rest) == "ELIGIBLE":
                found.append(list(combo))
        if found:
            break
    return found or [idx]


def member_view(p: Person) -> dict:
    v = {"name": p.name, "relation": f"{p.relation} {p.relative}", "status": p.status}
    if p.died:
        v["died"] = p.died
    return v


def evidence_view(e: Evidence, rules: dict) -> dict:
    text = {x["rule"]: x["text"] for x in rules["exclusions"]}[e.rule]
    r = e.record
    return {
        "rule": e.rule,
        "ruleText": text,
        "member": e.member.name,
        "record": {
            "registry": REGISTRY_LABEL[r.registry],
            "id": r.rid,
            "name": r.name,
            "relation": f"{r.relation} {r.relative}",
            "locality": r.locality,
            "year": r.year,
            "detail": r.detail,
        },
        "scoreBp": {"name": e.name, "relative": e.relative, "locality": e.locality, "total": e.score},
        "thresholdBp": e.threshold,
    }
