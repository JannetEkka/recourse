"""Hashes that must match the contract and the web page byte for byte.

receiptHash = keccak256(canonical JSON of the receipt)
leaf        = keccak256(outcome byte ++ receiptHash)   (Recourse.leafOf)
node        = keccak256(min(a, b) ++ max(a, b))       (sorted pairs, like OpenZeppelin)
"""

import json

from Crypto.Hash import keccak as _keccak

ELIGIBLE = 1
DENIED = 2
OUTCOME_CODE = {"ELIGIBLE": ELIGIBLE, "DENIED": DENIED}


def keccak(data: bytes) -> bytes:
    k = _keccak.new(digest_bits=256)
    k.update(data)
    return k.digest()


def hx(b: bytes) -> str:
    return "0x" + b.hex()


def unhx(s: str) -> bytes:
    return bytes.fromhex(s[2:] if s.startswith("0x") else s)


def canonical(obj) -> bytes:
    """Sorted keys, no spaces, UTF-8. The page's canonical() must give the same bytes.

    Floats are refused: Python and JavaScript print them differently, so every
    number that gets hashed is an integer (scores are in basis points).
    """

    def check(o):
        if isinstance(o, float):
            raise TypeError(f"float in hashed content: {o!r}")
        if isinstance(o, dict):
            for v in o.values():
                check(v)
        elif isinstance(o, list):
            for v in o:
                check(v)

    check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def receipt_hash(core: dict) -> bytes:
    return keccak(canonical(core))


def leaf(outcome: int, rhash: bytes) -> bytes:
    return keccak(bytes([outcome]) + rhash)


def _pair(a: bytes, b: bytes) -> bytes:
    return keccak(a + b) if a < b else keccak(b + a)


def merkle(leaves: list[bytes]) -> tuple[bytes, list[list[bytes]]]:
    """Root and one proof per leaf. An odd node at the end of a level moves up unchanged."""
    if not leaves:
        raise ValueError("no leaves")
    proofs: list[list[bytes]] = [[] for _ in leaves]
    level = list(leaves)
    owners = [[i] for i in range(len(leaves))]  # which leaves sit under each node
    while len(level) > 1:
        nxt, nxt_owners = [], []
        for i in range(0, len(level), 2):
            if i + 1 == len(level):
                nxt.append(level[i])
                nxt_owners.append(owners[i])
                continue
            a, b = level[i], level[i + 1]
            for leaf_i in owners[i]:
                proofs[leaf_i].append(b)
            for leaf_i in owners[i + 1]:
                proofs[leaf_i].append(a)
            nxt.append(_pair(a, b))
            nxt_owners.append(owners[i] + owners[i + 1])
        level, owners = nxt, nxt_owners
    return level[0], proofs


def root_of(lf: bytes, proof: list[bytes]) -> bytes:
    h = lf
    for p in proof:
        h = _pair(h, p)
    return h
