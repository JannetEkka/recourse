# Recourse

Receipts for welfare algorithms. Every automated eligibility decision is sealed on a public chain under rules the agency had to publish first. The family gets the records that actually decided their case, in their own language, and an appeal the agency can't lose or quietly ignore.

- **Live:** https://jannetekka.github.io/recourse/
- **Contract:** [`{{CONTRACT}}`]({{EXPLORER}}/address/{{CONTRACT}}) on Monad testnet (chain 10143)
- **Demo video:** {{VIDEO}}
- Built for [Web3 for Social Good 2026](https://dorahacks.io/hackathon/web3-social-good-2026/detail), Tech Track.

## The problem

Telangana's Samagra Vedika system matches people across government databases and removes them from subsidised food when it finds a "match". Al Jazeera and The Reporters' Collective [reported in January 2024](https://www.aljazeera.com/economy/2024/1/24/how-an-algorithm-denied-food-to-thousands-of-poor-in-indias-telangana) that it tagged Bismillah Bee's late husband, a rickshaw puller, as a car owner, and her family lost its rations. About 20 lakh ration cards were deleted from 2016 on ([The South First](https://thesouthfirst.com/telangana/telangana-employs-same-tech-to-issue-new-ration-cards-that-deleted-20-lakh-names/)).

Families in that position can't see which record sank them. Nobody outside the department can check which rules were in force on the day, whether they changed, or how often the system was wrong. The department keeps the only log, and the department is the party being checked.

## What Recourse does

1. **The rules are public before they're used.** The agency publishes the hash of each version of its matching rules on-chain, with a link to the file. The contract refuses any batch of decisions made under rules that weren't public in an earlier block. Edit the rules file afterwards and its hash stops matching.
2. **Each decision gets a receipt.** It lists the members checked, the records that counted, the match scores, the threshold, and whether the previous rules would have decided differently. A record is listed as a reason only if removing it changes the outcome. The receipt is salted and hashed; one Merkle root per batch goes on-chain, so nothing personal does.
3. **The family can read it.** Gemini explains the receipt in Telugu, Hindi or English and drafts the appeal letter. A guard checks every number and record ID in the text against the receipt and rejects the draft if one is invented or a decisive record is missing. If the model fails twice, fixed wording is used.
4. **Appeals are on the record.** A legal-aid worker files the appeal with the receipt's proof, so the family needs no wallet. The contract accepts appeals only against sealed refusals. The agency's answer is sealed too, and an appeal left past the response time the agency committed to shows as overdue.

## Try it

- [Amina's receipt](https://jannetekka.github.io/recourse/#/receipt/RV-2026-001001-b2.json). Press **Check against the chain**: your browser re-hashes the receipt, folds its proof into the batch root and calls the contract. Then press **Try to edit it**.
- [The public record](https://jannetekka.github.io/recourse/#/record): every rule version, batch and appeal, read live from the contract.
- [Check a receipt](https://jannetekka.github.io/recourse/#/check): paste any receipt file.

## The demo

The agency, households and registries are synthetic and seeded (`engine/recourse/world.py`). The chain transactions are real.

- 1,005 households on food-security cards in Hyderabad localities, 2 to 5 people each, some with a deceased member still on the card.
- Three registries to match against: vehicles (3,000 owners), income-tax returns (2,400) and the state payroll (800), drawn from the same name pools, so common names collide.
- About one household in twelve really is outside the scheme. Their records sometimes carry a spelling variant ("Md" for "Mohammed") or another address.

The agency re-verifies every card twice, under two versions of its rules:

| | Rules v1 | Rules v2 |
|---|---|---|
| Name / relative / locality weights | 4500 / 3500 / 2000 | 5000 / 3500 / 1500 |
| Threshold (out of 10000) | 8500 | 8000 |
| Record must be in the family's locality | yes | no |
| Households refused | 75 (7.5%) | 209 (20.8%) |
| ...that really are outside the scheme | 65 of 82 | 82 of 82 |
| ...wrongly refused | 10 | 127 |

v2 was meant to catch assets registered away from home, and it does: 17 more real cases. It also cuts off 117 more families who should have kept their rations. An auditor can't see the last two rows; only a synthetic demo can. What the public record does show is that v2 refused nearly three times as many families and that most of its appealed refusals were reversed.

Five families walk through the demo:

| Household | Under v2 | Why |
|---|---|---|
| Amina Begum (RV-2026-001001) | refused, reversed on appeal | Her husband Syed Ali, who died in 2019, matched a Toyota Innova registered in 2022 in Banjara Hills to "Syed Ali Khan", son of a man with the same name as his father. v1 required the same locality, so it didn't count. Modelled on Bismillah Bee's case; the names and records are invented. |
| Prakash Reddy (RV-2026-001002) | refused, upheld | He does own the car, registered at another address. v1 missed it. |
| Lakshmi Mudiraj (RV-2026-001003) | eligible | Nothing matched. |
| Joseph Prasad (RV-2026-001004) | refused | His son is on the police payroll. Both versions catch it. |
| Mohammed Imran (RV-2026-001005) | refused, reversed on appeal | Two strangers' records, a car and a tax return, each enough on its own. Both have to fall. |

## How it's built

```
contracts/   Recourse.sol and its Foundry tests (Solidity 0.8.28)
engine/      the decision engine, receipts, Merkle trees, Gemini + guard, and pipeline.py
  rules/     the two published rule versions
  out/monad/ what the pipeline did on Monad testnet: state, rules as published, batch archives
web/         the static page (no build step); data/ is exported by the pipeline
```

**Contract.** Any address can act as an agency. `nameAgency`, then `publishRuleset(rulesHash, uri, responseDays)`, then `sealBatch(rulesetId, root, count, refused)` from the next block on. `fileAppeal(batchId, receiptHash, proof, groundsHash)` checks the proof against a refusal leaf; `answerAppeal(id, overturned, answerHash)` is the agency's alone; `isOverdue(id)` turns true after `responseDays`. Per-ruleset counts (decisions, refused, appeals, upheld, reversed) live on-chain, so the public record needs no indexer.

**Hashing.** A receipt hash is keccak256 of its canonical JSON (sorted keys, no spaces, UTF-8, integers only). A leaf is keccak256(outcome byte ‖ receipt hash), so a refusal and an eligible decision can't be swapped. Inner nodes hash sorted pairs, the same scheme as OpenZeppelin's MerkleProof. Python, Solidity and the browser compute the same bytes; the contract tests read a batch the Python engine made.

**Decisive reasons.** `decide.py` re-runs the rules with each set of counted records removed, smallest sets first, and lists only the sets whose removal flips the outcome. For these OR-style rules that is every counted record together. A rule set that scores evidence would get the same test with no change to the receipt format.

**The guard.** `explain.py` collects every number and record ID in the receipt (and in what the family told the legal-aid worker), then checks the model's text against them. It runs on all three languages because names and IDs stay in Latin letters and numbers in 0-9.

## Run it

```bash
git clone --recursive https://github.com/JannetEkka/recourse && cd recourse
(cd contracts && forge test)
cd engine && pip install -r requirements.txt && python -m pytest -q tests
anvil &                                         # a local chain
python pipeline.py --network local --no-ai      # deploy, publish, decide, seal, appeal; exports web/data
cd ../web && python -m http.server 8000         # then open http://localhost:8000
```

`--network monad` reads the agency and legal-aid keys from the files named in `RECOURSE_AGENCY_KEY_FILE` and `RECOURSE_LEGAL_KEY_FILE`, and uses `GEMINI_API_KEY` for the explanations. Every step is recorded in `out/<network>/state.json`, so a re-run never repeats a transaction.

## Limits

- It proves which rules the agency said it ran, when, and what it decided. It can't prove the agency ran them on every household. A family or auditor with a receipt can re-run the published rules and catch a mismatch.
- It can't force the agency to answer. It makes a missing answer visible, with a date.
- Receipts carry other people's registry records (the stranger's car). A real deployment needs a rule for how much of a matched record the family may see.
- The keys are testnet-only and have never held real funds.

Built by Jannet Akanksha Ekka with Claude Code as the coding assistant. Gemini writes the explanations and appeal drafts; the guard above decides whether they're used.
