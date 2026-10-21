"""Plain-language explanations and appeal letters, written by Gemini and checked by a guard.

The receipt is the source of truth. The model only rewords it. Before any text is
used, the guard checks two things: every number and record ID in the text is in
the receipt (or the rules, or what the person told us), and every record that
decided the outcome is mentioned. A draft that fails is retried once, then
replaced by the template version, which can't fail.
"""

import json
import os
import re
import time

import requests

# Tried in order; a model that is overloaded or gone passes the request to the next.
MODELS = os.environ.get("RECOURSE_MODELS", "gemini-3-flash-preview,gemini-3.5-flash,gemini-flash-latest").split(",")
LANGS = {"en": "English", "hi": "Hindi", "te": "Telugu"}

ID_RE = re.compile(r"\b(?:TS\d{2}[A-Z]{2}\d{4}|ITR-AY\d{4}-\d{2}-\d{6}|EMP-TSG-\d{6}|RV-\d{4}-\d{6}|FSC-HYD-\d{6})\b")
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _walk(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)
    else:
        yield o


def allowed(core: dict, rules: dict, told: str = "") -> tuple[set[str], set[str]]:
    """Numbers and IDs a text about this receipt may use."""
    text = " ".join(str(v) for v in _walk(core) if not (isinstance(v, str) and v.startswith("0x")))
    text += " " + str(rules.get("appeal_response_days", "")) + " " + told + " " + rules.get("version", "")
    ids = set(ID_RE.findall(text))
    nums = set()
    for n in NUM_RE.findall(ID_RE.sub(" ", text)):
        n = n.replace(",", "").rstrip(".")
        nums.add(n.lstrip("0") or "0")
        if n.isdigit() and len(n) == 4 and int(n) <= 10000:  # basis points, also said as a decimal or percent
            nums.add(str(int(n) / 10000).rstrip("0").rstrip("."))
            nums.add(f"{int(n) / 10000:.2f}")
            nums.add(str(int(n) // 100))
    return nums, ids


def guard(text: str, core: dict, rules: dict, told: str = "") -> list[str]:
    """Problems with a draft. Empty means it can be used."""
    nums, ids = allowed(core, rules, told)
    problems = []
    found_ids = set(ID_RE.findall(text))
    for i in sorted(found_ids - ids):
        problems.append(f"record ID not in the receipt: {i}")
    for n in NUM_RE.findall(ID_RE.sub(" ", text)):
        n = n.replace(",", "").rstrip(".")
        n = n.lstrip("0") or "0"
        if n not in nums:
            problems.append(f"number not in the receipt: {n}")
    for s in core["decisive"]:
        for i in s:
            rid = core["reasons"][i]["record"]["id"]
            if rid not in found_ids:
                problems.append(f"decisive record not mentioned: {rid}")
    return problems


def template_explanation(core: dict, rules: dict) -> str:
    """English, built only from the receipt. Used when the model's draft fails the guard."""
    if core["outcome"] == "ELIGIBLE":
        return (f"Your household ({core['application']}) is eligible under rules {rules['version']}. "
                f"No record in the vehicle, income-tax or payroll registries was counted against any member "
                f"of your card.")
    lines = [f"Your household ({core['application']}) was refused under rules {rules['version']}."]
    for s in core["decisive"]:
        recs = [core["reasons"][i] for i in s]
        if len(recs) == 1:
            lines.append("This record alone decided it. If it is not your family's, you are eligible:")
        else:
            lines.append(f"These {len(recs)} records decided it together. "
                         "All of them would have to be shown not to be your family's:")
        for r in recs:
            rec = r["record"]
            lines.append(f"- {rec['id']} ({rec['registry']}): {rec['name']}, {rec['relation']}, {rec['locality']}, "
                         f"{rec['year']}, matched to {r['member']} with score {r['scoreBp']['total']} "
                         f"(threshold {r['thresholdBp']}).")
    prev = core.get("previous")
    if prev and prev["outcome"] != core["outcome"]:
        lines.append(f"Under the previous rules (ruleset {prev['rulesetId']}) the decision was {prev['outcome']}.")
    return "\n".join(lines)


def template_appeal(core: dict, rules: dict, told: str) -> str:
    recs = [core["reasons"][i] for s in core["decisive"] for i in s]
    ids = ", ".join(r["record"]["id"] for r in recs)
    body = [
        "To the Assistant Supply Officer, Civil Supplies Department",
        f"Subject: Appeal against refusal of application {core['application']} (card {core['card']})",
        "",
        f"My application was refused under rules {rules['version']} because of record(s) {ids}.",
        "These records do not belong to my family.",
    ]
    if told:
        body.append(told)
    body += ["Please correct the decision and restore our card.", "", "Yours faithfully"]
    return "\n".join(body)


def _gemini(prompt: str, key: str) -> tuple[str, str]:
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2}}
    last = None
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        r = None
        for attempt in range(2):
            try:
                # The key goes in a header, never the URL, so it can't leak into an error message.
                r = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=90)
            except requests.Timeout:
                r = None
                continue
            last = r
            if r.status_code in (429, 500, 503) and attempt < 1:
                time.sleep(5)
                continue
            break
        if r is None or r.status_code in (404, 429, 500, 503):
            continue  # next model
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip(), model
    if last is not None:
        last.raise_for_status()
    raise requests.HTTPError(f"no model answered ({last.status_code if last is not None else 'timeout'})",
                             response=last)


_RULES_FOR_MODEL = """Rules for what you write:
- Use only facts in the receipt and rules below. Do not add laws, deadlines, offices, phone numbers or advice that is not there.
- Every number you write must appear in the receipt or the rules. Write numbers with the digits 0-9.
- Name every record listed under "decisive" by its exact ID, as written in the receipt.
- Scores are in basis points: 8000 means 0.80. You may say "8000 out of 10000".
- Say "refused" or "eligible" in the language you write in; don't copy the words DENIED, ELIGIBLE or rulesetId.
  Call the rules "the current rules (version 2)" and "the earlier rules (version 1)".
- Plain words, short sentences. No markdown, no headings, no bullet symbols."""


def explain(core: dict, rules: dict, lang: str, key: str) -> dict:
    prompt = f"""You are explaining a decision about a family's food-security card to the family itself.
Write in {LANGS[lang]}, in 90 to 160 words. Say what was decided, which record(s) decided it and why that
record was linked to the family, and what the family can check or contest. If the receipt shows the previous
rules decided differently, say so. Keep names and record IDs in Latin letters exactly as written.

{_RULES_FOR_MODEL}

Receipt:
{json.dumps(_for_model(core), ensure_ascii=False, indent=1)}

Rules {rules['version']} (matching section):
{json.dumps(rules['matching'], ensure_ascii=False)}
"""
    return _guarded(prompt, core, rules, "", key, lambda: template_explanation(core, rules))


def appeal(core: dict, rules: dict, told: str, key: str) -> dict:
    prompt = f"""Draft a short, formal appeal letter in English from this family to the Assistant Supply Officer,
Civil Supplies Department, asking for the refusal to be reversed. 120 to 220 words. Open with the subject line
naming the application and card numbers. Point out, from the receipt, why each decisive record cannot be this
family's (compare names, the son/wife-of name, locality and year with the family's members). Include what the
family told us below. End with "Yours faithfully" and nothing after it.

{_RULES_FOR_MODEL}

What the family told us: {told or "nothing more"}

Receipt:
{json.dumps(_for_model(core), ensure_ascii=False, indent=1)}
"""
    return _guarded(prompt, core, rules, told, key, lambda: template_appeal(core, rules, told))


def _for_model(core: dict) -> dict:
    # The hashes, salt and chain fields mean nothing to the family; leave them out of the prompt.
    keep = ("application", "card", "locality", "members", "outcome", "reasons", "decisive", "previous",
            "decidedOn", "rulesetId")
    return {k: core[k] for k in keep}


def _guarded(prompt, core, rules, told, key, fallback) -> dict:
    tries = []
    for _ in range(2):
        try:
            text, model = _gemini(prompt, key)
        except requests.RequestException as e:
            status = e.response.status_code if getattr(e, "response", None) is not None else None
            tries.append({"error": f"{type(e).__name__} {status or ''}".strip()})
            continue
        problems = guard(text, core, rules, told)
        tries.append({"problems": problems})
        if not problems:
            return {"text": text, "source": model, "guard": "passed", "tries": tries}
    return {"text": fallback(), "source": "template", "guard": "model drafts failed; template used", "tries": tries}
