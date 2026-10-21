"""Write a small batch made by the engine's own hashing, for the contract tests."""

import json
import sys
from pathlib import Path

from recourse import hashing as H

out = Path(sys.argv[1] if len(sys.argv) > 1 else "../contracts/test/fixtures/batch.json")
cores = [
    {"application": f"RV-TEST-{i:03d}", "outcome": "DENIED" if i % 3 == 0 else "ELIGIBLE",
     "locality": "Falaknuma", "name": "ఆమినా బేగం" if i == 0 else f"Person {i}", "salt": H.hx(bytes([i]) * 32)}
    for i in range(7)  # odd on purpose: the last node moves up a level unpaired
]
hashes = [H.receipt_hash(c) for c in cores]
leaves = [H.leaf(H.OUTCOME_CODE[c["outcome"]], h) for c, h in zip(cores, hashes)]
root, proofs = H.merkle(leaves)
for lf, pr in zip(leaves, proofs):
    assert H.root_of(lf, pr) == root
items = [{"outcome": H.OUTCOME_CODE[c["outcome"]], "receiptHash": H.hx(h), "proof": [H.hx(p) for p in pr]}
         for c, h, pr in zip(cores, hashes, proofs)]
out.write_text(json.dumps({"root": H.hx(root), "items": items}, indent=1) + "\n")
print(out, H.hx(root))
