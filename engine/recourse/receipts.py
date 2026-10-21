"""Turn a batch of decisions into receipts, one Merkle root, and a proof per receipt."""

import os
from dataclasses import dataclass

from . import hashing as H
from .decide import Matcher, decisive_sets, evidence_view, member_view, outcome_of
from .world import Household, World


def rules_hash(rules: dict) -> str:
    return H.hx(H.keccak(H.canonical(rules)))


@dataclass
class Batch:
    rulesetId: int
    root: str
    count: int
    denied: int
    receipts: list[dict]  # each: {"core", "receiptHash", "leaf", "proof"}


def decide_batch(world: World, rules: dict, *, ruleset_id: int, chain_id: int, contract: str, agency: str,
                 decided_on: str, previous: dict | None = None, salt=os.urandom) -> tuple[Batch, dict]:
    """`previous` maps hid -> outcome under the ruleset this one replaces, so each receipt
    says whether the rule change is what decided it. Returns the batch and hid -> outcome."""
    m = Matcher(world, rules)
    rh = rules_hash(rules)
    cores, outcomes = [], {}
    for hh in world.households:
        ev = m.matches(hh)
        outcome = outcome_of(ev)
        outcomes[hh.hid] = outcome
        core = {
            "v": 1,
            "chainId": chain_id,
            "contract": contract.lower(),
            "agency": agency.lower(),
            "rulesetId": ruleset_id,
            "rulesHash": rh,
            "application": hh.application,
            "card": hh.card,
            "locality": hh.locality,
            "members": [member_view(p) for p in hh.members],
            "outcome": outcome,
            "reasons": [evidence_view(e, rules) for e in ev],
            "decisive": decisive_sets(ev),
            "recordsChecked": _checked(m, hh, rules),
            "previous": ({"rulesetId": previous["rulesetId"], "outcome": previous["outcomes"][hh.hid]}
                         if previous else None),
            "decidedOn": decided_on,
            "salt": H.hx(salt(32)),
        }
        cores.append(core)
    hashes = [H.receipt_hash(c) for c in cores]
    leaves = [H.leaf(H.OUTCOME_CODE[c["outcome"]], h) for c, h in zip(cores, hashes)]
    root, proofs = H.merkle(leaves)
    receipts = [
        {"core": c, "receiptHash": H.hx(h), "leaf": H.hx(lf), "proof": [H.hx(p) for p in pr]}
        for c, h, lf, pr in zip(cores, hashes, leaves, proofs)
    ]
    denied = sum(1 for c in cores if c["outcome"] == "DENIED")
    return Batch(ruleset_id, H.hx(root), len(cores), denied, receipts), outcomes


def _checked(m: Matcher, hh: Household, rules: dict) -> int:
    return sum(len(m.candidates(ex["registry"], p)) for ex in rules["exclusions"] for p in hh.members)
