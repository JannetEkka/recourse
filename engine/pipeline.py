"""Run the demo against a chain: deploy, publish rules, decide and seal two batches, appeal.

    python pipeline.py --network local   # anvil on :8545 with its default keys
    python pipeline.py --network monad   # Monad testnet; keys from files given by env vars

Every step records what it did in out/<network>/state.json and is skipped on a re-run,
so a dropped RPC call never repeats a transaction.
"""

import argparse
import gzip
import json
import os
import random
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from recourse import hashing as H
from recourse import explain
from recourse.receipts import decide_batch, rules_hash
from recourse.world import World

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
SITE = "https://jannetekka.github.io/recourse"
CODE_FILES = ["engine/recourse/decide.py", "engine/recourse/hashing.py", "engine/recourse/receipts.py"]

NETWORKS = {
    "local": {"rpc": "http://127.0.0.1:8545", "chainId": 31337, "explorer": None,
              # anvil's first two default accounts
              "agency": "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
              "legal": "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"},
    "monad": {"rpc": "https://testnet-rpc.monad.xyz", "chainId": 10143,
              "explorer": "https://testnet.monadexplorer.com"},
}

AGENCY_NAME = "Civil Supplies Department (demo replica, synthetic data)"

# What each spotlight family tells the legal-aid worker. Their appeals use it.
TOLD = {
    "amina": "My husband Syed Ali was a rickshaw puller. He died in 2019 and never owned a car. "
             "We have always lived in Falaknuma, never in Banjara Hills.",
    "imran": "I am a tailor in Yakutpura. I have never owned a car or filed an income-tax return. "
             "My father's name is Mohammed Yousuf.",
    "prakash": "I drive an auto. I do not own a car.",
}


class Chain:
    def __init__(self, net: dict, agency_key: str, legal_key: str):
        self.rpc, self.agency_key, self.legal_key = net["rpc"], agency_key, legal_key
        self.contract = None

    def _cast(self, *args) -> str:
        r = subprocess.run(["cast", *args], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"cast {' '.join(args[:2])} failed: {r.stderr.strip()[:500]}")
        return r.stdout.strip()

    def address(self, key: str) -> str:
        return self._cast("wallet", "address", "--private-key", key)

    def balance(self, addr: str) -> int:
        return int(self._cast("balance", addr, "--rpc-url", self.rpc))

    def send(self, key: str, sig: str, *args, to: str | None = None, value: str | None = None) -> dict:
        cmd = ["send", "--rpc-url", self.rpc, "--private-key", key, "--json", to or self.contract]
        if sig:
            cmd += [sig, *args]
        if value:
            cmd += ["--value", value]
        out = json.loads(self._cast(*cmd))
        if out.get("status") not in ("0x1", 1, "1"):
            raise RuntimeError(f"transaction failed: {sig} {out.get('transactionHash')}")
        return {"tx": out["transactionHash"], "block": int(out["blockNumber"], 16)}

    def call(self, sig: str, *args) -> str:
        return self._cast("call", "--rpc-url", self.rpc, self.contract, sig, *args)

    def deploy(self) -> dict:
        r = subprocess.run(["forge", "create", "src/Recourse.sol:Recourse", "--rpc-url", self.rpc,
                            "--private-key", self.agency_key, "--broadcast", "--json"],
                           cwd=REPO / "contracts", capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr[-800:])
        out = json.loads(r.stdout[r.stdout.index("{"):])
        return {"contract": out["deployedTo"].lower(), "tx": out["transactionHash"]}


def arr(hexes: list[str]) -> str:
    return "[" + ",".join(hexes) + "]"


def published_rules(version: str) -> dict:
    rules = json.loads((ROOT / "rules" / f"{version}.json").read_text())
    rules["code"] = {
        "repo": "https://github.com/JannetEkka/recourse",
        "keccak256": {f: H.hx(H.keccak((REPO / f).read_bytes())) for f in CODE_FILES},
    }
    return rules


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", choices=NETWORKS, default="local")
    ap.add_argument("--households", type=int, default=1000)
    ap.add_argument("--no-ai", action="store_true", help="template text only, no Gemini calls")
    ap.add_argument("--export", default=str(REPO / "web" / "data"))
    a = ap.parse_args()

    net = NETWORKS[a.network]
    if a.network == "local":
        agency_key, legal_key = net["agency"], net["legal"]
    else:
        agency_key = json.loads(Path(os.environ["RECOURSE_AGENCY_KEY_FILE"]).read_text())[0]["private_key"]
        legal_key = json.loads(Path(os.environ["RECOURSE_LEGAL_KEY_FILE"]).read_text())[0]["private_key"]
    gemini = None if a.no_ai else os.environ.get("GEMINI_API_KEY")

    out = ROOT / "out" / a.network
    out.mkdir(parents=True, exist_ok=True)
    state_file = out / "state.json"
    st = json.loads(state_file.read_text()) if state_file.exists() else {}

    def save():
        state_file.write_text(json.dumps(st, indent=1) + "\n")

    chain = Chain(net, agency_key, legal_key)
    agency, legal = chain.address(agency_key).lower(), chain.address(legal_key).lower()
    st.setdefault("agency", agency)
    st.setdefault("legalAid", legal)

    # 1. Deploy and name the agency.
    if "contract" not in st:
        d = chain.deploy()
        st["contract"], st["deployTx"] = d["contract"], d["tx"]
        save()
        print("deployed", d["contract"])
    chain.contract = st["contract"]
    if "named" not in st:
        st["named"] = chain.send(agency_key, "nameAgency(string)", AGENCY_NAME)
        save()

    # The legal-aid worker files appeals and needs a little gas.
    if "legalFunded" not in st and chain.balance(legal) < 10**17:
        st["legalFunded"] = chain.send(agency_key, "", to=legal, value="0.2ether")
        save()

    world = World(seed=7, households=a.households)
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
    prev = None
    for n, version in ((1, "v1"), (2, "v2")):
        rules = published_rules(version)
        (out / "rules").mkdir(exist_ok=True)
        rules_file = out / "rules" / f"{version}.json"
        key = f"ruleset{n}"
        if key not in st:
            rules_file.write_text(json.dumps(rules, indent=2, ensure_ascii=False) + "\n")
            tx = chain.send(agency_key, "publishRuleset(bytes32,string,uint16)", rules_hash(rules),
                            f"{SITE}/data/rules/{version}.json", str(rules["appeal_response_days"]))
            rid = int(chain.call("rulesetOfHash(address,bytes32)(uint32)", agency, rules_hash(rules)))
            st[key] = {"id": rid, "version": version, "hash": rules_hash(rules), **tx}
            save()
            print("published", version, "as ruleset", rid)
        rules = json.loads(rules_file.read_text())
        rid = st[key]["id"]

        bkey = f"batch{n}"
        archive = out / f"batch-{n}.json.gz"
        if bkey not in st:
            batch, outcomes = decide_batch(world, rules, ruleset_id=rid, chain_id=net["chainId"],
                                           contract=st["contract"], agency=agency, decided_on=today,
                                           previous=prev)
            # Write the archive before sealing: if the seal lands and we crash, the receipts survive.
            archive.write_bytes(gzip.compress(json.dumps(
                {"root": batch.root, "receipts": batch.receipts, "outcomes": outcomes}).encode()))
            tx = chain.send(agency_key, "sealBatch(uint32,bytes32,uint32,uint32)", str(rid), batch.root,
                            str(batch.count), str(batch.denied))
            bid = int(chain.call("batchOfRoot(bytes32)(uint32)", batch.root))
            st[bkey] = {"id": bid, "rulesetId": rid, "root": batch.root, "count": batch.count,
                        "denied": batch.denied, **tx}
            save()
            print(f"sealed batch {bid}: {batch.count} decisions, {batch.denied} denied")
        data = json.loads(gzip.decompress(archive.read_bytes()))
        prev = {"rulesetId": rid, "outcomes": {int(k): v for k, v in data["outcomes"].items()}}

    appeals(chain, st, save, world, out, agency_key, legal_key, gemini)
    export(st, net, world, out, Path(a.export), gemini)


def _receipts(out: Path, n: int) -> list[dict]:
    return json.loads(gzip.decompress((out / f"batch-{n}.json.gz").read_bytes()))["receipts"]


def _truth(world: World, core: dict) -> bool:
    """Synthetic ground truth: does every decisive record really belong to this family?"""
    hh = next(h for h in world.households if h.application == core["application"])
    pids = {p.pid for p in hh.members}
    recs = {r.rid: r for r in world.records}
    ids = [core["reasons"][i]["record"]["id"] for s in core["decisive"] for i in s]
    return any(recs[i].true_pid in pids for i in ids)


def appeals(chain, st, save, world, out, agency_key, legal_key, gemini):
    st.setdefault("appeals", [])
    if st.get("appealsPlanned"):
        plan = st["appealsPlanned"]
    else:
        rng = random.Random(11)
        spot = {world.households[h - 1].application: k for k, h in world.spotlight.items()}
        plan = []
        for n in (1, 2):
            rs = _receipts(out, n)
            denied = [r["core"] for r in rs if r["core"]["outcome"] == "DENIED"]
            if n == 2:
                for c in denied:
                    if spot.get(c["application"]) in TOLD:
                        plan.append({"batch": n, "application": c["application"], "who": spot[c["application"]]})
                newly_wrong = [c for c in denied if c["application"] not in spot and not _truth(world, c)
                               and c["previous"]["outcome"] == "ELIGIBLE"]
                right = [c for c in denied if c["application"] not in spot and _truth(world, c)]
                picks = rng.sample(newly_wrong, min(9, len(newly_wrong))) + rng.sample(right, min(2, len(right)))
                # The agency leaves one of each kind unanswered; they go overdue after the response days.
                unanswered = {picks[len(picks) - 3]["application"], picks[-1]["application"]}
            else:
                wrong = [c for c in denied if not _truth(world, c)]
                right = [c for c in denied if _truth(world, c)]
                picks = rng.sample(wrong, min(1, len(wrong))) + rng.sample(right, min(1, len(right)))
                unanswered = set()
            plan += [{"batch": n, "application": c["application"], "who": None,
                      "answer": c["application"] not in unanswered} for c in picks]
        for p in plan:
            p.setdefault("answer", True)
        st["appealsPlanned"] = plan
        save()

    done = {(x["batch"], x["application"]) for x in st["appeals"]}
    for p in plan:
        if (p["batch"], p["application"]) in done:
            continue
        rs = _receipts(out, p["batch"])
        rec = next(r for r in rs if r["core"]["application"] == p["application"])
        core = rec["core"]
        rules = json.loads((out / "rules" / f"v{p['batch']}.json").read_text())
        told = TOLD.get(p["who"] or "", "")
        if gemini and p["who"]:
            drafted = explain.appeal(core, rules, told, gemini)
        else:
            drafted = {"text": explain.template_appeal(core, rules, told), "source": "template", "guard": "n/a"}
        letter = drafted["text"]
        bid = st[f"batch{p['batch']}"]["id"]
        tx = chain.send(legal_key, "fileAppeal(uint32,bytes32,bytes32[],bytes32)", str(bid), rec["receiptHash"],
                        arr(rec["proof"]), H.hx(H.keccak(letter.encode())))
        aid = int(chain.call("appealOfLeaf(bytes32)(uint32)", rec["leaf"]))
        entry = {"id": aid, "batch": p["batch"], "application": p["application"], "batchId": bid, "letter": letter,
                 "letterSource": drafted["source"], "letterGuard": drafted.get("guard"), "filed": tx}
        st["appeals"].append(entry)
        save()
        print("appeal", aid, p["application"])

    for p in plan:
        entry = next(x for x in st["appeals"] if (x["batch"], x["application"]) == (p["batch"], p["application"]))
        if not p["answer"] or "answer" in entry:
            continue
        rs = _receipts(out, p["batch"])
        core = next(r for r in rs if r["core"]["application"] == p["application"])["core"]
        ids = ", ".join(core["reasons"][i]["record"]["id"] for s in core["decisive"] for i in s)
        theirs = _truth(world, core)
        if theirs:
            text = (f"Appeal {entry['id']}: the decision stands. Record {ids} was checked against the registry's "
                    f"documents and belongs to a member of household {core['application']}.")
        else:
            text = (f"Appeal {entry['id']}: the decision is reversed. Record {ids} was checked against the registry's "
                    f"documents and belongs to another person. Card {core['card']} is restored.")
        tx = chain.send(agency_key, "answerAppeal(uint32,bool,bytes32)", str(entry["id"]),
                        "false" if theirs else "true", H.hx(H.keccak(text.encode())))
        entry["answer"] = {"text": text, "overturned": not theirs, **tx}
        save()
        print("answered", entry["id"], "overturned" if not theirs else "upheld")


def export(st, net, world, out, dest: Path, gemini):
    """Everything the web page needs. Receipts go out only for a sample of households."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "rules").mkdir(exist_ok=True)
    for v in ("v1", "v2"):
        shutil.copy(out / "rules" / f"{v}.json", dest / "rules" / f"{v}.json")

    spot = {world.households[h - 1].application: k for k, h in world.spotlight.items()}
    rng = random.Random(5)
    rcpt_dir = dest / "receipts"
    rcpt_dir.mkdir(exist_ok=True)
    index = []
    appealed = {(x["batch"], x["application"]) for x in st["appeals"]}
    for n in (1, 2):
        rs = _receipts(out, n)
        bid = st[f"batch{n}"]["id"]
        pick = [r for r in rs if r["core"]["application"] in spot or (n, r["core"]["application"]) in appealed]
        others = [r for r in rs if r not in pick]
        pick += rng.sample([r for r in others if r["core"]["outcome"] == "DENIED"], 6)
        pick += rng.sample([r for r in others if r["core"]["outcome"] == "ELIGIBLE"], 6)
        for r in pick:
            app = r["core"]["application"]
            name = f"{app}-b{bid}.json"
            (rcpt_dir / name).write_text(json.dumps({**r, "batchId": bid}, ensure_ascii=False, indent=1) + "\n")
            index.append({"file": name, "application": app, "batchId": bid, "outcome": r["core"]["outcome"],
                          "spotlight": spot.get(app), "appealed": (n, app) in appealed})
    (rcpt_dir / "index.json").write_text(json.dumps(index, indent=1) + "\n")

    # Explanations in three languages for the spotlight receipts under v2.
    ex_dir = dest / "explanations"
    ex_dir.mkdir(exist_ok=True)
    rules2 = json.loads((out / "rules" / "v2.json").read_text())
    for r in _receipts(out, 2):
        app = r["core"]["application"]
        if app not in spot:
            continue
        f = ex_dir / f"{app}.json"
        ex = json.loads(f.read_text()) if f.exists() else {}
        for lang in explain.LANGS:
            have = ex.get(lang)
            if have and have["source"] != "template":
                continue  # a guarded model text is kept; a template fallback gets another try
            if gemini:
                ex[lang] = explain.explain(r["core"], rules2, lang, gemini)
            elif lang == "en" and not have:
                ex[lang] = {"text": explain.template_explanation(r["core"], rules2), "source": "template"}
            f.write_text(json.dumps(ex, ensure_ascii=False, indent=1) + "\n")

    (dest / "appeals.json").write_text(json.dumps([
        {k: v for k, v in x.items()} for x in st["appeals"]], ensure_ascii=False, indent=1) + "\n")

    truth = {}
    for n in (1, 2):
        rs = _receipts(out, n)
        denied = [r["core"] for r in rs if r["core"]["outcome"] == "DENIED"]
        wrong = sum(1 for c in denied if not _truth(world, c))
        truth[f"batch{n}"] = {"decisions": len(rs), "denied": len(denied), "deniedWrongly": wrong,
                              "deniedRightly": len(denied) - wrong}
    truly_out = sum(1 for hh in world.households
                    if any(r.true_pid in {p.pid for p in hh.members} for r in world.records if r.true_pid))
    truth["householdsReallyIneligible"] = truly_out
    (dest / "synthetic-truth.json").write_text(json.dumps(truth, indent=1) + "\n")

    (dest / "deployment.json").write_text(json.dumps({
        "chainId": net["chainId"], "rpc": net["rpc"], "explorer": net["explorer"],
        "contract": st["contract"], "deployTx": st["deployTx"], "agency": st["agency"],
        "agencyName": AGENCY_NAME, "legalAid": st["legalAid"],
        "rulesets": [st["ruleset1"], st["ruleset2"]], "batches": [st["batch1"], st["batch2"]],
        "spotlight": {k: world.households[h - 1].application for k, h in world.spotlight.items()},
    }, indent=1) + "\n")
    print("exported to", dest)



if __name__ == "__main__":
    sys.exit(main())
