"use strict";

// Recourse web page. Everything is checked in the browser: receipts are re-hashed here,
// Merkle proofs are folded here, and the chain is read directly over JSON-RPC.

const ABI = [
  "function agencyName(address) view returns (string)",
  "function rulesetCount() view returns (uint32)",
  "function rulesets(uint32) view returns (address agency, uint64 publishedAt, uint64 publishedBlock, uint64 retiredAt, uint16 responseDays, bytes32 rulesHash, string uri)",
  "function stats(uint32) view returns (uint32 batches, uint32 decisions, uint32 denied, uint32 appeals, uint32 upheld, uint32 overturned)",
  "function batchCount() view returns (uint32)",
  "function batches(uint32) view returns (uint32 rulesetId, uint32 count, uint32 denied, uint64 sealedAt, bytes32 root)",
  "function appealCount() view returns (uint32)",
  "function appeals(uint32) view returns (uint32 batchId, uint8 status, uint64 filedAt, uint64 answeredAt, address filer, bytes32 leaf, bytes32 groundsHash, bytes32 answerHash)",
  "function appealOfLeaf(bytes32) view returns (uint32)",
  "function isOverdue(uint32) view returns (bool)",
  "function verify(uint32,uint8,bytes32,bytes32[]) view returns (bool)",
];
const OUTCOME = { ELIGIBLE: 1, DENIED: 2 };
const STATUS = ["Open", "Decision stands", "Decision reversed"];
const LANGS = { en: "English", hi: "हिन्दी", te: "తెలుగు" };
const SPOT = {
  amina: { who: "Amina Begum", what: "Her late husband was matched to someone else's car" },
  prakash: { who: "Prakash Reddy", what: "A car he does own, registered at another address" },
  lakshmi: { who: "Lakshmi Mudiraj", what: "Nothing matched: eligible" },
  joseph: { who: "Joseph Prasad", what: "His son really is on the government payroll" },
  imran: { who: "Mohammed Imran", what: "Two strangers' records, each enough on its own" },
};

const $app = document.getElementById("app");
const S = { dep: null, index: null, appeals: null, truth: null, rules: {}, provider: null, c: null, cache: {} };

// ---------- helpers

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
const short = (h, n = 6) => (h && h.length > 2 * n + 2 ? `${h.slice(0, n + 2)}…${h.slice(-n)}` : h);
const pct = (a, b) => (b ? `${((100 * a) / b).toFixed(1)}%` : "–");
const istDate = (ts) => new Date(Number(ts) * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) + " IST";
const dayOnly = (ts) => new Date(Number(ts) * 1000).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" });

function link(kind, value, text) {
  const ex = S.dep && S.dep.explorer;
  if (!ex || !value) return esc(text || value);
  return `<a href="${ex}/${kind}/${value}" target="_blank" rel="noopener">${esc(text || short(value))}</a>`;
}

async function getJSON(path) {
  if (!(path in S.cache)) {
    S.cache[path] = fetch(path, { cache: "no-cache" }).then((r) => {
      if (!r.ok) throw new Error(`${path}: ${r.status}`);
      return r.json();
    });
  }
  return S.cache[path];
}

// Sorted keys, no spaces, same as Python's json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False).
function canonical(v) {
  if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
  if (v && typeof v === "object") {
    return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}";
  }
  return JSON.stringify(v);
}
const keccakText = (s) => ethers.keccak256(ethers.toUtf8Bytes(s));
const receiptHash = (core) => keccakText(canonical(core));
const leafOf = (outcome, h) => ethers.solidityPackedKeccak256(["uint8", "bytes32"], [outcome, h]);
function rootOf(leaf, proof) {
  let h = leaf.toLowerCase();
  for (const p0 of proof) {
    const p = p0.toLowerCase();
    h = h < p ? ethers.keccak256(ethers.concat([h, p])) : ethers.keccak256(ethers.concat([p, h]));
  }
  return h;
}

async function boot() {
  try {
    S.dep = await getJSON("data/deployment.json");
  } catch (e) {
    $app.innerHTML = `<p class="loading">Couldn't load the deployment data (${esc(e.message)}).</p>`;
    return;
  }
  S.provider = new ethers.JsonRpcProvider(S.dep.rpc, S.dep.chainId, { staticNetwork: true, batchMaxCount: 20 });
  S.c = new ethers.Contract(S.dep.contract, ABI, S.provider);
  document.getElementById("foot-links").innerHTML =
    ` Contract ${link("address", S.dep.contract)} · <a href="https://github.com/JannetEkka/recourse">source on GitHub</a>.`;
  window.addEventListener("hashchange", route);
  route();
}

function route() {
  const h = location.hash.replace(/^#\/?/, "");
  const [page, ...rest] = h.split("/");
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.nav === page || (page === "receipt" && a.dataset.nav === "receipts")));
  window.scrollTo(0, 0);
  const views = { "": home, receipts, receipt: () => receiptPage(rest.join("/")), r: () => sharedReceipt(rest.join("/")), record, check, how };
  (views[page] || home)().catch((e) => {
    console.error(e);
    $app.innerHTML = `<p class="loading">Something went wrong: ${esc(e.message)}</p>`;
  });
}

// ---------- chain reads

async function chainState() {
  if (S.state) return S.state;
  const c = S.c;
  const [rc, bc, ac, name] = await Promise.all([c.rulesetCount(), c.batchCount(), c.appealCount(), c.agencyName(S.dep.agency)]);
  const ids = (n) => Array.from({ length: Number(n) }, (_, i) => i + 1);
  const rulesets = await Promise.all(ids(rc).map(async (id) => {
    const [r, s] = await Promise.all([c.rulesets(id), c.stats(id)]);
    return { id, agency: r.agency, publishedAt: r.publishedAt, publishedBlock: r.publishedBlock, retiredAt: r.retiredAt, responseDays: Number(r.responseDays), rulesHash: r.rulesHash, uri: r.uri,
      batches: Number(s.batches), decisions: Number(s.decisions), denied: Number(s.denied), appeals: Number(s.appeals), upheld: Number(s.upheld), overturned: Number(s.overturned) };
  }));
  const batches = await Promise.all(ids(bc).map(async (id) => {
    const b = await c.batches(id);
    return { id, rulesetId: Number(b.rulesetId), count: Number(b.count), denied: Number(b.denied), sealedAt: b.sealedAt, root: b.root };
  }));
  const appeals = await Promise.all(ids(ac).map(async (id) => {
    const [a, overdue] = await Promise.all([c.appeals(id), c.isOverdue(id)]);
    return { id, batchId: Number(a.batchId), status: Number(a.status), filedAt: a.filedAt, answeredAt: a.answeredAt, filer: a.filer, leaf: a.leaf, groundsHash: a.groundsHash, answerHash: a.answerHash, overdue };
  }));
  S.state = { agencyName: name, rulesets, batches, appeals };
  return S.state;
}

// ---------- pages

async function home() {
  const amina = S.dep.spotlight.amina;
  $app.innerHTML = `
  <section class="hero">
    <h1>When an algorithm cuts off a family's food, they should get a receipt.</h1>
    <p class="lede">Recourse seals every automated welfare decision on a public chain, under rules the agency had to publish first. The family gets the exact records that decided their case, in their own language, and an appeal the agency can't lose or quietly ignore.</p>
    <div class="btns">
      <a class="btn" href="#/receipt/${amina}-b2.json">See Amina's receipt</a>
      <a class="btn ghost" href="#/record">Open the public record</a>
    </div>
  </section>
  <div class="quote">
    <p>In Telangana, an automated system matches people across government databases and removes them from subsidised food when it finds a “match”. It tagged Bismillah Bee's late husband, a rickshaw puller, as a car owner, and the family lost its rations. Nobody could tell her which record it was.</p>
    <p class="small">Reported by <a href="https://www.aljazeera.com/economy/2024/1/24/how-an-algorithm-denied-food-to-thousands-of-poor-in-indias-telangana">Al Jazeera with The Reporters' Collective (January 2024)</a>. About 20 lakh ration cards were deleted from 2016 on (<a href="https://thesouthfirst.com/telangana/telangana-employs-same-tech-to-issue-new-ration-cards-that-deleted-20-lakh-names/">The South First</a>). Amina, below, is invented and modelled on that case.</p>
  </div>
  <h2>Three things that change</h2>
  <div class="grid grid-3">
    <div class="card"><h3>The rules are public before they're used</h3><p class="muted small">The agency publishes the hash of each version of its matching rules on-chain. The contract refuses any decision sealed under rules that weren't public in an earlier block, and the rules file can't change without everyone seeing the hash break.</p></div>
    <div class="card"><h3>The family sees what decided it</h3><p class="muted small">A receipt lists only the records that changed the outcome: if a record were removed and the decision stayed the same, it isn't listed as a reason. Gemini explains it in Telugu, Hindi or English, and a guard rejects any sentence with a number or record that isn't on the receipt.</p></div>
    <div class="card"><h3>Appeals are on the record</h3><p class="muted small">A legal-aid worker files the appeal on-chain, so the agency can't say it never arrived. Its answer is sealed too, and anyone can see how often each version of the rules gets overturned on appeal.</p></div>
  </div>
  <h2>Try it</h2>
  <ol class="steps">
    <li><a href="#/receipts">Open a receipt</a> and press <b>Check against the chain</b>. Your browser re-hashes it and asks the contract.</li>
    <li>Press <b>Try to edit it</b>. Change one fact and watch every check fail.</li>
    <li>Open <a href="#/record">the public record</a>. Version 2 of the rules refuses almost three times as many families, and most of its appeals are reversed.</li>
  </ol>`;
}

async function receipts() {
  const index = await getJSON("data/receipts/index.json");
  const spot = index.filter((x) => x.spotlight && x.batchId === S.dep.batches[1].id);
  const rest = index.filter((x) => !x.spotlight);
  const item = (x, title, sub) => `<a class="item" href="#/receipt/${esc(x.file)}">
      <div class="t">${esc(title)} <span class="outcome-s badge ${x.outcome === "DENIED" ? "bad" : "good"}">${x.outcome === "DENIED" ? "Refused" : "Eligible"}</span>${x.appealed ? ' <span class="badge plain">appealed</span>' : ""}</div>
      <div class="small muted">${esc(sub)}</div></a>`;
  $app.innerHTML = `
    <h1>Receipts</h1>
    <p class="muted">Every household gets one for every decision. These are a sample from the agency's two batches: one under the rules v1, one under v2. In real use a family holds only its own receipt.</p>
    <h2>Five families</h2>
    <div class="list">${spot.map((x) => item(x, SPOT[x.spotlight].who, `${SPOT[x.spotlight].what} · ${x.application} · rules v2`)).join("")}</div>
    <p class="small muted">The same five under rules v1: ${index.filter((x) => x.spotlight && x.batchId === S.dep.batches[0].id).map((x) => `<a href="#/receipt/${esc(x.file)}">${esc(SPOT[x.spotlight].who.split(" ")[0])}</a>`).join(" · ")}</p>
    <h2>More households</h2>
    <div class="list grid grid-2">${rest.map((x) => item(x, x.application, `rules v${x.batchId === S.dep.batches[0].id ? 1 : 2}${x.appealed ? " · appealed" : ""}`)).join("")}</div>`;
}

async function receiptPage(file) {
  if (!/^[\w.-]+\.json$/.test(file)) throw new Error("bad receipt name");
  const r = await getJSON(`data/receipts/${file}`);
  return renderReceipt(r);
}

async function sharedReceipt(data) {
  const r = await unpack(data);
  return renderReceipt(r);
}

async function check() {
  $app.innerHTML = `
    <h1>Check a receipt</h1>
    <p class="muted">Paste a receipt file. It's checked in this browser against the contract; nothing is sent anywhere except read-only calls to the chain.</p>
    <textarea id="paste" placeholder='{"core": {...}, "receiptHash": "0x...", "proof": [...], "batchId": 2}'></textarea>
    <div class="btns"><button class="btn" id="go">Check it</button></div>
    <p id="err" class="small" style="color:var(--bad)"></p>`;
  document.getElementById("go").onclick = () => {
    try {
      const r = JSON.parse(document.getElementById("paste").value);
      if (!r.core || !r.proof || !r.batchId) throw new Error("A receipt needs core, proof and batchId.");
      renderReceipt(r);
    } catch (e) {
      document.getElementById("err").textContent = e.message;
    }
  };
}

// ---------- the receipt

function memberOf(core, name) {
  return core.members.find((m) => m.name === name) || {};
}

function thingsToCheck(core, reason) {
  const m = memberOf(core, reason.member);
  const rec = reason.record;
  const out = [];
  if (m.died && rec.year > m.died) out.push(`This record is from ${rec.year}. ${m.name} died in ${m.died}, ${rec.year - m.died} year${rec.year - m.died > 1 ? "s" : ""} earlier.`);
  if (rec.locality !== core.locality) out.push(`The record is in ${rec.locality}. The family's card is in ${core.locality}.`);
  if (rec.name !== m.name) out.push(`The name on the record is “${rec.name}”, not “${m.name}”.`);
  if (rec.relation !== m.relation) out.push(`The record says “${rec.relation}”; the card says “${m.relation}”.`);
  if (reason.scoreBp.total - reason.thresholdBp < 300) out.push(`The match scored ${reason.scoreBp.total}, ${reason.scoreBp.total === reason.thresholdBp ? "exactly at" : "just above"} the threshold of ${reason.thresholdBp}.`);
  return out;
}

function matchBlock(core, reason, n, setSize) {
  const m = memberOf(core, reason.member);
  const rec = reason.record;
  const sc = reason.scoreBp;
  const rows = [
    ["Name", m.name, rec.name, sc.name],
    ["Son/wife/daughter of", m.relation, rec.relation, sc.relative],
    ["Locality", core.locality, rec.locality, sc.locality],
    ["Year", m.died ? `died ${m.died}` : "—", rec.year, null],
  ];
  const checks = thingsToCheck(core, reason);
  return `<div class="match">
    <div class="match-head">${setSize > 1 ? `Record ${n + 1} of ${setSize}: ` : ""}${esc(reason.ruleText)} · <span class="mono">${esc(rec.id)}</span></div>
    <table>
      <tr><th></th><th>On the family's card</th><th>In the ${esc(rec.registry)}</th><th class="num">Score</th></tr>
      ${rows.map(([k, a, b, s]) => `<tr><th>${esc(k)}</th><td>${esc(a)}</td><td class="${String(a) !== String(b) ? "diff" : ""}">${esc(b)}</td><td class="num mono">${s == null ? "" : s}</td></tr>`).join("")}
      <tr><th>Detail</th><td></td><td>${esc(rec.detail)}</td><td></td></tr>
    </table>
    <div style="padding:10px 14px">
      <div class="small">Match score <b>${sc.total}</b> against a threshold of <b>${reason.thresholdBp}</b> (out of 10000)</div>
      <div class="scorebar" role="img" aria-label="score ${sc.total} of 10000, threshold ${reason.thresholdBp}"><div class="fill" style="width:${sc.total / 100}%"></div><div class="mark" style="left:${reason.thresholdBp / 100}%"></div></div>
      ${checks.length ? `<ul class="checks small">${checks.map((t) => `<li class="flag">${esc(t)}</li>`).join("")}</ul>` : ""}
    </div>
  </div>`;
}

function templateExplanation(core) {
  if (core.outcome === "ELIGIBLE") return `Your household (${core.application}) is eligible under rules v${core.rulesetId}. No record in the vehicle, income-tax or payroll registries was counted against any member of your card.`;
  const lines = [`Your household (${core.application}) was refused under rules v${core.rulesetId}.`];
  for (const set of core.decisive) {
    const recs = set.map((i) => core.reasons[i]);
    lines.push(recs.length === 1 ? "This record alone decided it. If it is not your family's, you are eligible:" : `These ${recs.length} records decided it together. All of them would have to be shown not to be your family's:`);
    for (const r of recs) lines.push(`- ${r.record.id} (${r.record.registry}): ${r.record.name}, ${r.record.relation}, ${r.record.locality}, ${r.record.year}, matched to ${r.member} with score ${r.scoreBp.total} (threshold ${r.thresholdBp}).`);
  }
  if (core.previous && core.previous.outcome !== core.outcome) lines.push(`Under the previous rules (v${core.previous.rulesetId}) the decision was ${core.previous.outcome}.`);
  return lines.join("\n");
}

async function renderReceipt(r) {
  const core = r.core;
  const denied = core.outcome === "DENIED";
  const ver = `v${core.rulesetId}`;
  const decisive = core.decisive.flat();
  const counted = core.reasons.length;
  let ex = null;
  try { ex = await getJSON(`data/explanations/${core.application}.json`); } catch { ex = null; }
  if (ex && core.rulesetId !== S.dep.batches[1].rulesetId) ex = null; // explanations are for the v2 receipts
  const prevNote = core.previous
    ? core.previous.outcome !== core.outcome
      ? `<span class="badge warn">Under the earlier rules (v${core.previous.rulesetId}) this was ${core.previous.outcome === "DENIED" ? "refused" : "eligible"}</span>`
      : `<span class="badge plain">Same outcome under the earlier rules (v${core.previous.rulesetId})</span>`
    : "";

  $app.innerHTML = `
  <p class="small"><a href="#/receipts">← All receipts</a></p>
  <div class="layout">
    <div>
      <div class="receipt" id="paper">
        <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center">
          <span class="outcome ${core.outcome}">${denied ? "Refused" : "Eligible"}</span>
          ${prevNote}
        </div>
        <hr class="rule">
        <dl class="kv">
          <dt>Application</dt><dd>${esc(core.application)}</dd>
          <dt>Card</dt><dd>${esc(core.card)}, ${esc(core.locality)}</dd>
          <dt>Decided on</dt><dd>${esc(core.decidedOn)}</dd>
          <dt>Rules</dt><dd>version ${core.rulesetId} · <span title="${esc(core.rulesHash)}">${esc(short(core.rulesHash))}</span></dd>
          <dt>Members checked</dt><dd>${core.members.map((m) => `${esc(m.name)} (${esc(m.relation)}${m.died ? `, died ${m.died}` : ""})`).join("<br>")}</dd>
          <dt>Records compared</dt><dd>${core.recordsChecked} · counted ${counted} · decisive ${decisive.length}</dd>
        </dl>
        <hr class="rule">
        <div class="tiny">Receipt ${esc(short(r.receiptHash, 10))} · batch ${r.batchId}</div>
      </div>

      ${denied ? `<h2>What decided it</h2>
        <p class="muted small">${core.decisive.length === 1 && core.decisive[0].length === 1
          ? "One record decided this. If it isn't your family's, you are eligible."
          : `These ${decisive.length} records decided it together: each one alone was enough, so all of them would have to be shown not to be your family's.`}</p>
        ${core.decisive.map((set) => set.map((i, n) => matchBlock(core, core.reasons[i], n, set.length)).join("")).join("")}`
        : `<h2>Why eligible</h2><p class="muted">The rules compared ${core.recordsChecked} registry records with the people on this card. None scored above the threshold.</p>`}

      <h2>In your language</h2>
      <div class="card">
        <div class="tabs" role="tablist">${Object.entries(LANGS).map(([k, v], i) => `<button class="tab ${i === 0 ? "on" : ""}" data-lang="${k}" role="tab">${v}</button>`).join("")}</div>
        <div id="explain" class="explain"></div>
        <p id="explain-src" class="tiny" style="margin-top:10px"></p>
      </div>

      <div id="appeal"></div>
    </div>

    <aside>
      <div class="card">
        <h3 style="margin-top:0">Is this receipt real?</h3>
        <p class="small muted">Your browser re-hashes the receipt, folds its proof into the batch's root, and asks the contract on Monad testnet. Nothing is sent anywhere but read-only calls.</p>
        <div class="btns"><button class="btn" id="verify">Check against the chain</button><button class="btn ghost" id="tamper">Try to edit it</button></div>
        <ul class="checks verify small" id="vlist"></ul>
      </div>
      <div class="card" style="margin-top:16px" id="share">
        <h3 style="margin-top:0">Keep it</h3>
        <p class="small muted">A printed receipt carries this code. It holds the whole receipt, so it can be checked even if this site goes away.</p>
        <div id="qr" class="qr" aria-label="QR code of this receipt"></div>
        <p class="tiny" id="qr-note"></p>
        <div class="btns"><button class="btn ghost" id="dl">Download receipt</button></div>
      </div>
      <details style="margin-top:16px"><summary>The receipt as data</summary><pre class="json">${esc(JSON.stringify(r, null, 1))}</pre></details>
    </aside>
  </div>`;

  // explanation tabs
  const showLang = (lang) => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.lang === lang));
    const box = document.getElementById("explain");
    const src = document.getElementById("explain-src");
    const e = ex && ex[lang];
    if (e) {
      box.lang = lang;
      box.textContent = e.text;
      src.innerHTML = e.source === "template"
        ? "Template text: the model's drafts failed the check, so the fixed wording is shown."
        : `Written by ${esc(e.source)}. <span class="badge good">checked</span> Every number and record ID in it is on this receipt, and every decisive record is named.`;
    } else {
      box.lang = "en";
      box.textContent = templateExplanation(core);
      src.textContent = lang === "en" ? "Fixed wording built from the receipt." : "A translation exists for the five spotlight families; this receipt shows the fixed English wording.";
    }
  };
  document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => showLang(t.dataset.lang)));
  showLang("en");

  document.getElementById("verify").onclick = () => runChecks(r, false);
  document.getElementById("tamper").onclick = () => tamperDialog(r);
  document.getElementById("dl").onclick = () => {
    const blob = new Blob([JSON.stringify(r, null, 1)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `receipt-${core.application}-b${r.batchId}.json` });
    a.click();
    URL.revokeObjectURL(a.href);
  };
  drawQR(r);
  appealSection(r);
}

async function tamperDialog(r) {
  const core = r.core;
  const options = [];
  if (core.outcome === "DENIED") options.push(["Change the outcome to eligible", (c) => { c.outcome = "ELIGIBLE"; }]);
  else options.push(["Change the outcome to refused", (c) => { c.outcome = "DENIED"; }]);
  if (core.reasons.length) options.push([`Change the year on record ${core.reasons[0].record.id}`, (c) => { c.reasons[0].record.year += 1; }]);
  options.push(["Swap in a different date", (c) => { c.decidedOn = "2020-01-01"; }]);
  const list = document.getElementById("vlist");
  list.innerHTML = `<li class="pending">Pick an edit: ${options.map(([t], i) => `<button class="tab" data-t="${i}" style="margin:4px 4px 0 0">${esc(t)}</button>`).join("")}</li>`;
  list.querySelectorAll("button[data-t]").forEach((b) => (b.onclick = () => {
    const copy = JSON.parse(JSON.stringify(r));
    options[Number(b.dataset.t)][1](copy.core);
    runChecks(copy, true, options[Number(b.dataset.t)][0]);
  }));
}

async function runChecks(r, tampered, what) {
  const list = document.getElementById("vlist");
  list.innerHTML = tampered ? `<li class="flag">Edited copy: ${esc(what)}. The proof and batch are unchanged.</li>` : "";
  const add = (label) => {
    const li = document.createElement("li");
    li.className = "pending";
    li.innerHTML = esc(label);
    list.appendChild(li);
    return (ok, detail) => {
      li.className = ok ? "ok" : "fail";
      if (detail) li.innerHTML += `<span class="detail">${detail}</span>`;
      return ok;
    };
  };
  const core = r.core;
  const code = OUTCOME[core.outcome];
  try {
    const h = receiptHash(core);
    add("The receipt hashes to the hash it carries")(h === r.receiptHash, `${short(h, 10)}${h === r.receiptHash ? "" : ` ≠ ${short(r.receiptHash, 10)}`}`);
    const root = rootOf(leafOf(code, h), r.proof);
    const done = add(`Its proof leads to batch ${r.batchId}'s sealed root`);
    const b = await S.c.batches(r.batchId);
    done(root === b.root.toLowerCase(), `computed ${short(root, 8)} · on-chain ${short(b.root, 8)}`);
    const done2 = add("The contract confirms it: verify(batch, outcome, hash, proof)");
    const ok = await S.c.verify(r.batchId, code, h, r.proof);
    done2(ok, ok ? "returned true" : "returned false");
    const done3 = add(`The decision was made under rules v${core.rulesetId}, as published on-chain`);
    const rs = await S.c.rulesets(core.rulesetId);
    done3(rs.rulesHash === core.rulesHash && rs.agency.toLowerCase() === core.agency, `published ${istDate(rs.publishedAt)} by ${short(rs.agency)}`);
    const done4 = add("The rules file is unchanged since it was published");
    const file = rs.uri.split("/").pop();
    const rules = await getJSON(`data/rules/${file}`);
    const rh = keccakText(canonical(rules));
    done4(rh === rs.rulesHash, `${esc(file)} hashes to ${short(rh, 8)}`);
    add("The rules were public before this batch was sealed")(Number(rs.publishedAt) <= Number(b.sealedAt) && b.sealedAt > 0n, `rules ${istDate(rs.publishedAt)} · sealed ${istDate(b.sealedAt)}`);
    add("It's bound to this contract on this chain")(core.contract === S.dep.contract.toLowerCase() && core.chainId === S.dep.chainId, `chain ${core.chainId} · ${short(core.contract)}`);
  } catch (e) {
    add("Couldn't reach the chain")(false, esc(e.shortMessage || e.message));
  }
}

async function appealSection(r) {
  const box = document.getElementById("appeal");
  const core = r.core;
  if (core.outcome !== "DENIED") return;
  const h = receiptHash(core);
  let id = 0;
  try { id = Number(await S.c.appealOfLeaf(leafOf(OUTCOME.DENIED, h))); } catch { /* shown as not appealed */ }
  if (!id) {
    box.innerHTML = `<h2>Appeal</h2><p class="muted">This decision hasn't been appealed. A legal-aid worker can file the appeal on-chain with the receipt; the family needs no wallet.</p>
      <div class="letter">${esc(templateAppeal(core))}</div>`;
    return;
  }
  const [a, overdue, rs, mine] = await Promise.all([S.c.appeals(id), S.c.isOverdue(id), S.c.rulesets(core.rulesetId), getJSON("data/appeals.json").then((x) => x.find((y) => y.id === id))]);
  const status = Number(a.status);
  const due = Number(a.filedAt) + Number(rs.responseDays) * 86400;
  const letterOk = mine && keccakText(mine.letter) === a.groundsHash;
  const answerOk = mine && mine.answer && keccakText(mine.answer.text) === a.answerHash;
  const badge = status === 2 ? '<span class="badge good">Decision reversed</span>' : status === 1 ? '<span class="badge bad">Decision stands</span>' : overdue ? '<span class="badge bad">Overdue</span>' : '<span class="badge warn">Waiting for the agency</span>';
  box.innerHTML = `<h2>Appeal ${id} ${badge}</h2>
    <p class="small muted">Filed ${istDate(a.filedAt)} by legal aid ${link("address", a.filer)}${mine ? ` · ${link("tx", mine.filed.tx, "transaction")}` : ""}.
    ${status === 0 ? `The agency committed to answer within ${rs.responseDays} days, by ${dayOnly(due)}.` : `Answered ${istDate(a.answeredAt)}${mine && mine.answer ? ` · ${link("tx", mine.answer.tx, "transaction")}` : ""}.`}</p>
    ${mine ? `<h3>The letter <span class="badge ${letterOk ? "good" : "bad"}">${letterOk ? "matches the hash filed on-chain" : "doesn't match the chain"}</span></h3>
      <div class="letter">${esc(mine.letter)}</div>
      <p class="tiny">${mine.letterSource && mine.letterSource !== "template" ? `Drafted by ${esc(mine.letterSource)} from the receipt and what the family told the legal-aid worker, then checked: every number and record ID is on the receipt or in their statement.` : "Fixed wording built from the receipt."}</p>` : ""}
    ${mine && mine.answer ? `<h3>The agency's answer <span class="badge ${answerOk ? "good" : "bad"}">${answerOk ? "matches the hash it sealed" : "doesn't match the chain"}</span></h3><div class="letter">${esc(mine.answer.text)}</div>` : ""}`;
}

function templateAppeal(core) {
  const ids = core.decisive.flat().map((i) => core.reasons[i].record.id).join(", ");
  return ["To the Assistant Supply Officer, Civil Supplies Department",
    `Subject: Appeal against refusal of application ${core.application} (card ${core.card})`, "",
    `My application was refused under rules v${core.rulesetId} because of record(s) ${ids}.`,
    "These records do not belong to my family.", "Please correct the decision and restore our card.", "", "Yours faithfully"].join("\n");
}

// The whole receipt in a link: deflate, then base64url, after #/r/.
async function pack(r) {
  const bytes = new TextEncoder().encode(JSON.stringify(r));
  const cs = new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate-raw"));
  const buf = new Uint8Array(await new Response(cs).arrayBuffer());
  let s = "";
  buf.forEach((b) => (s += String.fromCharCode(b)));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
async function unpack(data) {
  const b64 = data.replace(/-/g, "+").replace(/_/g, "/");
  const bin = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
  const ds = new Blob([bin]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return JSON.parse(await new Response(ds).text());
}

async function drawQR(r) {
  const el = document.getElementById("qr");
  const note = document.getElementById("qr-note");
  if (typeof qrcode !== "function" || typeof CompressionStream !== "function") {
    document.getElementById("share").querySelector(".qr").remove();
    return;
  }
  const url = `${location.origin}${location.pathname}#/r/${await pack(r)}`;
  try {
    const q = qrcode(0, "L");
    q.addData(url);
    q.make();
    el.innerHTML = q.createSvgTag({ cellSize: 2, margin: 0, scalable: true });
    note.innerHTML = `${url.length} characters · <a href="${esc(url)}">open the link</a>`;
  } catch {
    el.remove();
    note.innerHTML = `<a href="${esc(url)}">A link holding the whole receipt</a> (too long for a QR code).`;
  }
}

// ---------- public record

async function record() {
  $app.innerHTML = `<h1>Public record</h1><p class="loading">Reading the contract on Monad testnet…</p>`;
  const [st, appealTexts, truth, r1, r2] = await Promise.all([chainState(), getJSON("data/appeals.json"), getJSON("data/synthetic-truth.json"), getJSON("data/rules/v1.json"), getJSON("data/rules/v2.json")]);
  const openOverdue = st.appeals.filter((a) => a.status === 0 && a.overdue).length;
  const totalDecisions = st.rulesets.reduce((s, r) => s + r.decisions, 0);
  const rs = st.rulesets;
  const maxRate = Math.max(...rs.map((r) => r.denied / Math.max(1, r.decisions)));

  const refusalRows = rs.map((r) => `<div class="row"><div class="name">Rules v${r.id}</div><div class="track">
      <div class="bar" style="width:${(55 * r.denied / Math.max(1, r.decisions)) / maxRate}%"><div class="seg" style="width:100%;background:var(--series-1)" data-tip="Rules v${r.id}: ${r.denied} of ${r.decisions} refused (${pct(r.denied, r.decisions)})"></div></div>
      <span class="val">${pct(r.denied, r.decisions)} · ${r.denied} of ${r.decisions}</span></div></div>`).join("");

  const maxAppeals = Math.max(...rs.map((r) => r.appeals), 1);
  const appealRows = rs.map((r) => {
    const open = r.appeals - r.upheld - r.overturned;
    const w = (n) => (100 * n) / maxAppeals;
    const seg = (n, color, label) => (n ? `<div class="seg" style="width:${(100 * n) / r.appeals}%;background:${color}" data-tip="Rules v${r.id}: ${n} ${label}"></div>` : "");
    return `<div class="row"><div class="name">Rules v${r.id}</div><div class="track"><div class="bar" style="width:${w(r.appeals) * 0.55}%">
      ${seg(r.overturned, "var(--series-1)", "reversed")}${seg(r.upheld, "var(--series-2)", "upheld")}${seg(open, "var(--series-3)", "still open")}</div>
      <span class="val">${r.appeals} appeals · ${pct(r.overturned, r.overturned + r.upheld)} of answered reversed</span></div></div>`;
  }).join("");

  const diffRows = [];
  const walk = (a, b, path) => {
    const keys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
    for (const k of keys) {
      if (["code", "version", "change_from_previous"].includes(k)) continue;
      const va = a ? a[k] : undefined, vb = b ? b[k] : undefined;
      if (va && vb && typeof va === "object" && !Array.isArray(va)) walk(va, vb, `${path}${k}.`);
      else if (JSON.stringify(va) !== JSON.stringify(vb)) diffRows.push([`${path}${k}`, va, vb]);
    }
  };
  walk(r1, r2, "");

  $app.innerHTML = `
  <h1>Public record</h1>
  <p class="muted">${esc(st.agencyName)} · agency ${link("address", S.dep.agency)} · contract ${link("address", S.dep.contract)}. Everything on this page is read from the chain just now, except the letter texts, which are checked against the hashes on-chain.</p>
  <div class="grid grid-3" style="margin-top:18px">
    <div class="card stat"><div class="label">Decisions sealed</div><div class="value">${totalDecisions.toLocaleString("en-IN")}</div><div class="sub">in ${st.batches.length} batches under ${rs.length} rule versions</div></div>
    <div class="card stat"><div class="label">Appeals filed</div><div class="value">${st.appeals.length}</div><div class="sub">${st.appeals.filter((a) => a.status === 2).length} reversed · ${st.appeals.filter((a) => a.status === 1).length} upheld · ${st.appeals.filter((a) => a.status === 0).length} open</div></div>
    <div class="card stat"><div class="label">Overdue answers</div><div class="value">${openOverdue}</div><div class="sub">${openOverdue ? "past the response time the agency committed to" : `the open ones are due by ${[...new Set(st.appeals.filter((a) => a.status === 0).map((a) => dayOnly(Number(a.filedAt) + 86400 * rs.find((x) => x.id === st.batches.find((b) => b.id === a.batchId).rulesetId).responseDays)))].join(", ") || "—"}`}</div></div>
  </div>

  <h2>What changed when the rules changed</h2>
  <div class="grid grid-2">
    <div class="card"><h3 style="margin-top:0">Share of households refused</h3><div class="chart" id="c1">${refusalRows}</div></div>
    <div class="card"><h3 style="margin-top:0">What happened on appeal</h3><div class="chart" id="c2">${appealRows}</div>
      <div class="legend"><span><i style="background:var(--series-1)"></i>Reversed</span><span><i style="background:var(--series-2)"></i>Upheld</span><span><i style="background:var(--series-3)"></i>Still open</span></div></div>
  </div>
  <div class="scroll" style="margin-top:16px"><table class="data">
    <tr><th>Rules</th><th>Published</th><th class="num">Decisions</th><th class="num">Refused</th><th class="num">Appeals</th><th class="num">Reversed</th><th class="num">Upheld</th><th class="num">Open</th><th>Rules file hash</th></tr>
    ${rs.map((r) => `<tr><td>v${r.id}</td><td>${istDate(r.publishedAt)}</td><td class="num">${r.decisions}</td><td class="num">${r.denied} (${pct(r.denied, r.decisions)})</td><td class="num">${r.appeals}</td><td class="num">${r.overturned}</td><td class="num">${r.upheld}</td><td class="num">${r.appeals - r.upheld - r.overturned}</td><td><a class="mono" href="data/rules/v${r.id}.json">${short(r.rulesHash)}</a></td></tr>`).join("")}
  </table></div>

  <h3>The change itself</h3>
  <p class="small muted">${esc(r2.change_from_previous || "")}</p>
  <div class="scroll"><table class="data"><tr><th>Setting</th><th>v1</th><th>v2</th></tr>
    ${diffRows.map(([k, a, b]) => `<tr><td class="mono">${esc(k)}</td><td>${esc(JSON.stringify(a))}</td><td>${esc(JSON.stringify(b))}</td></tr>`).join("")}</table></div>

  <div class="note" style="margin-top:20px">
    <b>What only a demo can show.</b> The data is synthetic, so we know the truth. Of ${truth.householdsReallyIneligible} households that really are outside the scheme, v1 caught ${truth.batch1.deniedRightly} and wrongly refused ${truth.batch1.deniedWrongly} others. v2 caught ${truth.batch2.deniedRightly}, and wrongly refused ${truth.batch2.deniedWrongly}. A real auditor never sees this column. What they can see is above: how many decisions each version made, how many it refused, and how often its refusals were reversed on appeal.
  </div>

  <h2>Batches</h2>
  <div class="scroll"><table class="data"><tr><th>Batch</th><th>Rules</th><th>Sealed</th><th class="num">Decisions</th><th class="num">Refused</th><th>Root</th></tr>
    ${st.batches.map((b) => { const tx = S.dep.batches.find((x) => x.id === b.id); return `<tr><td>${b.id}</td><td>v${b.rulesetId}</td><td>${istDate(b.sealedAt)}</td><td class="num">${b.count}</td><td class="num">${b.denied}</td><td class="mono">${tx ? link("tx", tx.tx, short(b.root)) : short(b.root)}</td></tr>`; }).join("")}</table></div>

  <h2>Appeals</h2>
  <div class="scroll"><table class="data"><tr><th>#</th><th>Rules</th><th>Filed</th><th>Status</th><th>Answered or due</th><th>Letter</th><th>Answer</th></tr>
    ${st.appeals.map((a) => {
      const t = appealTexts.find((x) => x.id === a.id);
      const b = st.batches.find((x) => x.id === a.batchId);
      const rset = rs.find((x) => x.id === b.rulesetId);
      const due = Number(a.filedAt) + 86400 * rset.responseDays;
      const lOk = t && keccakText(t.letter) === a.groundsHash;
      const aOk = t && t.answer && keccakText(t.answer.text) === a.answerHash;
      const status = a.status === 0 ? (a.overdue ? '<span class="badge bad">Overdue</span>' : '<span class="badge warn">Open</span>') : a.status === 2 ? '<span class="badge good">Reversed</span>' : '<span class="badge plain">Upheld</span>';
      const file = t ? `${t.application}-b${a.batchId}.json` : null;
      return `<tr><td>${file ? `<a href="#/receipt/${file}">${a.id}</a>` : a.id}</td><td>v${b.rulesetId}</td><td>${dayOnly(a.filedAt)}</td><td>${status}</td>
        <td>${a.status === 0 ? `due ${dayOnly(due)}` : dayOnly(a.answeredAt)}</td>
        <td>${t ? `<span class="badge ${lOk ? "good" : "bad"}">${lOk ? "✓ hash" : "✗ hash"}</span>` : "—"}</td>
        <td>${a.status === 0 ? "—" : t && t.answer ? `<span class="badge ${aOk ? "good" : "bad"}">${aOk ? "✓ hash" : "✗ hash"}</span>` : "—"}</td></tr>`;
    }).join("")}</table></div>`;
  wireTips();
}

function wireTips() {
  const tip = document.getElementById("tip");
  document.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("mousemove", (e) => {
      tip.textContent = el.dataset.tip;
      tip.style.display = "block";
      tip.style.left = `${Math.min(e.clientX + 12, window.innerWidth - 270)}px`;
      tip.style.top = `${e.clientY + 14}px`;
    });
    el.addEventListener("mouseleave", () => (tip.style.display = "none"));
  });
}

// ---------- how it works

async function how() {
  $app.innerHTML = `
  <h1>How it works</h1>
  <ol class="steps" style="max-width:760px;margin-top:20px">
    <li><b>The agency publishes its rules.</b> Each version of the matching rules is a JSON file: which registries count, how names are compared, the weights, the threshold, and the hash of the code that applies them. The agency calls <code>publishRuleset(hash, uri, responseDays)</code>, committing to answer appeals within that many days.</li>
    <li><b>Decisions are made off-chain, as now.</b> For every household, the engine compares each member on the card with the vehicle, income-tax and payroll registries and records every match that counts.</li>
    <li><b>Only the decisive records are listed as reasons.</b> The engine removes records and re-runs the rules. A record is a reason only if taking it away changes the outcome. Under these rules any one match is enough to refuse, so every counted record is decisive and all of them must fall for the family to qualify. A ruleset that scores or combines evidence gets the same test with no change to the receipt.</li>
    <li><b>Each decision becomes a salted receipt.</b> Its hash, joined with the outcome, is a leaf in a Merkle tree. The agency seals the batch with one call, <code>sealBatch(rulesetId, root, count, refused)</code>. The contract refuses rules that weren't public in an earlier block.</li>
    <li><b>The family gets the receipt</b> on paper with a QR code, or by link. Gemini explains it in Telugu, Hindi or English. A guard checks every number and record ID in the text against the receipt and rejects the draft if one is missing or invented.</li>
    <li><b>An appeal goes on the record.</b> A legal-aid worker files it with the receipt's proof (<code>fileAppeal</code>); the contract accepts appeals only against sealed refusals. The agency's answer is sealed with <code>answerAppeal</code>, and anyone can see which appeals are past due.</li>
  </ol>
  <h2>Why a chain, and not the agency's own database?</h2>
  <p style="max-width:760px">Because the agency is the party being checked. A log the agency keeps can be edited by the agency. Here the rules, the batches and the appeals are fixed the moment they're written, by someone other than the agency, and anyone can check them without asking permission. Nothing personal goes on-chain: only hashes of salted receipts, which reveal nothing without the receipt itself.</p>
  <h2>What it doesn't do</h2>
  <ul style="max-width:760px">
    <li>It can't prove the agency ran the published rules on every household. It proves which rules it said it ran, when, and what it decided; a family or auditor holding a receipt can re-run the rules and catch a mismatch.</li>
    <li>It can't force an answer. It makes a missing answer visible, with a date.</li>
    <li>The demo's agency, households and registries are invented. The contract, seals and appeals are real Monad testnet transactions.</li>
  </ul>`;
}

boot();
