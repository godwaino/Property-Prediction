/* Predictelligence Property — Frontend JS */
"use strict";

// ── Utility helpers ──────────────────────────────────────────────────────────

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) {
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
}

function fmtMoney(v) {
  if (v == null || !isFinite(Number(v))) return "—";
  return "£" + Number(v).toLocaleString("en-GB");
}

function fmtPct(v) {
  if (v == null) return "—";
  const n = Number(v);
  return (n >= 0 ? "+" : "") + n.toFixed(1) + "%";
}

function num(v) {
  const n = Number(v);
  return isFinite(n) ? n : null;
}

// ── PropertyScorecard renderer ───────────────────────────────────────────────

function renderScorecard(result) {
  const facts     = result.facts     || {};
  const valuation = result.valuation || {};
  const strategy  = valuation.strategy || {};
  const comps     = result.comps     || [];

  const area = document.getElementById("result-area");
  area.innerHTML = "";
  area.style.display = "block";

  // ── Links bar ──
  if (result.permalink) {
    area.appendChild(
      el("div", { class: "card row" },
        el("span", { class: "muted" }, `Analysis #${result.analysis_id}`),
        el("div", {},
          Object.assign(el("a", { class: "btn", href: result.permalink }), { textContent: "Permalink" }),
          Object.assign(el("a", { class: "btn", href: result.permalink + "/json" }), { textContent: "JSON" }),
          Object.assign(el("a", { class: "btn", href: result.permalink + "/md" }), { textContent: "Markdown" })
        )
      )
    );
  }

  // ── Fact card ──
  const factRows = [
    ["Address", facts.address || "—"],
    ["Asking price", fmtMoney(facts.price)],
    ["Bedrooms", facts.bedrooms ?? "—"],
    ["Bathrooms", facts.bathrooms ?? "—"],
    ["Type", facts.property_type || "—"],
    ["Tenure", facts.tenure || "—"],
    ["Floor area", facts.floor_area_sqm ? `${Math.round(facts.floor_area_sqm)} m²` : "—"],
    ["EPC", facts.epc_rating || "—"],
    ["Postcode", facts.postcode || "—"],
  ];

  const tBody = el("tbody");
  factRows.forEach(([k, v]) => {
    tBody.appendChild(el("tr", {},
      el("th", {}, k),
      el("td", {}, String(v))
    ));
  });

  area.appendChild(
    el("div", { class: "card" },
      el("div", { class: "card-header" },
        el("span", { class: "card-title" }, "Property Facts"),
        el("span", { class: "badge badge-blue" }, facts.property_type || "Property")
      ),
      el("table", {}, tBody)
    )
  );

  // ── Valuation / verdict card ──
  const score = num(valuation.score) ?? 0;
  let scoreCls = score >= 70 ? "badge-green" : score >= 45 ? "badge-amber" : "badge-red";

  const verdictCard = el("div", { class: "card" });
  verdictCard.appendChild(
    el("div", { class: "card-header" },
      el("span", { class: "card-title" }, "Deal Verdict"),
      el("span", { class: `badge ${scoreCls}` }, `${score}/100`)
    )
  );

  // Score label
  verdictCard.appendChild(
    el("p", { class: "muted", style: "margin:0 0 12px" }, valuation.label || "")
  );

  // Valuation row
  const valRow = el("div", { class: "valuation-row" });
  [
    ["Fair Value Low", fmtMoney(valuation.fair_value_low)],
    ["Fair Value Mid", fmtMoney(valuation.fair_value_mid)],
    ["Fair Value High", fmtMoney(valuation.fair_value_high)],
  ].forEach(([label, value]) => {
    const box = el("div", { class: "val-box" });
    box.appendChild(el("div", { class: "label" }, label));
    box.appendChild(el("div", { class: "value" }, value));
    valRow.appendChild(box);
  });
  verdictCard.appendChild(valRow);

  // Notes
  const notes = valuation.notes || [];
  if (notes.length) {
    const ul = el("ul", { style: "margin:12px 0 0; padding-left:18px; font-size:13px; color:var(--muted);" });
    notes.forEach(n => ul.appendChild(el("li", {}, n)));
    verdictCard.appendChild(ul);
  }

  // Offer strategy
  if (strategy.anchor_offer) {
    verdictCard.appendChild(el("hr", { style: "border:none;border-top:1px solid var(--line);margin:14px 0" }));
    verdictCard.appendChild(el("div", { class: "card-title", style: "margin-bottom:8px" }, "Offer Strategy"));

    const sRows = [
      ["Anchor offer", fmtMoney(strategy.anchor_offer)],
      ["Range", `${fmtMoney(strategy.offer_range_low)} – ${fmtMoney(strategy.offer_range_high)}`],
      ["Implied discount", `${strategy.asking_discount_pct ?? 0}% below asking`],
      ["Tactic", strategy.tactic || ""],
    ];
    const sTbody = el("tbody");
    sRows.forEach(([k, v]) => {
      sTbody.appendChild(el("tr", {},
        el("th", {}, k),
        el("td", {}, v)
      ));
    });
    verdictCard.appendChild(el("table", {}, sTbody));
  }

  area.appendChild(verdictCard);

  // ── Predictelligence Panel ──
  renderPredictelligencePanel(area, result.prediction, result.facts);

  // ── Comparables ──
  if (comps.length) {
    const compCard = el("div", { class: "card" });
    compCard.appendChild(el("div", { class: "card-header" },
      el("span", { class: "card-title" }, "Comparable Sales (Land Registry)"),
      el("span", { class: "badge badge-grey" }, `${comps.length} comps`)
    ));

    const cHead = el("thead");
    cHead.appendChild(el("tr", {},
      ...["Price", "Date", "Postcode", "Type", "Street"].map(h => el("th", {}, h))
    ));
    const cBody = el("tbody");
    comps.slice(0, 12).forEach(c => {
      cBody.appendChild(el("tr", {},
        el("td", {}, fmtMoney(c.price)),
        el("td", {}, c.date || "—"),
        el("td", {}, c.postcode || "—"),
        el("td", {}, c.property_type || "—"),
        el("td", {}, c.street || "—"),
      ));
    });
    compCard.appendChild(el("table", {}, cHead, cBody));
    area.appendChild(compCard);
  }

  // ── Features ──
  const features = facts.key_features || [];
  if (features.length) {
    const featCard = el("div", { class: "card" });
    featCard.appendChild(el("div", { class: "card-header" },
      el("span", { class: "card-title" }, "Key Features")
    ));
    const ul = el("ul", { style: "margin:0; padding-left:18px; font-size:13px; line-height:1.8" });
    features.forEach(f => ul.appendChild(el("li", {}, f)));
    featCard.appendChild(ul);
    area.appendChild(featCard);
  }

  // Footer
  area.appendChild(
    el("p", { class: "footer" },
      "Educational content only — not financial advice or a professional valuation."
    )
  );
}

// ── Predictelligence Panel ────────────────────────────────────────────────────

function renderPredictelligencePanel(container, prediction, facts) {
  const panel = el("div", { id: "predictelligence-panel" });

  // Header
  panel.appendChild(
    el("div", { class: "pi-header" },
      el("span", { class: "pi-logo" }, "⚡ Predictelligence Forecast"),
      el("span", { class: "badge badge-green" }, "LIVE ML")
    )
  );

  // Error state
  if (!prediction) {
    panel.appendChild(
      el("div", { class: "pi-body" },
        el("div", { class: "skeleton-card" }, "Live prediction temporarily unavailable")
      )
    );
    container.appendChild(panel);
    return;
  }

  if (prediction.warming_up || (prediction.model_ready === false && !prediction.error)) {
    panel.appendChild(
      el("div", { class: "pi-body" },
        el("div", { class: "skeleton-card" }, "Model is calibrating — predictions available shortly")
      )
    );
    container.appendChild(panel);
    return;
  }

  if (prediction.error && !prediction.direction) {
    panel.appendChild(
      el("div", { class: "pi-body" },
        el("div", { class: "skeleton-card" }, "Live prediction temporarily unavailable")
      )
    );
    container.appendChild(panel);
    return;
  }

  const body = el("div", { class: "pi-body" });

  // ── Section A: 90-Day Price Forecast ──────────────────────────────────────
  body.appendChild(el("div", { class: "card-title", style: "margin-bottom:12px" }, "90-Day Price Forecast"));

  const forecastRow = el("div", { class: "forecast-row" });

  // Predicted value
  const predVal = el("div", { class: "forecast-value" },
    fmtMoney(prediction.predicted_value)
  );
  forecastRow.appendChild(predVal);

  // Direction arrow
  const dir = (prediction.direction || "SIDEWAYS").toUpperCase();
  const dirArrow = dir === "UP" ? "▲" : dir === "DOWN" ? "▼" : "→";
  const dirClass = dir === "UP" ? "direction-up" : dir === "DOWN" ? "direction-down" : "direction-sideways";
  const dirEl = el("div", { class: `forecast-direction ${dirClass}` }, `${dirArrow} ${dir}`);
  forecastRow.appendChild(dirEl);

  // Change pct
  const pct = num(prediction.predicted_change_pct) ?? 0;
  const changeClass = pct > 0 ? "change-pos" : pct < 0 ? "change-neg" : "change-neu";
  forecastRow.appendChild(el("div", { class: `forecast-change ${changeClass}` }, fmtPct(pct)));

  body.appendChild(forecastRow);

  // Confidence bar
  const conf = num(prediction.confidence) ?? 0;
  body.appendChild(
    el("div", { class: "confidence-wrap" },
      el("div", { class: "confidence-label" },
        el("span", {}, "Model Confidence"),
        el("span", {}, `${conf.toFixed(0)}%`)
      ),
      el("div", { class: "progress-wrap" },
        el("div", { class: "progress-fill", style: `width:${conf}%` })
      )
    )
  );

  // ── Section B: Investment Signal (investor only) ───────────────────────────
  const userType = (facts && facts.user_type) || "investor";
  const signal = (prediction.investment_signal || "HOLD").toUpperCase();
  const insights = prediction.user_insights || {};

  if (userType === "investor") {
    body.appendChild(el("hr", { class: "pi-divider" }));
    body.appendChild(el("div", { class: "card-title", style: "margin-bottom:10px" }, "Investment Signal"));

    const sigClass = signal === "BUY" ? "signal-buy" : signal === "SELL" ? "signal-sell" : "signal-hold";
    const sigIcon  = signal === "BUY" ? "✅" : signal === "SELL" ? "🔴" : "⚠️";
    body.appendChild(
      el("div", { class: `signal-badge-large ${sigClass}` }, `${sigIcon} ${signal}`)
    );

    // Composite score bar
    const comp = num(prediction.composite_score) ?? 0.5;
    const compPct = Math.round(comp * 100);
    const barClass = comp >= 0.65 ? "" : comp >= 0.45 ? "amber" : "red";
    body.appendChild(
      el("div", { class: "confidence-wrap", style: "margin-top:8px" },
        el("div", { class: "confidence-label" },
          el("span", {}, "Composite Score"),
          el("span", {}, `${compPct}%`)
        ),
        el("div", { class: "progress-wrap" },
          el("div", { class: `progress-fill ${barClass}`, style: `width:${compPct}%` })
        )
      )
    );

    // ROI estimate
    const roi = num(insights.roi_estimate);
    if (roi != null) {
      body.appendChild(
        el("div", { class: "roi-row", style: "margin-top:10px" },
          "Estimated 12-month ROI: ",
          el("span", { class: "roi-val" }, fmtPct(roi))
        )
      );
    }

    // Insight headline
    if (insights.headline) {
      body.appendChild(
        el("div", { class: "insight-box", style: "margin-top:10px" },
          el("div", { class: "insight-headline" }, insights.headline),
          insights.hold_period_suggestion
            ? el("div", { class: "insight-body" }, insights.hold_period_suggestion)
            : el("span", {})
        )
      );
    }
  }

  // ── Section C: Macro Signals (always shown) ───────────────────────────────
  const macro = prediction.macro_signals || {};
  body.appendChild(el("hr", { class: "pi-divider" }));
  body.appendChild(el("div", { class: "card-title", style: "margin-bottom:10px" }, "Macro Signals"));

  const macroRow = el("div", { class: "macro-row" });

  const boeDir = (macro.boe_direction || "HOLDING").toUpperCase();
  const boeTrend = boeDir === "RISING" ? "▲ RISING" : boeDir === "FALLING" ? "▼ FALLING" : "→ HOLDING";
  const boeTrendClass = boeDir === "RISING" ? "mc-trend-up" : boeDir === "FALLING" ? "mc-trend-down" : "mc-trend-hold";

  macroRow.appendChild(
    el("div", { class: "macro-chip" },
      el("span", { class: "mc-label" }, "BoE Rate"),
      el("span", { class: "mc-value" }, `${(macro.boe_rate || 5.25).toFixed(2)}%`),
      el("span", { class: boeTrendClass }, boeTrend)
    )
  );

  const inflTrend = (macro.inflation_trend || "ELEVATED").toUpperCase();
  macroRow.appendChild(
    el("div", { class: "macro-chip" },
      el("span", { class: "mc-label" }, "Inflation"),
      el("span", { class: "mc-value" }, `${(macro.inflation_rate || 3.8).toFixed(1)}%`),
      el("span", { class: inflTrend === "STABLE" ? "mc-trend-down" : "mc-trend-up" }, inflTrend)
    )
  );

  macroRow.appendChild(
    el("div", { class: "macro-chip" },
      el("span", { class: "mc-label" }, "Season"),
      el("span", { class: "mc-value" }, macro.season || "—")
    )
  );

  const afford = (macro.affordability || "PRESSURED").toUpperCase();
  macroRow.appendChild(
    el("div", { class: "macro-chip" },
      el("span", { class: "mc-label" }, "Affordability"),
      el("span", { class: afford === "IMPROVING" ? "mc-trend-down" : "mc-trend-up" }, afford)
    )
  );

  body.appendChild(macroRow);

  // ── Section D: Buyer/Mover Insight ───────────────────────────────────────
  if (userType === "first_time_buyer" || userType === "home_mover") {
    body.appendChild(el("hr", { class: "pi-divider" }));
    body.appendChild(el("div", { class: "card-title", style: "margin-bottom:10px" },
      userType === "first_time_buyer" ? "First-Time Buyer Insight" : "Home Mover Insight"
    ));

    const insightEl = el("div", { class: "insight-box" });
    if (insights.headline) {
      insightEl.appendChild(el("div", { class: "insight-headline" }, insights.headline));
    }
    const detail = insights.affordability_outlook || insights.market_timing || "";
    if (detail) {
      insightEl.appendChild(el("div", { class: "insight-body" }, detail));
    }
    body.appendChild(insightEl);
  }

  // Cycles badge
  if (prediction.model_cycles != null) {
    body.appendChild(
      el("div", { style: "margin-top:14px; font-size:11px; color:var(--muted); text-align:right" },
        `Model cycles: ${prediction.model_cycles} · Timestamp: ${prediction.timestamp ? prediction.timestamp.slice(0,19).replace("T"," ") : ""} UTC`
      )
    );
  }

  panel.appendChild(body);
  container.appendChild(panel);
}

// ── Form submission ──────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  const form      = document.getElementById("analyze-form");
  const submitBtn = document.getElementById("submit-btn");
  const errDiv    = document.getElementById("error-msg");
  const loading   = document.getElementById("loading-msg");

  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const urlInput  = document.getElementById("url-input");
    const typeSelect = document.getElementById("user-type");
    const url = (urlInput?.value || "").trim();

    if (!url) {
      errDiv.textContent = "Please paste a Rightmove URL.";
      errDiv.style.display = "block";
      return;
    }

    // Reset state
    errDiv.style.display = "none";
    errDiv.textContent = "";
    document.getElementById("result-area").style.display = "none";
    document.getElementById("result-area").innerHTML = "";
    loading.style.display = "block";
    submitBtn.disabled = true;
    submitBtn.textContent = "Analysing…";

    try {
      const payload = {
        url,
        user_type: typeSelect?.value || "investor",
      };

      const resp = await fetch("/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const json = await resp.json();

      if (!json.ok) {
        errDiv.textContent = json.error || "Analysis failed.";
        errDiv.style.display = "block";
      } else {
        renderScorecard(json.result);
      }
    } catch (err) {
      console.error(err);
      errDiv.textContent = `Network error: ${err.message}`;
      errDiv.style.display = "block";
    } finally {
      loading.style.display = "none";
      submitBtn.disabled = false;
      submitBtn.textContent = "Analyse";
    }
  });
});
