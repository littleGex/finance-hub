"use strict";
/* Accounts tab: IBANs, balances, pots and regular payments. Uses helpers from app.js (window.FH). */
(() => {
  const { api, el, toast, money, parseAmount, fmtDate, jsonReq, refresh, wireDrop, importCsv, BANK_NAMES } = window.FH;
  const $ = (id) => document.getElementById(id);
  const FREQ = { monthly: "Monthly", quarterly: "Quarterly", yearly: "Yearly" };

  let accounts = [];
  let editing = null;          // payment being edited, or null for a new one
  let fromAccountId = null;    // account a new payment is paid from

  const amountOrThrow = (v) => {
    const n = parseAmount(v);
    if (!Number.isFinite(n)) throw new Error("That is not an amount");
    return n;
  };
  const deAmount = (n) => n.toFixed(2).replace(".", ",");
  const groupIban = (iban) => iban.replace(/(.{4})/g, "$1 ").trim();
  const thisMonth = () => new Date().toISOString().slice(0, 7);

  /** Replace `node` with a small form; restores it on Cancel. Re-renders everything after a successful save. */
  function inlineEdit(node, fields, onSave) {
    const inputs = fields.map((f) => el("input", {
      value: f.value ?? "", placeholder: f.placeholder, "aria-label": f.placeholder, inputmode: f.inputmode || "text",
    }));
    const form = el("form", { class: "inline-edit" }, ...inputs,
      el("button", { class: "primary small", type: "submit" }, "Save"),
      el("button", { class: "link", type: "button", onclick: () => form.replaceWith(node) }, "Cancel"));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await onSave(...inputs.map((i) => i.value)); await refresh(); }
      catch (err) { toast(err.message, true); }
    });
    node.replaceWith(form);
    inputs[0].focus();
    inputs[0].select();
  }

  function confirmDialog(text, okLabel = "Delete") {
    const d = $("confirm-dialog");
    $("confirm-text").textContent = text;
    $("confirm-ok").textContent = okLabel;
    d.returnValue = "";
    d.showModal();
    return new Promise((resolve) => d.addEventListener("close", () => resolve(d.returnValue === "ok"), { once: true }));
  }

  /* ---------- account card ---------- */

  function ibanRow(a) {
    const row = el("div", { class: "iban-row" },
      el("span", { class: "sub" }, a.iban ? "IBAN " + groupIban(a.iban) : "No IBAN yet (needed to spot transfers)"),
      el("button", {
        class: "link", onclick: () => inlineEdit(row, [{ value: a.iban ? groupIban(a.iban) : "", placeholder: "IBAN" }],
          (v) => api(`/api/accounts/${a.id}`, jsonReq("PATCH", { iban: v.trim() || null }))),
      }, a.iban ? "Edit" : "Add IBAN"));
    return row;
  }

  function buttonRow(a) {
    const file = el("input", { type: "file", accept: ".csv,text/csv", hidden: "" });
    file.addEventListener("change", () => importCsv(a.id, file.files[0]));
    const row = el("div", { class: "btn-row" },
      el("button", {
        class: "link", onclick: () => inlineEdit(row, [{ value: deAmount(a.balance), placeholder: "Current balance", inputmode: "decimal" }],
          (v) => api(`/api/accounts/${a.id}/balance`, jsonReq("POST", { balance: amountOrThrow(v) }))),
      }, "Set balance"),
      el("button", { class: "link", onclick: () => file.click() }, "Import CSV"),
      file);
    return row;
  }

  function potsSection(a) {
    const out = [];
    if (a.pots.length) {
      const list = el("ul", { class: "rows" });
      for (const p of a.pots) {
        const li = el("li", {},
          el("div", { class: "main" }, el("div", { class: "title" }, p.name)),
          el("div", { class: "right" },
            el("span", { class: "amt" }, money(p.balance)),
            el("button", {
              class: "link", onclick: () => inlineEdit(li, [{ value: deAmount(p.balance), placeholder: `${p.name} balance`, inputmode: "decimal" }],
                (v) => api(`/api/pots/${p.id}`, jsonReq("PATCH", { balance: amountOrThrow(v) }))),
            }, "Set"),
            el("button", { class: "link danger", "aria-label": `Remove pot ${p.name}`, onclick: () => removePot(p) }, "✕")));
        list.append(li);
      }
      const negative = a.unassigned < 0;
      list.append(el("li", { class: "unassigned" },
        el("div", { class: "main" },
          el("div", { class: "title" }, "Unassigned"),
          negative ? el("div", { class: "sub warn" }, "Pots add up to more than the account holds") : ""),
        el("span", { class: "amt" + (negative ? " warn" : "") }, money(a.unassigned))));
      out.push(el("h3", { class: "section-h" }, "Pots"), list);
    }
    const add = el("button", {
      class: "link add-link", onclick: () => inlineEdit(add,
        [{ placeholder: "Pot name, e.g. Children" }, { placeholder: "Balance today", inputmode: "decimal" }],
        (name, balance) => api(`/api/accounts/${a.id}/pots`, jsonReq("POST", {
          name, balance: balance.trim() ? amountOrThrow(balance) : 0,
        }))),
    }, "+ Add pot");
    out.push(add);
    return out;
  }

  async function removePot(p) {
    if (!(await confirmDialog(`Remove the pot “${p.name}”? Its balance goes back to Unassigned.`, "Remove"))) return;
    try { await fetchDelete(`/api/pots/${p.id}`); await refresh(); }
    catch (e) { toast(e.message, true); }
  }

  function targetText(r) {
    if (r.to_account_id == null) return "";
    const acc = accounts.find((a) => a.id === r.to_account_id);
    const pot = acc && acc.pots.find((p) => p.id === r.to_pot_id);
    return ` · → ${acc ? acc.name : "?"}${pot ? " · " + pot.name : ""}`;
  }

  function paymentsSection(a, recurring) {
    const items = recurring.filter((r) => r.from_account_id === a.id);
    const out = [el("h3", { class: "section-h" }, "Regular payments")];
    if (items.length) {
      const list = el("ul", { class: "rows" });
      for (const r of items) {
        const when = r.active ? (r.next_due ? `next ${fmtDate(r.next_due)}` : "") : "paused";
        const li = el("li", { class: "payment-row" + (r.active ? "" : " paused"), tabindex: "0", role: "button" },
          el("div", { class: "main" },
            el("div", { class: "title" }, r.name, r.to_account_id != null ? el("span", { class: "badge transfer" }, "Transfer") : ""),
            el("div", { class: "sub" }, `${FREQ[r.frequency]} · ${when}${targetText(r)}`)),
          el("span", { class: "amt" }, money(r.amount)));
        li.addEventListener("click", () => openPayment(r));
        li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPayment(r); } });
        list.append(li);
      }
      out.push(list);
    }
    out.push(el("button", { class: "link add-link", onclick: () => openPayment(null, a.id) }, "+ Add payment"));
    return out;
  }

  function accountCard(a, recurring) {
    const card = el("section", { class: "card acct-card" },
      el("div", { class: "card-head" },
        el("div", {}, el("h2", {}, a.name), el("div", { class: "sub" }, BANK_NAMES[a.bank] || a.bank)),
        el("div", { class: "amt big" }, money(a.balance))),
      ibanRow(a),
      buttonRow(a),
      ...potsSection(a),
      ...paymentsSection(a, recurring));
    wireDrop(card, (file) => importCsv(a.id, file));
    return card;
  }

  window.renderAccountsTab = (summary, recurring) => {
    accounts = summary.accounts;
    const box = $("account-cards");
    box.replaceChildren();
    if (!accounts.length) box.append(el("section", { class: "card" }, el("p", { class: "sub" }, "No accounts yet. Tap Add account.")));
    for (const a of accounts) box.append(accountCard(a, recurring));
  };

  /* ---------- payment dialog ---------- */

  const form = $("payment-form");
  const field = (name) => form.elements[name];

  function fillPots(selectedPotId) {
    const acc = accounts.find((a) => a.id === Number(field("to_account_id").value));
    const pots = acc ? acc.pots : [];
    $("pot-field").hidden = !pots.length;
    field("to_pot_id").replaceChildren(
      el("option", { value: "" }, "No specific pot"),
      ...pots.map((p) => el("option", { value: String(p.id) }, p.name)));
    field("to_pot_id").value = pots.some((p) => p.id === selectedPotId) ? String(selectedPotId) : "";
  }

  function openPayment(item, accountId) {
    editing = item;
    fromAccountId = item ? item.from_account_id : accountId;
    const from = accounts.find((a) => a.id === fromAccountId);
    $("payment-title").textContent = (item ? "Edit payment" : "New payment") + (from ? ` · ${from.name}` : "");
    field("name").value = item ? item.name : "";
    field("amount").value = item ? deAmount(item.amount) : "";
    field("frequency").value = item ? item.frequency : "monthly";
    field("due_day").value = item ? item.due_day : 1;
    field("start_month").value = item ? item.start_month : thisMonth();
    field("to_account_id").replaceChildren(
      el("option", { value: "" }, "Nothing (it's a bill)"),
      ...accounts.filter((a) => a.id !== fromAccountId).map((a) => el("option", { value: String(a.id) }, a.name)));
    field("to_account_id").value = item && item.to_account_id != null ? String(item.to_account_id) : "";
    fillPots(item ? item.to_pot_id : null);
    $("payment-delete").hidden = !item;
    $("payment-pause").hidden = !item;
    $("payment-pause").textContent = item && !item.active ? "Resume" : "Pause";
    $("payment-dialog").showModal();
    field("name").focus();
  }

  field("to_account_id").addEventListener("change", () => fillPots(null));
  $("payment-cancel").addEventListener("click", () => $("payment-dialog").close());

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const toAccount = field("to_account_id").value;
      const body = {
        name: field("name").value.trim(),
        amount: amountOrThrow(field("amount").value),
        from_account_id: fromAccountId,
        frequency: field("frequency").value,
        due_day: Number(field("due_day").value),
        start_month: field("start_month").value.trim(),
        to_account_id: toAccount ? Number(toAccount) : null,
        to_pot_id: toAccount && field("to_pot_id").value ? Number(field("to_pot_id").value) : null,
      };
      if (!body.name) throw new Error("Please give the payment a name");
      if (editing) await api(`/api/recurring/${editing.id}`, jsonReq("PATCH", body));
      else await api("/api/recurring", jsonReq("POST", body));
      $("payment-dialog").close();
      await refresh();
    } catch (err) { toast(err.message, true); }        // dialog stays open so nothing typed is lost
  });

  $("payment-pause").addEventListener("click", async () => {
    try {
      await api(`/api/recurring/${editing.id}`, jsonReq("PATCH", { active: !editing.active }));
      $("payment-dialog").close();
      await refresh();
    } catch (err) { toast(err.message, true); }
  });

  $("payment-delete").addEventListener("click", async () => {
    const item = editing;
    $("payment-dialog").close();
    if (!(await confirmDialog(`Delete “${item.name}”? Pot balances keep what was already paid in.`))) return;
    try { await fetchDelete(`/api/recurring/${item.id}`); await refresh(); }
    catch (err) { toast(err.message, true); }
  });

  /** DELETE endpoints answer 204 with no body, which api() can't parse as JSON. */
  async function fetchDelete(path) {
    const r = await fetch(path, { method: "DELETE" });
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail || detail; } catch {}
      throw new Error(detail);
    }
  }
})();
