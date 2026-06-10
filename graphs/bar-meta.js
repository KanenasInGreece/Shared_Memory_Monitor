/** Shared header stats — Last updated + samples from /api/summary */
(function () {
  function formatSampleTime(at) {
    if (!at) return "—";
    const d = new Date(at);
    if (!isNaN(d.getTime())) {
      return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" });
    }
    return String(at).replace("T", " ").slice(0, 19);
  }

  function setBarStats({ updated, samples, mode = "ok", error = "", title = "" }) {
    const live = document.getElementById("live-label");
    const updatedEl = document.getElementById("bar-updated-v");
    const samplesEl = document.getElementById("bar-samples-v");
    const status = document.getElementById("bar-status");
    const barUpdated = document.getElementById("bar-updated");
    const barSamples = document.getElementById("bar-samples");
    if (!live) return;

    if (mode === "error") {
      live.classList.add("off");
      live.title = "";
      if (barUpdated) barUpdated.hidden = true;
      if (barSamples) barSamples.hidden = true;
      if (status) { status.hidden = false; status.textContent = error; }
      return;
    }

    if (barUpdated) barUpdated.hidden = false;
    if (barSamples) barSamples.hidden = false;
    if (status) status.hidden = true;
    live.classList.remove("off");
    if (updatedEl) updatedEl.textContent = updated ?? "—";
    if (samplesEl) samplesEl.textContent = samples ?? "—";
    live.title = title || (updated && samples != null
      ? `Last telemetry ${updated} · ${samples} samples stored`
      : "");
  }

  async function loadBarMeta() {
    try {
      const S = await (await fetch("/api/summary")).json();
      setBarStats({
        updated: formatSampleTime(S.last_at),
        samples: S.samples ?? "—",
        mode: S.status === "empty" ? "ok" : "ok",
        title: S.status === "empty" ? "No telemetry samples yet" : "",
      });
    } catch (e) {
      setBarStats({ mode: "error", error: String(e.message || e) });
    }
  }

  window.SmBarMeta = { load: loadBarMeta, set: setBarStats, formatSampleTime };

  /* Dashboard owns bar stats (range-window samples); other pages auto-poll. */
  if (document.body.dataset.barMeta !== "dashboard") {
    loadBarMeta();
    setInterval(loadBarMeta, 30000);
  }
})();