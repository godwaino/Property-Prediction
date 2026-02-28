/* ══════════════════════════════════════════════════════════════════════════════
   Predictelligence Property — Frontend JS (postcode form edition)
   Premium bento-grid results renderer
   ══════════════════════════════════════════════════════════════════════════════ */
"use strict";

// ── Helpers ───────────────────────────────────────────────────────────────────

function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class")    e.className = v;
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
  idGroup.appendChild(span("id-text",
    `${facts.postcode || ""} · ${facts.property_type || ""} · ${facts.bedrooms || "?"} bed`
  ));
  bar.appendChild(idGroup);
  area.appendChild(bar);

  // ── Bento grid ───────────────────────────────────────────────────────────
  const bento = div("bento-grid card-animate");
  const left  = div("bento-left");
  const right = div("bento-right");

  // LEFT: ordered cards
  left.appendChild(buildFactCard(facts));
  if (narrative)         left.appendChild(buildAIInsight(narrative));
  left.appendChild(buildVerdictCard(valuation, strategy));
  if (redFlags.length)   left.appendChild(buildRedFlags(redFlags));
  if (enrichment)        left.appendChild(buildAreaRisk(enrichment));
  if (comps.length)      left.appendChild(buildCompsCard(comps));

  // RIGHT: Predictelligence panel
  right.appendChild(buildPIPanel(prediction, facts));

  bento.appendChild(left);
  bento.appendChild(right);
  area.appendChild(bento);
}

// ── Fact card ─────────────────────────────────────────────────────────────────

function buildFactCard(facts) {
  const card = div("card");
  const typeBadge = el("span", { class: "badge badge-blue" },
    (facts.property_type || "Property").split(" ")[0]);
  card.appendChild(buildCardHeader("Property Details", typeBadge));

  const rows = [
    ["Postcode",      facts.postcode || "—"],
    ["Property Type", facts.property_type || "—"],
    ["Bedrooms",      facts.bedrooms ?? "—"],
    ["Asking Price",  fmtMoney(facts.price)],
    ["Profile",       (facts.user_type || "investor").replace(/_/g, " ")],
  ];

  rows.forEach(([k, v]) => {
    const row = div("fact-row");
    row.appendChild(span("fact-key", k));
    const val = span("fact-val", String(v));
    if (k === "Asking Price") val.style.color = "var(--text)";
    row.appendChild(val);
    card.appendChild(row);
  });

  return card;
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
  const verdict = div("score-verdict");
  verdict.textContent = valuation.label || "—";
  const compCount = div("score-comp");
  compCount.textContent = valuation.comparable_average
    ? `Comparable average: ${fmtMoney(valuation.comparable_average)}`
    : "No comparables available";
  labelWrap.appendChild(verdict);
  labelWrap.appendChild(compCount);
  scoreDisplay.appendChild(scoreNum);
  scoreDisplay.appendChild(labelWrap);
  card.appendChild(scoreDisplay);

  // Valuation stats
  const statGrid = div("stat-grid");
  [
    ["Fair Value Low",  fmtMoney(valuation.fair_value_low)],
    ["Fair Value Mid",  fmtMoney(valuation.fair_value_mid)],
    ["Fair Value High", fmtMoney(valuation.fair_value_high)],
  ].forEach(([label, value]) => {
    const box = div("stat-box");
    box.appendChild(el("div", { class: "stat-label" }, label));
    const v = el("div", { class: "stat-value" }); v.textContent = value;
    box.appendChild(v);
    statGrid.appendChild(box);
  });
  card.appendChild(statGrid);

  // Notes
  const notes = valuation.notes || [];
  if (notes.length) {
    const ul = el("ul", { class: "notes-list" });
    notes.forEach(n => { const li = el("li"); li.textContent = n; ul.appendChild(li); });
    card.appendChild(ul);
  }

  // Offer strategy
  if (strategy && strategy.anchor_offer) {
    card.appendChild(el("hr", { style: "border:none;border-top:1px solid var(--border);margin:18px 0 16px" }));
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

    if (strategy.tactic) {
      const tactic = div("tactic-box");
      tactic.innerHTML = `<strong>Tactic:</strong> ${strategy.tactic} &nbsp;<em style="color:var(--subtle)">(${strategy.asking_discount_pct ?? 0}% below asking)</em>`;
      card.appendChild(tactic);
    }
  }

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
    const dot = el("div", { class: `flag-dot ${dotCls}` });
    const body = div("flag-body");
    body.appendChild(el("div", { class: "flag-title" }, flag.flag || "Risk factor"));
    if (flag.impact) {
      body.appendChild(el("div", { class: "flag-impact" }, flag.impact));
    }
    item.appendChild(dot);
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
  const crimeCount = enrichment.crime_count_12m != null ? ` (${enrichment.crime_count_12m})` : "";
  grid.appendChild(buildAreaChip("Crime", crime.charAt(0).toUpperCase() + crime.slice(1) + crimeCount, crimeCl));

  const flood = enrichment.flood_severity || "negligible";
  const floodCl = { negligible: "good", low: "good", medium: "warn", high: "bad", severe: "bad" }[flood] || "neutral";
  grid.appendChild(buildAreaChip("Flood Risk", flood.charAt(0).toUpperCase() + flood.slice(1), floodCl));

  if (enrichment.imd_decile != null) {
    const imd = enrichment.imd_decile;
    const imdCl = imd <= 3 ? "bad" : imd <= 6 ? "warn" : "good";
    grid.appendChild(buildAreaChip("Deprivation", `Decile ${imd}/10`, imdCl));
  } else {
    grid.appendChild(buildAreaChip("Deprivation", "No data", "neutral"));
  }

  if (enrichment.median_earnings != null) {
    grid.appendChild(buildAreaChip("Median Earnings", fmtMoney(enrichment.median_earnings) + "/yr", "neutral"));
  }

  const hasMajor = enrichment.planning_major_nearby;
  const planCount = enrichment.planning_apps_count || 0;
  if (planCount > 0 || hasMajor) {
    const planTxt = hasMajor ? "Major nearby" : `${planCount} app${planCount !== 1 ? "s" : ""}`;
    grid.appendChild(buildAreaChip("Planning", planTxt, hasMajor ? "warn" : "neutral"));
  }

  if (enrichment.epc_rating) {
    const epc = enrichment.epc_rating.toUpperCase();
    const epcCl = ["A","B"].includes(epc) ? "good" : ["F","G"].includes(epc) ? "bad" : "neutral";
    grid.appendChild(buildAreaChip("Area EPC", epc, epcCl));
  }

  card.appendChild(grid);

  const areaFlags = enrichment.area_flags || [];
  if (areaFlags.length) {
    const notes = div("area-notes");
    areaFlags.forEach(f => {
      const note = div("area-note");
      note.textContent = "· " + f;
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

// ── Comparables card ──────────────────────────────────────────────────────────

function buildCompsCard(comps) {
  const card = div("card");
  card.appendChild(buildCardHeader("Comparable Sales",
    el("span", { class: "badge badge-ghost" }, `${comps.length} comps`)));
  const head = el("thead");
  head.appendChild(el("tr", null,
    ...["Price","Date","Postcode","Type"].map(h => el("th", null, h))
  ));
  const body = el("tbody");
  comps.slice(0, 12).forEach(c => {
    body.appendChild(el("tr", null,
      el("td", null, fmtMoney(c.price)),
      el("td", null, c.date || "—"),
      el("td", null, c.postcode || "—"),
      el("td", null, c.property_type || "—"),
    ));
  });
  card.appendChild(el("table", null, head, body));
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

  // Section A: 90-Day Forecast
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

  // Section B: Investment Signal
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

  // Section D: Buyer/Mover Insight
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
  s.appendChild(el("div", { style: "font-size:22px;margin-bottom:8px;" }, icon));
  s.appendChild(el("div", null, message));
  return s;
}

// ── Form submission ───────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  const form       = document.getElementById("analyze-form");
  const submitBtn  = document.getElementById("submit-btn");
  const errBanner  = document.getElementById("error-msg");
  const loadingMsg = document.getElementById("loading-msg");

  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const postcode    = (document.getElementById("postcode-input")?.value || "").trim().toUpperCase();
    const propType    = document.getElementById("property-type")?.value || "Semi-detached";
    const bedrooms    = parseInt(document.getElementById("bedrooms-input")?.value || "3", 10);
    const askingPrice = parseFloat(document.getElementById("price-input")?.value || "450000");
    const userType    = document.getElementById("user-type")?.value || "investor";

    if (!postcode) {
      errBanner.textContent = "Please enter a postcode.";
      errBanner.style.display = "block";
      return;
    }

    // Reset
    errBanner.style.display = "none";
    document.getElementById("result-area").style.display = "none";
    document.getElementById("result-area").innerHTML = "";
    loadingMsg.style.display = "flex";
    submitBtn.disabled = true;
    submitBtn.textContent = "Analysing…";

    try {
      const resp = await fetch("/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          postcode,
          property_type: propType,
          bedrooms,
          asking_price: askingPrice,
          user_type: userType,
        }),
      });

      const json = await resp.json();

      if (!json.ok) {
        errBanner.textContent = json.error || "Analysis failed.";
        errBanner.style.display = "block";
      } else {
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
      submitBtn.textContent = "Analyse";
    }
  });
});
