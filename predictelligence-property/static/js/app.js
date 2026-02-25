(function () {
  const form = document.getElementById("analysisForm");
  const runPredictionBtn = document.getElementById("runPredictionBtn");
  const checkHealthBtn = document.getElementById("checkHealthBtn");
  const loadHistoryBtn = document.getElementById("loadHistoryBtn");

  const predictionOutput = document.getElementById("predictionOutput");
  const healthOutput = document.getElementById("healthOutput");
  const historyOutput = document.getElementById("historyOutput");
  const dashboardStatus = document.getElementById("dashboardStatus");

  if (!form || !runPredictionBtn || !checkHealthBtn || !loadHistoryBtn) {
    return;
  }

  const getFormData = () => {
    const fd = new FormData(form);
    return {
      postcode: String(fd.get("postcode") || "SW1A1AA").replace(/\s+/g, ""),
      property_type: String(fd.get("property_type") || "semi-detached").toLowerCase(),
      bedrooms: Number(fd.get("bedrooms") || 2),
      current_valuation: Number(fd.get("asking_price") || 285000),
      user_type: String(fd.get("user_type") || "investor"),
    };
  };

  const printJSON = (el, value) => {
    el.textContent = JSON.stringify(value, null, 2);
  };

  const withStatus = async (label, fn) => {
    dashboardStatus.textContent = `${label}...`;
    try {
      await fn();
      dashboardStatus.textContent = `${label} complete.`;
    } catch (err) {
      dashboardStatus.textContent = `${label} failed: ${err.message}`;
    }
  };

  runPredictionBtn.addEventListener("click", async () => {
    await withStatus("Running live prediction", async () => {
      const payload = getFormData();
      const query = new URLSearchParams({
        postcode: payload.postcode,
        property_type: payload.property_type,
        bedrooms: String(payload.bedrooms),
        current_valuation: String(payload.current_valuation),
        user_type: payload.user_type,
      });
      const resp = await fetch(`/api/prediction/predict?${query.toString()}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      printJSON(predictionOutput, json);
    });
  });

  checkHealthBtn.addEventListener("click", async () => {
    await withStatus("Checking model health", async () => {
      const resp = await fetch("/api/prediction/health");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      printJSON(healthOutput, json);
    });
  });

  loadHistoryBtn.addEventListener("click", async () => {
    await withStatus("Loading prediction history", async () => {
      const payload = getFormData();
      const query = new URLSearchParams({
        postcode: payload.postcode,
        limit: "20",
      });
      const resp = await fetch(`/api/prediction/history?${query.toString()}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      printJSON(historyOutput, json);
    });
  });
})();
