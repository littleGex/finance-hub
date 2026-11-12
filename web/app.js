"use strict";

const $ = (id) => document.getElementById(id);
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const RING_COLORS = { savings: "#ff2d55", budget: "#30d158", fresh: "#64d2ff" };
const RING_RADII = { savings: 88, budget: 66, fresh: 44 };
const BANK_NAMES = { sparkasse: "Sparkasse", ing: "ING", bos: "Bank of Scotland", other: "Other" };
const NS = "http://www.w3.org/2000/svg";

let lastLevel = null;

/* ---------- helpers ---------- */
const eur = (n) => new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(n);
const money = (n) => new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" }).format(n);

function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const kid of kids) e.append(kid);
  return e;
}

function toast(msg, isError = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "show" + (isError ? " error" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = ""), 3200);
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return r.json();
}

function countUp(node, to, format, ms = 900) {
  const from = Number(node.dataset.v || 0);
  node.dataset.v = to;
  if (reduceMotion || from === to) { node.textContent = format(to); return; }
  const start = performance.now();
  const step = (now) => {
    const p = Math.min(1, (now - start) / ms);
    const eased = 1 - Math.pow(1 - p, 3);
    node.textContent = format(from + (to - from) * eased);
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ---------- confetti ---------- */
function confetti() {
  if (reduceMotion) return;
  const c = $("confetti"), ctx = c.getContext("2d");
  c.width = innerWidth * devicePixelRatio; c.height = innerHeight * devicePixelRatio;
  const colors = ["#ff2d55", "#30d158", "#64d2ff", "#ffd60a", "#bf5af2", "#0a84ff"];
  const parts = Array.from({ length: 110 }, () => ({
    x: c.width / 2, y: c.height * 0.35,
    vx: (Math.random() - 0.5) * 16 * devicePixelRatio, vy: (Math.random() * -14 - 4) * devicePixelRatio,
    s: (Math.random() * 6 + 4) * devicePixelRatio, r: Math.random() * 6, vr: (Math.random() - 0.5) * 0.4,
    col: colors[(Math.random() * colors.length) | 0],
  }));
  let frames = 0;
  (function tick() {
    ctx.clearRect(0, 0, c.width, c.height);
    for (const p of parts) {
      p.vy += 0.45 * devicePixelRatio; p.x += p.vx; p.y += p.vy; p.r += p.vr;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r);
      ctx.fillStyle = p.col; ctx.globalAlpha = Math.max(0, 1 - frames / 110);
      ctx.fillRect(-p.s / 2, -p.s / 4, p.s, p.s / 2); ctx.restore();
    }
    if (++frames < 110) requestAnimationFrame(tick); else ctx.clearRect(0, 0, c.width, c.height);
  })();
}

/* ---------- rings ---------- */
function buildRings() {
  const svg = $("rings");
  for (const key of Object.keys(RING_RADII)) {
    const r = RING_RADII[key], circ = 2 * Math.PI * r;
    const track = document.createElementNS(NS, "circle");
    track.setAttribute("class", "ring-track"); track.setAttribute("cx", 100); track.setAttribute("cy", 100);
    track.setAttribute("r", r); track.setAttribute("stroke", RING_COLORS[key]);
    const bar = document.createElementNS(NS, "circle");
    bar.setAttribute("class", "ring-bar"); bar.id = "ring-" + key;
    bar.setAttribute("cx", 100); bar.setAttribute("cy", 100); bar.setAttribute("r", r);
    bar.setAttribute("stroke", RING_COLORS[key]);
    bar.style.strokeDasharray = circ; bar.style.strokeDashoffset = circ;
    svg.append(track, bar);
  }
}

function renderRings(rings) {
  const legend = $("ring-legend");
  legend.replaceChildren();
  for (const key of Object.keys(RING_RADII)) {
    const ring = rings[key], r = RING_RADII[key], circ = 2 * Math.PI * r;
    // Two frames so the CSS transition animates from empty.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      $("ring-" + key).style.strokeDashoffset = circ * (1 - ring.value);
    }));
    legend.append(el("li", {},
      el("span", { class: "dot", style: `background:${RING_COLORS[key]}` }),
      el("b", {}, `${ring.label} · ${Math.round(ring.value * 100)}%`),
      el("small", {}, ring.detail)));
  }
}

/* ---------- rendering ---------- */
async function refresh() {
  const [s, payslips, txs] = await Promise.all([
    api("/api/summary"), api("/api/payslips"), api("/api/transactions?limit=12"),
  ]);

  countUp($("networth"), s.net_worth_eur, eur);
  $("level-chip").textContent = `Level ${s.game.level} · ${s.game.xp} XP`;
  $("streak-chip").textContent = `🔥 ${s.streak_months}-month streak`;
  $("xpfill").style.width = `${Math.round(s.game.progress * 100)}%`;
  if (lastLevel !== null && s.game.level > lastLevel) { confetti(); toast(`Level up! You're now level ${s.game.level}`); }
  lastLevel = s.game.level;
  renderRings(s.rings);

  const accounts = $("accounts");
  accounts.replaceChildren();
  if (!s.accounts.length) accounts.append(el("li", {}, el("span", { class: "sub" }, "No accounts yet. Tap Add.")));
  for (const a of s.accounts) accounts.append(accountRow(a));

  const ps = $("payslips");
  ps.replaceChildren();
  for (const p of payslips.slice(0, 6)) {
    ps.append(el("li", {},
      el("div", { class: "main" },
        el("div", { class: "title" }, p.period || "Period not detected", p.needs_review ? el("span", { class: "badge" }, "Review") : ""),
        el("div", { class: "sub" }, p.net != null ? `Net ${money(p.net)}` : "Amounts not read")),
      el("span", { class: "sub" }, p.stored_path.split("/").slice(-2).join("/"))));
  }

  const list = $("transactions");
  list.replaceChildren();
  if (!txs.length) list.append(el("li", {}, el("span", { class: "sub" }, "Nothing imported yet.")));
  for (const t of txs) {
    list.append(el("li", {},
      el("div", { class: "main" },
        el("div", { class: "title" }, t.counterparty || t.description || "Transaction"),
        el("div", { class: "sub" }, `${t.booked_on} · ${t.account}`)),
      el("span", { class: "amt " + (t.amount >= 0 ? "pos" : "neg") }, money(t.amount))));
  }
}

function accountRow(a) {
  const input = el("input", { type: "file", accept: ".csv,text/csv", hidden: "" });
  const row = el("li", { class: "account-row", tabindex: "0" },
    el("div", { class: "main" },
      el("div", { class: "title" }, a.name),
      el("div", { class: "sub" }, `${BANK_NAMES[a.bank] || a.bank} · ${a.last_tx ? "last tx " + a.last_tx : "no data yet"}`)),
    el("div", {},
      el("div", { class: "amt" }, money(a.balance)),
      el("button", { class: "link", onclick: (e) => { e.stopPropagation(); setBalance(a); } }, "Set balance")),
    input);
  const upload = async (file) => {
    if (!file) return;
    try {
      const fd = new FormData(); fd.append("file", file);
      const r = await api(`/api/import/${a.id}`, { method: "POST", body: fd });
      toast(`${r.rows_new} new, ${r.rows_duplicate} already known`);
      if (r.rows_new) confetti();
      await refresh();
    } catch (e) { toast(e.message, true); }
  };
  row.addEventListener("click", () => input.click());
  row.addEventListener("keydown", (e) => { if (e.key === "Enter") input.click(); });
  input.addEventListener("click", (e) => e.stopPropagation());
  input.addEventListener("change", () => upload(input.files[0]));
  wireDrop(row, upload);
  return row;
}

async function setBalance(a) {
  const v = prompt(`Current balance of ${a.name} (EUR)`, a.balance);
  if (v === null) return;
  const n = Number(v.replace(",", "."));
  if (!Number.isFinite(n)) return toast("That is not a number", true);
  try {
    await api(`/api/accounts/${a.id}/balance`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ balance: n }) });
    await refresh();
  } catch (e) { toast(e.message, true); }
}

function wireDrop(node, onFile) {
  ["dragenter", "dragover"].forEach((ev) => node.addEventListener(ev, (e) => { e.preventDefault(); node.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => node.addEventListener(ev, (e) => { e.preventDefault(); node.classList.remove("over"); }));
  node.addEventListener("drop", (e) => onFile(e.dataTransfer.files[0]));
}

/* ---------- payslip drop ---------- */
async function uploadPayslip(file) {
  if (!file) return;
  try {
    const fd = new FormData(); fd.append("file", file);
    const r = await api("/api/payslips", { method: "POST", body: fd });
    toast(r.needs_review ? "Filed. Please check the details" : `Filed payslip ${r.period}`, false);
    if (!r.needs_review) confetti();
    await refresh();
  } catch (e) { toast(e.message, true); }
}

/* ---------- init ---------- */
buildRings();
const drop = $("payslip-drop");
wireDrop(drop, uploadPayslip);
$("payslip-input").addEventListener("change", (e) => uploadPayslip(e.target.files[0]));

$("add-account").addEventListener("click", () => $("account-dialog").showModal());
$("account-form").addEventListener("submit", async (e) => {
  const submitter = e.submitter && e.submitter.value;
  if (submitter !== "ok") return;
  const fd = new FormData(e.target);
  try {
    await api("/api/accounts", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: fd.get("name"), bank: fd.get("bank") }) });
    e.target.reset();
    await refresh();
  } catch (err) { toast(err.message, true); }
});

refresh().catch((e) => toast(e.message, true));
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
