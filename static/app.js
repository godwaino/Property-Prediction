/* ══════════════════════════════════════════════════════════════════════════════
   Predictelligence Property — Frontend JS v2
   Premium bento-grid results renderer with score ring & step loader
   ══════════════════════════════════════════════════════════════════════════════ */
"use strict";

// ── Helpers ───────────────────────────────────────────────────────────────────

function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class")     e.className = v;
      else if (k === "html") e.innerHTML = v;
      else if (k === "style") e.setAttribute("style", v);
      else e.setAttribute(k, v);
    }
  }
  for (const c of children) {
    if (c == null) continue;
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
}

function div(cls, ...children) { return el("div", { class: cls }, ...children); }
function span(cls, text) { const s = el("span", { class: cls }); if (text != null) s.textContent = text; return s; }

function fmtMoney(v) {
  if (v == null || !isFinite(+v)) return "—";
  return "£" + (+v).toLocaleString("en-GB", { maximumFractionDigits: 0 });
}

function fmtPct(v, plusSign = true) {
  if (v == null) return "—";
  const n = +v;
  return (plusSign && n >= 0 ? "+" : "") + n.toFixed(1) + "%";
}

function num(v) { const n = +v; return isFinite(n) ? n : null; }

function scoreCls(score) {
  if (score >= 70) return "high";
  if (score >= 45) return "medium";
  return "low";
}

function badgeCls(score) {
  if (score >= 70) return "badge-green";
  if (score >= 45) return "badge-amber";
  return "badge-red";
}

function scoreColor(score) {
  if (score >= 70) return "var(--green)";
  if (score >= 45) return "var(--amber)";
  return "var(--red)";
}

// ── Score Ring (SVG donut) ────────────────────────────────────────────────────

function buildScoreRing(score, size = 96) {
  const r = (size / 2) - 9;
  const circumference = 2 * Math.PI * r;
  const pct = Math.min(Math.max(score, 0), 100) / 100;
  const offset = circumference * (1 - pct);
  const color = scoreColor(score);
  const cx = size / 2;

  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.setAttribute("class", "score-ring-svg");

  const bg = document.createElementNS(ns, "circle");
  bg.setAttribute("class", "score-ring-bg");
  bg.setAttribute("cx", cx); bg.setAttribute("cy", cx); bg.setAttribute("r", r);
  bg.setAttribute("stroke-width", "7");

  const fill = document.createElementNS(ns, "circle");
  fill.setAttribute("class", "score-ring-fill");
  fill.setAttribute("cx", cx); fill.setAttribute("cy", cx); fill.setAttribute("r", r);
  fill.setAttribute("stroke-width", "7");
  fill.setAttribute("stroke", color);
  fill.setAttribute("stroke-dasharray", `${circumference} ${circumference}`);
  fill.setAttribute("stroke-dashoffset", circumference); // start at 0 for animation

  const txt = document.createElementNS(ns, "text");
  txt.setAttribute("class", "score-ring-text");
  txt.setAttribute("x", cx); txt.setAttribute("y", cx - 5);
  txt.setAttribute("fill", color);
  txt.textContent = score;

  const lbl = document.createElementNS(ns, "text");
  lbl.setAttribute("class", "score-ring-label");
  lbl.setAttribute("x", cx); lbl.setAttribute("y", cx + 14);
  lbl.textContent = "/ 100";

  svg.appendChild(bg);
  svg.appendChild(fill);
  svg.appendChild(txt);
  svg.appendChild(lbl);

  // Animate the ring after paint
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      fill.style.transition = "stroke-dashoffset 1.2s cubic-bezier(.22,1,.36,1)";
      fill.setAttribute("stroke-dashoffset", offset);
    });
  });

  const wrap = div("score-ring-wrap");
  wrap.appendChild(svg);
  return wrap;
}

// ── Main render entry ─────────────────────────────────────────────────────────

function renderResult(result) {
  const area = document.getElementById("result-area");
  area.innerHTML = "";
  area.style.display = "block";

  const facts      = result.facts      || {};
  const valuation  = result.valuation  || {};
  const strategy   = valuation.strategy || {};
  const comps      = result.comps      || [];
  const prediction = result.prediction;
  const enrichment = result.enrichment || null;
  const narrative  = result.ai_narrative || "";
  const redFlags   = valuation.red_flags || [];

  // ── Actions bar ───────────────────────────────────────────────────────────
  const bar = div("actions-bar card-animate");
  const idGroup = div("actions-group");
  if (result.analysis_id) {
    idGroup.appendChild(span("id-text", `Analysis #${result.analysis_id}`));
  }
  if (result.cache_hit) {
    idGroup.appendChild(el("span", { class: "cache-badge" }, "⚡ Cached"));
  }
  bar.appendChild(idGroup);
  if (result.permalink) {
    const linkGroup = div("actions-group");
    linkGroup.appendChild(el("a", { class: "btn-ghost", href: result.permalink }, "🔗 Permalink"));
    linkGroup.appendChild(el("a", { class: "btn-ghost", href: result.permalink + "/json" }, "{ } JSON"));
    linkGroup.appendChild(el("a", { class: "btn-ghost", href: result.permalink + "/md" }, "📄 Report"));
    bar.appendChild(linkGroup);
  }
  area.appendChild(bar);

  // ── Property Hero Card ───────────────────────────────────────────────────
  area.appendChild(buildPropertyHero(facts, valuation));

  // ── Bento grid ───────────────────────────────────────────────────────────
  const bento = div("bento-grid card-animate");
  const left  = div("bento-left");
  const right = div("bento-right");

  if (narrative)         left.appendChild(buildAIInsight(narrative));
  left.appendChild(buildVerdictCard(valuation, strategy));
  if (redFlags.length)   left.appendChild(buildRedFlags(redFlags));
  if (enrichment)        left.appendChild(buildAreaRisk(enrichment));
  left.appendChild(buildFactCard(facts));
  if (comps.length)      left.appendChild(buildCompsCard(comps));
  if ((facts.key_features || []).length > 0) left.appendChild(buildFeaturesCard(facts.key_features));

  right.appendChild(buildPIPanel(prediction, facts));

  bento.appendChild(left);
  bento.appendChild(right);
  area.appendChild(bento);
}

// ── Property Hero Card ────────────────────────────────────────────────────────

function buildPropertyHero(facts, valuation) {
  const card = el("div", { class: "prop-hero-card card-animate" });

  const top = div("prop-hero-top");
  const info = div("");

  const addr = el("div", { class: "prop-hero-address" });
  addr.textContent = facts.address || "Property Analysis";
  info.appendChild(addr);

  if (facts.price) {
    const price = el("div", { class: "prop-hero-price" });
    price.textContent = fmtMoney(facts.price);
    info.appendChild(price);
  }

  const pills = div("prop-hero-pills", null);
  pills.style.marginTop = "10px";
  if (facts.bedrooms) pills.appendChild(el("span", { class: "prop-pill" }, `${facts.bedrooms} bed`));
  if (facts.bathrooms) pills.appendChild(el("span", { class: "prop-pill" }, `${facts.bathrooms} bath`));
  if (facts.property_type) pills.appendChild(el("span", { class: "prop-pill" }, facts.property_type));
  if (facts.tenure) {
    const leaseCls = (facts.tenure || "").toLowerCase().includes("leasehold") ? "prop-pill amber" : "prop-pill";
    pills.appendChild(el("span", { class: leaseCls }, facts.tenure));
  }
  if (facts.postcode) pills.appendChild(el("span", { class: "prop-pill" }, facts.postcode));
  if (facts.epc_rating) {
    const epc = facts.epc_rating.toUpperCase();
    const epcCls = ["A","B"].includes(epc) ? "prop-pill green" : ["F","G"].includes(epc) ? "prop-pill red" : "prop-pill";
    pills.appendChild(el("span", { class: epcCls }, `EPC ${epc}`));
  }
  info.appendChild(pills);
  top.appendChild(info);

  // Score ring
  const score = num(valuation.score) ?? 0;
  const ringWrap = buildScoreRing(score, 110);
  const verdictEl = el("div", { class: "score-verdict-text" });
  verdictEl.textContent = valuation.label ? valuation.label.split(".")[0] : "";
  ringWrap.appendChild(verdictEl);
  top.appendChild(ringWrap);

  card.appendChild(top);
  return card;
}

// ── AI Insight card ───────────────────────────────────────────────────────────

function buildAIInsight(narrative) {
  const card = div("card");
  card.appendChild(buildCardHeader("AI Analysis",
    el("span", { class: "badge badge-purple" }, "Claude")));

  const prose = div("narrative-prose");
  const segments = narrative.split(/\n\n+/);
  segments.forEach(seg => {
    const trimmed = seg.trim();
    if (!trimmed) return;
    if (trimmed.startsWith("## ") || trimmed.startsWith("### ")) {
      const heading = el("h4");
      heading.textContent = trimmed.replace(/^#{2,3}\s+/, "");
      prose.appendChild(heading);
      return;
    }
    const lines = trimmed.split("\n");
    if (lines.length === 1 && trimmed.startsWith("- ")) {
      const p = el("p");
      p.innerHTML = "• " + inlineMd(trimmed.slice(2));
      prose.appendChild(p);
    } else if (lines.every(l => l.startsWith("- "))) {
      lines.forEach(l => {
        const p = el("p");
        p.innerHTML = "• " + inlineMd(l.slice(2));
        prose.appendChild(p);
      });
    } else {
      const p = el("p");
      p.innerHTML = inlineMd(trimmed);
      prose.appendChild(p);
    }
  });

  card.appendChild(prose);
  return card;
}

function inlineMd(text) {
  return text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

// ── Red Flags card ────────────────────────────────────────────────────────────

function buildRedFlags(flags) {
  const card = div("card");
  const highCount = flags.filter(f => f.severity === "high").length;
  const badge = el("span", {
    class: highCount > 0 ? "badge badge-red" : "badge badge-amber"
  }, `${flags.length} flag${flags.length !== 1 ? "s" : ""}`);
  card.appendChild(buildCardHeader("Risk Flags", badge));

  const list = div("flag-list");
  flags.forEach(flag => {
    const item = div("flag-item");
    const dotCls = { high: "high", medium: "medium", low: "low" }[flag.severity] || "low";
    item.appendChild(el("div", { class: `flag-dot ${dotCls}` }));
    const body = div("flag-body");
    body.appendChild(el("div", { class: "flag-title" }, flag.flag || "Risk factor"));
    if (flag.impact) body.appendChild(el("div", { class: "flag-impact" }, flag.impact));
    item.appendChild(body);
    list.appendChild(item);
  });
  card.appendChild(list);
  return card;
}

// ── Area Risk card ────────────────────────────────────────────────────────────

function buildAreaRisk(enrichment) {
  const card = div("card");
  const adj = enrichment.area_score_adjustment || 0;
  const badgeTxt = adj >= 0 ? `+${adj.toFixed(1)} pts` : `${adj.toFixed(1)} pts`;
  const badgeCl = adj >= 0 ? "badge-green" : adj >= -3 ? "badge-amber" : "badge-red";
  card.appendChild(buildCardHeader("Area Profile",
    el("span", { class: `badge ${badgeCl}` }, badgeTxt)));

  const grid = div("area-grid");

  const crime = enrichment.crime_severity || "unknown";
  const crimeCl = { low: "good", medium: "warn", high: "bad", unknown: "neutral" }[crime] || "neutral";
  const crimeCount = enrichment.crime_count_12m != null ? ` (${enrichment.crime_count_12m} in 6mo)` : "";
  grid.appendChild(buildAreaChip("🚔 Crime", crime.charAt(0).toUpperCase() + crime.slice(1) + crimeCount, crimeCl));

  const flood = enrichment.flood_severity || "negligible";
  const floodCl = { negligible: "good", low: "good", medium: "warn", high: "bad", severe: "bad" }[flood] || "neutral";
  grid.appendChild(buildAreaChip("🌊 Flood Risk", flood.charAt(0).toUpperCase() + flood.slice(1), floodCl));

  if (enrichment.imd_decile != null) {
    const imd = enrichment.imd_decile;
    const imdCl = imd <= 3 ? "bad" : imd <= 6 ? "warn" : "good";
    grid.appendChild(buildAreaChip("📊 Deprivation", `Decile ${imd}/10`, imdCl));
  } else {
    grid.appendChild(buildAreaChip("📊 Deprivation", "No data", "neutral"));
  }

  if (enrichment.median_earnings != null) {
    grid.appendChild(buildAreaChip("💷 Median Earnings", fmtMoney(enrichment.median_earnings) + "/yr", "neutral"));
  }

  const hasMajor = enrichment.planning_major_nearby;
  const planCount = enrichment.planning_apps_count || 0;
  if (planCount > 0 || hasMajor) {
    const planTxt = hasMajor ? "Major nearby" : `${planCount} app${planCount !== 1 ? "s" : ""}`;
    grid.appendChild(buildAreaChip("🏗️ Planning", planTxt, hasMajor ? "warn" : "neutral"));
  }

  if (enrichment.epc_rating) {
    const epc = enrichment.epc_rating.toUpperCase();
    const epcCl = ["A","B"].includes(epc) ? "good" : ["F","G"].includes(epc) ? "bad" : "neutral";
    grid.appendChild(buildAreaChip("⚡ Area EPC", epc, epcCl));
  }

  card.appendChild(grid);

  const areaFlags = enrichment.area_flags || [];
  if (areaFlags.length) {
    const notes = div("area-notes");
    areaFlags.forEach(f => {
      const note = div("area-note");
      note.textContent = f;
      notes.appendChild(note);
    });
    card.appendChild(notes);
  }

  return card;
}

function buildAreaChip(label, value, quality) {
  const chip = el("div", { class: `area-chip ${quality || "neutral"}` });
  chip.appendChild(el("div", { class: "area-chip-label" }, label));
  chip.appendChild(el("div", { class: "area-chip-value" }, value));
  return chip;
}

// ── Fact card ─────────────────────────────────────────────────────────────────

const FACT_ICONS = {
  "Address": "📍", "Asking Price": "💰", "Bedrooms": "🛏️",
  "Bathrooms": "🚿", "Type": "🏠", "Tenure": "📜",
  "Floor Area": "📐", "EPC Rating": "⚡", "Postcode": "🗺️",
};

function buildFactCard(facts) {
  const card = div("card");
  card.appendChild(buildCardHeader("Property Details", buildTypeBadge(facts.property_type)));

  const rows = [
    ["Address",      facts.address || "—"],
    ["Asking Price", fmtMoney(facts.price)],
    ["Bedrooms",     facts.bedrooms  ?? "—"],
    ["Bathrooms",    facts.bathrooms ?? "—"],
    ["Type",         facts.property_type || "—"],
    ["Tenure",       facts.tenure || "—"],
    ["Floor Area",   facts.floor_area_sqm ? `${Math.round(facts.floor_area_sqm)} m²` : "—"],
    ["EPC Rating",   facts.epc_rating || "—"],
    ["Postcode",     facts.postcode || "—"],
  ];

  rows.forEach(([k, v]) => {
    const row = div("fact-row");
    const keyEl = div("fact-key");
    const icon = FACT_ICONS[k];
    if (icon) keyEl.appendChild(span("fact-key-icon", icon));
    keyEl.appendChild(document.createTextNode(k));
    const val = span("fact-val", String(v));
    if (k === "Asking Price") val.style.cssText = "color:var(--text);font-size:15px;";
    row.appendChild(keyEl);
    row.appendChild(val);
    card.appendChild(row);
  });

  return card;
}

function buildTypeBadge(type) {
  const t = (type || "Property").split(" ")[0];
  return el("span", { class: "badge badge-blue" }, t);
}

// ── Deal verdict card ─────────────────────────────────────────────────────────

function buildVerdictCard(valuation, strategy) {
  const card = div("card");
  const score = num(valuation.score) ?? 0;

  card.appendChild(buildCardHeader("Deal Verdict",
    el("span", { class: `badge ${badgeCls(score)}` }, `${score}/100`)));

  const scoreDisplay = div("score-display");
  const scoreNum = el("div", { class: `score-number ${scoreCls(score)}` });
  scoreNum.textContent = score;
  const labelWrap = div("score-label-wrap");
  const verdict = div("score-verdict"); verdict.textContent = valuation.label || "—";
  const compCount = div("score-comp");
  compCount.textContent = valuation.comp_count
    ? `Based on ${valuation.comp_count} comparable sale${valuation.comp_count !== 1 ? "s" : ""}`
    : "No comparables available";
  labelWrap.appendChild(verdict);
  labelWrap.appendChild(compCount);
  scoreDisplay.appendChild(scoreNum);
  scoreDisplay.appendChild(labelWrap);
  card.appendChild(scoreDisplay);

  const statGrid = div("stat-grid");
  [
    ["Fair Value Low",  fmtMoney(valuation.fair_value_low)],
    ["Fair Value Mid",  fmtMoney(valuation.fair_value_mid)],
    ["Fair Value High", fmtMoney(valuation.fair_value_high)],
  ].forEach(([label, value]) => {
    const box = div("stat-box");
    box.appendChild(el("div", { class: "stat-label" }, label));
    const v = el("div", { class: "stat-value" }); v.textContent = value;
    if (label === "Fair Value Mid") v.style.color = "var(--green)";
    box.appendChild(v);
    statGrid.appendChild(box);
  });
  card.appendChild(statGrid);

  const notes = valuation.notes || [];
  if (notes.length) {
    const ul = el("ul", { class: "notes-list" });
    notes.forEach(n => { const li = el("li"); li.textContent = n; ul.appendChild(li); });
    card.appendChild(ul);
  }

  if (strategy.anchor_offer) {
    card.appendChild(el("hr", { style: "border:none;border-top:1px solid var(--border);margin:20px 0 18px" }));
    card.appendChild(buildCardHeader("Offer Strategy", null));
    const grid = div("offer-grid");
    [
      ["Anchor Offer", fmtMoney(strategy.anchor_offer), true],
      ["Range", `${fmtMoney(strategy.offer_range_low)} – ${fmtMoney(strategy.offer_range_high)}`, false],
    ].forEach(([label, value, highlight]) => {
      const box = el("div", { class: `offer-box${highlight ? " highlight" : ""}` });
      box.appendChild(el("div", { class: "ob-label" }, label));
      const v = el("div", { class: "ob-value" }); v.textContent = value;
      box.appendChild(v);
      grid.appendChild(box);
    });
    card.appendChild(grid);
    const tactic = div("tactic-box");
    tactic.innerHTML = `<strong>Tactic:</strong> ${strategy.tactic || "—"} &nbsp;<em style="color:var(--subtle)">(${strategy.asking_discount_pct ?? 0}% below asking)</em>`;
    card.appendChild(tactic);
  }

  return card;
}

// ── Comparables card ──────────────────────────────────────────────────────────

function buildCompsCard(comps) {
  const card = div("card");
  card.appendChild(buildCardHeader("Comparable Sales",
    el("span", { class: "badge badge-ghost" }, `${comps.length} comps`)));
  const head = el("thead");
  head.appendChild(el("tr", null,
    ...["Price","Date","Postcode","Type","Street"].map(h => el("th", null, h))
  ));
  const body = el("tbody");
  comps.slice(0, 12).forEach(c => {
    body.appendChild(el("tr", null,
      el("td", { style: "font-weight:700;" }, fmtMoney(c.price)),
      el("td", { style: "color:var(--muted);" }, c.date || "—"),
      el("td", null, c.postcode || "—"),
      el("td", { style: "color:var(--muted);" }, c.property_type || "—"),
      el("td", { style: "color:var(--subtle);" }, c.street || "—"),
    ));
  });
  card.appendChild(el("div", { style: "overflow-x:auto;" }, el("table", null, head, body)));
  return card;
}

// ── Key features card ─────────────────────────────────────────────────────────

function buildFeaturesCard(features) {
  const card = div("card");
  card.appendChild(buildCardHeader("Key Features", null));
  const grid = el("div", { style: "display:grid;grid-template-columns:1fr 1fr;gap:6px;" });
  features.forEach(f => {
    const item = el("div", { style: "display:flex;gap:8px;align-items:flex-start;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:13px;color:var(--muted);" });
    item.appendChild(el("span", { style: "color:var(--green);flex-shrink:0;font-size:14px;" }, "✓"));
    item.appendChild(el("span", null, f));
    grid.appendChild(item);
  });
  card.appendChild(grid);
  return card;
}

// ── Predictelligence Panel ────────────────────────────────────────────────────

function buildPIPanel(prediction, facts) {
  const panel = div("pi-panel");
  const inner = div("pi-inner");

  const header = div("pi-header");
  header.appendChild(span("pi-logo-text", "⚡ Predictelligence Forecast"));
  header.appendChild(el("span", { class: "badge badge-green" }, "LIVE ML"));
  inner.appendChild(header);

  const body = div("pi-body");

  if (!prediction) {
    body.appendChild(buildPIState("🔮", "Live prediction temporarily unavailable"));
    inner.appendChild(body); panel.appendChild(inner); return panel;
  }
  if (prediction.warming_up || (!prediction.model_ready && !prediction.direction)) {
    body.appendChild(buildPIState("⏳", "Model is calibrating — predictions available shortly"));
    inner.appendChild(body); panel.appendChild(inner); return panel;
  }
  if (prediction.error && !prediction.direction) {
    body.appendChild(buildPIState("🔮", "Live prediction temporarily unavailable"));
    inner.appendChild(body); panel.appendChild(inner); return panel;
  }

  // Section A: 90-Day Price Forecast
  const secA = div("pi-section");
  secA.appendChild(span("pi-section-label", "90-Day Price Forecast"));

  const forecastVal = div("pi-forecast-value");
  forecastVal.textContent = fmtMoney(prediction.predicted_value);
  secA.appendChild(forecastVal);

  const dirRow = div("pi-dir-row");
  const dir = (prediction.direction || "SIDEWAYS").toUpperCase();
  const dirArrow = { UP: "▲", DOWN: "▼", SIDEWAYS: "→" }[dir] || "→";
  const dirClass = { UP: "dir-up", DOWN: "dir-down", SIDEWAYS: "dir-sideways" }[dir] || "dir-sideways";
  const dirEl = div("pi-direction");
  dirEl.appendChild(el("span", { class: dirClass }, `${dirArrow} ${dir}`));
  dirRow.appendChild(dirEl);

  const pct = num(prediction.predicted_change_pct) ?? 0;
  const changeCls = pct > 0 ? "pos" : pct < 0 ? "neg" : "neu";
  dirRow.appendChild(span(`pi-change ${changeCls}`, fmtPct(pct)));
  secA.appendChild(dirRow);

  const conf = num(prediction.confidence) ?? 0;
  secA.appendChild(buildProgressRow("Model Confidence", conf, conf < 80 ? "amber" : ""));
  body.appendChild(secA);

  // Section B: Investment Signal (investor only)
  const userType = (facts && facts.user_type) || "investor";
  const signal = (prediction.investment_signal || "HOLD").toUpperCase();
  const insights = prediction.user_insights || {};

  if (userType === "investor") {
    body.appendChild(el("hr", { class: "pi-divider" }));
    const secB = div("pi-section");
    secB.appendChild(span("pi-section-label", "Investment Signal"));

    const sigClass = { BUY: "sig-buy", HOLD: "sig-hold", SELL: "sig-sell" }[signal] || "sig-hold";
    const sigIcon  = { BUY: "✅", HOLD: "⚠️", SELL: "🔴" }[signal] || "⚠️";
    const badge = div(`pi-signal-badge ${sigClass}`);
    badge.textContent = `${sigIcon} ${signal}`;
    secB.appendChild(badge);

    const comp = num(prediction.composite_score) ?? 0.5;
    const compPct = Math.round(comp * 100);
    const compBarCls = comp >= 0.65 ? "" : comp >= 0.45 ? "amber" : "red";
    secB.appendChild(buildProgressRow("Composite Score", compPct, compBarCls));

    const roi = num(insights.roi_estimate);
    if (roi != null) {
      const roiEl = div("pi-roi");
      roiEl.appendChild(span("pi-roi-key", "Est. 12-month ROI"));
      const roiVal = span("pi-roi-val", fmtPct(roi));
      roiVal.style.color = roi >= 0 ? "var(--green)" : "var(--red)";
      roiEl.appendChild(roiVal);
      secB.appendChild(roiEl);
    }

    if (insights.headline) {
      const ins = div("pi-insight");
      ins.appendChild(el("div", { class: "pi-insight-head" }, insights.headline));
      if (insights.hold_period_suggestion) {
        ins.appendChild(el("div", { class: "pi-insight-body" }, insights.hold_period_suggestion));
      }
      secB.appendChild(ins);
    }
    body.appendChild(secB);
  }

  // Section C: Macro Signals
  body.appendChild(el("hr", { class: "pi-divider" }));
  const secC = div("pi-section");
  secC.appendChild(span("pi-section-label", "Macro Signals"));
  const macro = prediction.macro_signals || {};
  secC.appendChild(buildMacroChips(macro));
  body.appendChild(secC);

  // Section D: Buyer / Mover Insight
  if (userType === "first_time_buyer" || userType === "home_mover") {
    body.appendChild(el("hr", { class: "pi-divider" }));
    const secD = div("pi-section");
    const label = userType === "first_time_buyer" ? "First-Time Buyer Insight" : "Home Mover Insight";
    secD.appendChild(span("pi-section-label", label));
    const ins = div("pi-insight");
    if (insights.headline) ins.appendChild(el("div", { class: "pi-insight-head" }, insights.headline));
    const detail = insights.affordability_outlook || insights.market_timing || "";
    if (detail) ins.appendChild(el("div", { class: "pi-insight-body" }, detail));
    secD.appendChild(ins);
    body.appendChild(secD);
  }

  if (prediction.model_cycles != null) {
    const meta = div("pi-meta");
    const ts = prediction.timestamp ? prediction.timestamp.slice(0, 19).replace("T", " ") : "";
    meta.textContent = `Cycles: ${prediction.model_cycles}  ·  ${ts} UTC`;
    body.appendChild(meta);
  }

  inner.appendChild(body);
  panel.appendChild(inner);
  return panel;
}

// ── Macro chips ───────────────────────────────────────────────────────────────

function buildMacroChips(macro) {
  const row = div("macro-chips");

  const boeDir = (macro.boe_direction || "HOLDING").toUpperCase();
  const boeArrow = boeDir === "RISING" ? "▲" : boeDir === "FALLING" ? "▼" : "→";
  const boeTrCls = boeDir === "RISING" ? "trend-up" : boeDir === "FALLING" ? "trend-down" : "trend-hold";
  row.appendChild(buildChip("BoE Rate", `${(macro.boe_rate||5.25).toFixed(2)}%`, `${boeArrow} ${boeDir}`, boeTrCls));

  const inflTrend = (macro.inflation_trend || "ELEVATED").toUpperCase();
  const inflTrCls = inflTrend === "STABLE" ? "trend-down" : "trend-up";
  row.appendChild(buildChip("Inflation", `${(macro.inflation_rate||3.8).toFixed(1)}%`, inflTrend, inflTrCls));

  row.appendChild(buildChip("Season", macro.season || "—", null, null));

  const afford = (macro.affordability || "PRESSURED").toUpperCase();
  const affordCls = afford === "IMPROVING" ? "trend-down" : "trend-up";
  row.appendChild(buildChip("Affordability", afford, null, affordCls));

  return row;
}

function buildChip(key, value, trend, trendCls) {
  const chip = div("macro-chip");
  chip.appendChild(span("mc-key", key + " "));
  chip.appendChild(span("mc-val", value));
  if (trend) chip.appendChild(el("span", { class: `mc-trend ${trendCls || ""}` }, " " + trend));
  return chip;
}

// ── Progress row ──────────────────────────────────────────────────────────────

function buildProgressRow(label, pct, fillClass) {
  const wrap = el("div", { style: "margin-bottom:14px;" });
  const labelRow = div("progress-label");
  labelRow.appendChild(el("span", null, label));
  labelRow.appendChild(el("span", null, `${Math.round(pct)}%`));
  wrap.appendChild(labelRow);
  const track = div("progress-track");
  const fill = el("div", { class: `progress-fill ${fillClass || ""}`, style: `width:${Math.min(pct,100)}%` });
  track.appendChild(fill);
  wrap.appendChild(track);
  return wrap;
}

// ── Card header helper ────────────────────────────────────────────────────────

function buildCardHeader(title, badge) {
  const h = div("card-header");
  h.appendChild(span("card-title", title));
  if (badge) h.appendChild(badge);
  return h;
}

// ── PI state (skeleton / error / warming) ─────────────────────────────────────

function buildPIState(icon, message) {
  const s = div("skeleton-pulse");
  s.appendChild(el("div", { style: "font-size:24px;margin-bottom:10px;" }, icon));
  s.appendChild(el("div", null, message));
  return s;
}

// ── Multi-step loading controller ─────────────────────────────────────────────

const STEPS = ["step-fetch", "step-comps", "step-area", "step-ai", "step-ml"];
const STEP_DELAYS = [0, 1200, 3500, 6000, 9000]; // ms after submission

let _stepTimer = null;

function startLoadingSteps() {
  const headlineEl = document.getElementById("loading-headline");
  const headlines = [
    "Fetching property listing…",
    "Finding comparable sales…",
    "Profiling area risk data…",
    "Running Claude AI…",
    "Generating ML forecast…",
  ];

  // Reset all steps
  STEPS.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = "loading-step";
    const icon = el.querySelector(".step-icon");
    if (icon) icon.innerHTML = '<span class="step-dot"></span>';
  });

  // Animate steps in sequence
  STEP_DELAYS.forEach((delay, i) => {
    const timer = setTimeout(() => {
      // Mark previous step done
      if (i > 0) {
        const prev = document.getElementById(STEPS[i - 1]);
        if (prev) {
          prev.className = "loading-step done";
          const icon = prev.querySelector(".step-icon");
          if (icon) icon.innerHTML = "✓";
        }
      }
      // Activate current step
      const curr = document.getElementById(STEPS[i]);
      if (curr) {
        curr.className = "loading-step active";
        const icon = curr.querySelector(".step-icon");
        if (icon) icon.innerHTML = '<span class="step-spinner"></span>';
      }
      if (headlineEl && headlines[i]) headlineEl.textContent = headlines[i];
    }, delay);
    // Store timers for cleanup
    if (i === 0) _stepTimer = timer;
  });
}

function stopLoadingSteps() {
  // Mark all as done on completion
  STEPS.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = "loading-step done";
    const icon = el.querySelector(".step-icon");
    if (icon) icon.innerHTML = "✓";
  });
}

// ── Form submission ───────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  const form      = document.getElementById("analyze-form");
  const submitBtn = document.getElementById("submit-btn");
  const errBanner = document.getElementById("error-msg");
  const loadingMsg = document.getElementById("loading-msg");

  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const urlInput   = document.getElementById("url-input");
    const typeSelect = document.getElementById("user-type");
    const url = (urlInput?.value || "").trim();

    if (!url) {
      errBanner.textContent = "Please paste a Rightmove URL.";
      errBanner.style.display = "block";
      return;
    }

    errBanner.style.display = "none";
    document.getElementById("result-area").style.display = "none";
    document.getElementById("result-area").innerHTML = "";
    loadingMsg.style.display = "flex";
    submitBtn.disabled = true;
    submitBtn.textContent = "Analysing…";
    startLoadingSteps();

    try {
      const resp = await fetch("/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, user_type: typeSelect?.value || "investor" }),
      });
      const json = await resp.json();

      if (!json.ok) {
        errBanner.textContent = json.error || "Analysis failed.";
        errBanner.style.display = "block";
      } else {
        stopLoadingSteps();
        // Brief pause so user sees the completed steps
        await new Promise(r => setTimeout(r, 300));
        renderResult(json.result);
        setTimeout(() => {
          document.getElementById("result-area")
            ?.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 80);
      }
    } catch (err) {
      errBanner.textContent = `Network error: ${err.message}`;
      errBanner.style.display = "block";
    } finally {
      loadingMsg.style.display = "none";
      submitBtn.disabled = false;
      submitBtn.textContent = "Analyse →";
    }
  });
});
