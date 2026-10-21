# DoraHacks BUIDL fields (paste-ready)

## BUIDL name
Recourse

## Brief description
Receipts for welfare algorithms: rules published on-chain before use, the records that decided each case, and appeals on the record.

## Track
Tech Track

## Links
- GitHub: https://github.com/JannetEkka/recourse
- Project website: https://jannetekka.github.io/recourse/
- Demo video: https://github.com/JannetEkka/recourse/blob/main/media/demo/recourse-demo.mp4 (or the YouTube link once uploaded)

## Details

### The problem
Telangana uses an automated system to decide who gets subsidised food. It matches people across government databases and removes them when it finds a "match". In January 2024 Al Jazeera and The Reporters' Collective reported that it tagged Bismillah Bee's late husband, a rickshaw puller, as a car owner, and her family lost its rations. About 20 lakh ration cards were deleted from 2016 on.

People in her position can't see which record sank them. Nobody outside the department can check which rules were in force on the day, whether they changed, or how often the system got it wrong. The department keeps the only log, and the department is the party being checked.

### What Recourse does
1. **Rules are public before they're used.** The agency publishes the hash of each version of its matching rules on-chain. The contract refuses any batch of decisions made under rules that weren't public in an earlier block.
2. **Every decision gets a receipt.** It lists the people checked, the registry records that counted, the match scores, the threshold, and whether the previous rules would have decided differently. A record counts as a reason only if removing it changes the outcome.
3. **The family can read it.** Gemini explains the receipt in Telugu, Hindi or English and drafts the appeal letter. A guard checks every number and record ID against the receipt and throws out any draft that invents one or leaves out a decisive record.
4. **Appeals are on the record.** A legal-aid worker files the appeal on-chain with the receipt's proof, so the family needs no wallet. The agency's answer is sealed too, and an appeal left past the response time the agency committed to shows as overdue.

### Why a chain
The agency is the party being audited, so it can't be the one keeping the log. On a public chain the rules, the batches and the appeals are fixed when they're written, and anyone can check them without asking. Only hashes of salted receipts go on-chain, one Merkle root per batch, so no personal data does.

### The demo (live on Monad testnet)
A synthetic civil-supplies department re-verifies 1,005 households twice, against synthetic vehicle, income-tax and payroll registries:

- Rules v1 refused 75 households (7.5%). Rules v2, meant to catch cars registered at other addresses, refused 209 (20.8%).
- Because the data is synthetic we know the truth: v2 caught 17 more real cases and wrongly cut off 117 more families.
- A real auditor can't see that, but the public record shows it anyway: of v2's answered appeals, 10 of 12 were reversed.

Amina's receipt is modelled on the Bismillah Bee case: her husband died in 2019 and was matched to a Toyota Innova registered in 2022 in another locality, at exactly the threshold. Her appeal was filed and reversed on-chain.

Try it:
- [Amina's receipt](https://jannetekka.github.io/recourse/#/receipt/RV-2026-001001-b2.json): press "Check against the chain", then "Try to edit it".
- [The public record](https://jannetekka.github.io/recourse/#/record): every rule version, batch and appeal, read live from the contract.

### How it's built
- `Recourse.sol` (Solidity 0.8.28, Foundry, 21 tests), verified on Sourcify: [0x0113802632a88f7f5ebd7603a8eea5f31e5c30ce](https://testnet.monadvision.com/address/0x0113802632a88f7f5ebd7603a8eea5f31e5c30ce) on Monad testnet. No owner and no admin key; any address can act as an agency.
- Python engine: seeded synthetic city, two published rule versions, the decisive-record test, salted receipts, Merkle trees, Gemini with the fact guard, and a resumable pipeline (21 tests). Python, Solidity and the browser compute the same hashes byte for byte.
- A static web page (ethers v6) that re-hashes receipts, folds proofs and reads the contract directly.
- Cost: one seal per batch of 1,005 decisions, about 160,000 gas (0.017 testnet MON at today's price).

### Feasibility
The agency changes one thing in its process: it seals each batch and publishes each rule version. Decisions stay off-chain, in the system it already runs. Legal-aid groups, which already help families appeal, get a tool that tells them exactly which record to dispute. Auditors get a public view of refusals and appeal outcomes per rule version without asking for access.

### Limits
It proves which rules the agency said it ran, when, and what it decided; a family or auditor can re-run the published rules on a receipt and catch a mismatch. It can't force an answer, but it makes a missing one visible with a date. The agency, households and registries in the demo are invented; the contract, seals and appeals are real testnet transactions.

### Team
Jannet Akanksha Ekka, solo. Built with Claude Code as the coding assistant; Gemini writes the explanations and appeal drafts, and the guard decides whether they're used.
