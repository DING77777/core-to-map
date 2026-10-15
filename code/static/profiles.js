(function () {
  "use strict";

  const pins = new WeakMap();
  const colours = ["#276b7b", "#af3a59", "#8661a6", "#bd692d", "#507c49", "#4168a1", "#996e30"];
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
  const format = (value, digits = 3) => Number(value).toLocaleString("en", { maximumFractionDigits: digits });
  const numeric = (row) => row.status === "valid_numeric" && row.value !== null && Number.isFinite(Number(row.value));

  function colour(id) {
    let hash = 0;
    for (const character of String(id)) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
    return colours[hash % colours.length];
  }

  function domain(metric, rows, query) {
    if (metric.kind === "mineral_group_proportion" || metric.kind === "quality_proportion") return [0, 1];
    const values = rows.filter(numeric).map((row) => Number(row.value));
    if (query.operator === "gte" && query.metric_id === metric.metric_id && query.threshold !== null && Number.isFinite(Number(query.threshold))) values.push(Number(query.threshold));
    if (!values.length) return null;
    const low = Math.min(...values), high = Math.max(...values);
    const padding = Math.max((high - low) * .08, metric.unit === "nm" ? .5 : Math.max(Math.abs(high) * .02, .002));
    return [Math.max(0, low - padding), high + padding];
  }

  function rowAt(rows, depth) {
    let low = 0, high = rows.length - 1;
    while (low <= high) {
      const index = (low + high) >> 1, row = rows[index];
      if (depth < Number(row.from_m)) high = index - 1;
      else if (depth >= Number(row.to_m)) low = index + 1;
      else return row;
    }
    return null;
  }

  function missingLabel(row, metric) {
    if (!row) return "No source record";
    if (row.status === "source_na") return metric.kind === "mineral_group_proportion" ? "N.A. · not detected / below threshold" : "N.A. · no numeric value";
    return row.raw_token ? String(row.raw_token) + " · no numeric value" : "No numeric value";
  }

  function render(container, options) {
    const { profiles = [], holeId, view, query = {}, runs = [], selectedRun, candidates = [], selectedCandidate } = options;
    container.classList.add("hl-profiles");
    if (!view || !(view.to > view.from) || !profiles.length) {
      container.innerHTML = '<p class="hl-profile-empty">Choose an available indicator to see its depth profile.</p>';
      return;
    }
    const tracks = profiles.map((profile) => {
      const rows = (profile.records || []).filter((row) => row.hole_id === holeId && Number(row.to_m) > view.from && Number(row.from_m) < view.to).sort((a, b) => Number(a.from_m) - Number(b.from_m));
      return { metric: profile.metric, rows, colour: colour(profile.metric.metric_id), domain: domain(profile.metric, rows, query) };
    });
    const left = 60, right = candidates.length ? 43 : 16, top = 91, bottom = 471, height = 506;
    const width = Math.max(Math.floor(container.clientWidth || 460), left + right + tracks.length * 190);
    const trackWidth = (width - left - right) / tracks.length;
    const y = (depth) => top + (depth - view.from) / (view.to - view.from) * (bottom - top);
    const visibleRuns = runs.filter((run) => run.hole_id === holeId && Number(run.to_m) > view.from && Number(run.from_m) < view.to);
    const fragments = [`<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" tabindex="0" role="group" aria-label="${escape(holeId)} linked depth profiles. Arrow keys move by one metre. Enter pins a depth, Escape clears it."><title>${escape(holeId)} · One-metre scalar summaries. Blank spaces are not connected.</title>`];
    fragments.push(`<text class="hl-depth-heading" x="${left - 12}" y="${top - 13}" text-anchor="end">Depth m</text>`);
    for (let index = 0; index <= 5; index++) {
      const depth = view.from + (view.to - view.from) * index / 5, py = y(depth);
      fragments.push(`<line class="hl-depth-grid" x1="${left}" x2="${width - right}" y1="${py}" y2="${py}"/><text class="hl-tick" x="${left - 12}" y="${py + 4}" text-anchor="end">${format(depth, 1)}</text>`);
    }
    tracks.forEach((track, index) => {
      const start = left + trackWidth * index, plotLeft = start + 14, plotRight = start + trackWidth - 18;
      const x = (value) => plotLeft + (Number(value) - track.domain[0]) / (track.domain[1] - track.domain[0]) * (plotRight - plotLeft);
      const label = String(track.metric.label || track.metric.metric_id).split(" · ");
      fragments.push(`<rect x="${plotLeft}" y="12" width="20" height="3" rx="1.5" fill="${track.colour}"/><text class="hl-track-title" x="${plotLeft}" y="34">${escape(label[0])}</text><text class="hl-track-unit" x="${plotLeft}" y="51">${escape([label.slice(1).join(" · "), track.metric.unit].filter(Boolean).join(" · "))}</text>`);
      if (index) fragments.push(`<line class="hl-track-divider" x1="${start}" x2="${start}" y1="10" y2="${bottom}"/>`);
      visibleRuns.forEach((run) => fragments.push(`<rect class="hl-run-band${selectedRun === run.run_id ? " selected" : ""}" x="${plotLeft}" y="${y(Math.max(view.from, Number(run.from_m)))}" width="${plotRight - plotLeft}" height="${Math.max(.6, y(Math.min(view.to, Number(run.to_m))) - y(Math.max(view.from, Number(run.from_m))))}" data-run="${escape(run.run_id)}" tabindex="0" role="button" aria-label="Matching interval ${format(run.from_m)} to ${format(run.to_m)} metres"><title>Matching interval · ${format(run.from_m)}–${format(run.to_m)} m</title></rect>`));
      if (track.domain) {
        for (let tick = 0; tick <= 2; tick++) {
          const value = track.domain[0] + (track.domain[1] - track.domain[0]) * tick / 2;
          fragments.push(`<line class="hl-value-grid" x1="${x(value)}" x2="${x(value)}" y1="${top}" y2="${bottom}"/><text class="hl-tick" x="${x(value)}" y="${top - 13}" text-anchor="${tick === 0 ? "start" : tick === 2 ? "end" : "middle"}">${format(value, track.metric.unit === "nm" ? 1 : 3)}</text>`);
        }
        if (query.operator === "gte" && query.metric_id === track.metric.metric_id && query.threshold !== null && Number.isFinite(Number(query.threshold)) && Number(query.threshold) >= track.domain[0] && Number(query.threshold) <= track.domain[1]) {
          fragments.push(`<line class="hl-threshold" x1="${x(query.threshold)}" x2="${x(query.threshold)}" y1="${top}" y2="${bottom}"><title>Filter threshold ≥ ${format(query.threshold)} ${escape(track.metric.unit)}</title></line>`);
        }
        track.rows.filter(numeric).forEach((row) => {
          const px = x(row.value), from = Math.max(view.from, Number(row.from_m)), to = Math.min(view.to, Number(row.to_m));
          const title = `${format(row.from_m)}–${format(row.to_m)} m · ${row.value} ${track.metric.unit}\nSource token: ${row.raw_token}\n${row.source_filename || row.source_id || ""} · CSV data record ${row.data_record_index}`;
          fragments.push(`<line class="hl-value" x1="${px}" x2="${px}" y1="${y(from)}" y2="${y(to)}" stroke="${track.colour}" data-record="${escape(row.record_id)}"><title>${escape(title)}</title></line>`);
        });
      }
      if (!track.rows.some(numeric)) fragments.push(`<text class="hl-no-values" x="${(plotLeft + plotRight) / 2}" y="${(top + bottom) / 2}" text-anchor="middle">No numeric values</text>`);
    });
    if (candidates.length) {
      const cx = width - 23;
      fragments.push(`<text class="hl-candidate-label" x="${cx}" y="${top - 13}" text-anchor="middle">Change</text><line class="candidate-track" x1="${cx}" x2="${cx}" y1="${top}" y2="${bottom}"/>`);
      for (const candidate of candidates.filter((item) => item.depth_m >= view.from && item.depth_m < view.to)) {
        const cy = y(candidate.depth_m);
        fragments.push(`<g class="candidate-marker${selectedCandidate === candidate.id ? " selected" : ""}" data-candidate="${escape(candidate.id)}" tabindex="0" role="button" aria-label="Candidate spectral change at ${format(candidate.depth_m)} metres"><title>Candidate spectral change · ${format(candidate.depth_m)} m</title><rect x="${cx - 12}" y="${cy - 9}" width="24" height="18" fill="transparent"/><path d="M${cx} ${cy - 5}l5 5l-5 5l-5 -5Z"/></g>`);
      }
    }
    fragments.push(`<g class="hl-crosshair" pointer-events="none" visibility="hidden"><line x1="${left}" x2="${width - right}" y1="0" y2="0"/><rect x="2" y="-10" width="48" height="20" rx="4"/><text x="45" y="4" text-anchor="end"></text></g><text class="hl-plot-footnote" x="${left + 14}" y="${height - 12}">Along-hole depth increases downward · each segment is one reported metre</text></svg>`);
    container.innerHTML = `<div class="hl-profile-scroll">${fragments.join("")}</div><div class="hl-profile-readout"><div class="hl-readout-heading"><span>Move across the profiles to compare a depth.</span><button type="button" class="hl-clear-depth" hidden>Clear pin</button></div><div class="hl-readout-values"></div><details class="hl-source-details" hidden><summary>Source records at this depth</summary><div class="hl-source-rows"></div></details></div>`;
    const svg = container.querySelector("svg"), crosshair = container.querySelector(".hl-crosshair");
    const readoutHeading = container.querySelector(".hl-readout-heading span"), values = container.querySelector(".hl-readout-values");
    const clearButton = container.querySelector(".hl-clear-depth"), sourceDetails = container.querySelector(".hl-source-details"), sources = container.querySelector(".hl-source-rows");
    const oldPin = pins.get(container);
    let pinned = oldPin?.holeId === holeId && oldPin.depth >= view.from && oldPin.depth < view.to ? oldPin.depth : null;
    let currentDepth = pinned;

    function showDepth(depth, isPinned = false) {
      currentDepth = depth;
      crosshair.setAttribute("visibility", "visible");
      crosshair.setAttribute("transform", `translate(0 ${y(depth)})`);
      crosshair.querySelector("text").textContent = format(depth, 1);
      crosshair.classList.toggle("pinned", isPinned);
      readoutHeading.textContent = `${isPinned ? "Pinned" : "At"} ${format(depth, 2)} m · ${holeId}`;
      clearButton.hidden = !isPinned;
      values.innerHTML = tracks.map((track) => {
        const row = rowAt(track.rows, depth), value = row && numeric(row) ? `${format(row.value, 4)} ${track.metric.unit}` : missingLabel(row, track.metric);
        return `<div class="hl-readout-item"><i style="background:${track.colour}"></i><div><span>${escape(track.metric.label)}</span><strong>${escape(value)}</strong></div></div>`;
      }).join("");
      sourceDetails.hidden = false;
      sources.innerHTML = tracks.map((track) => {
        const row = rowAt(track.rows, depth);
        const details = row ? `${format(row.from_m)}–${format(row.to_m)} m · raw token ${row.raw_token ?? "—"} · ${row.source_filename || row.source_id || "Source unavailable"} · CSV data record ${row.data_record_index ?? "—"}` : "No source record covers this depth.";
        return `<p><strong>${escape(track.metric.label)}</strong><span>${escape(details)}</span></p>`;
      }).join("");
    }

    function clearPin() {
      pinned = null;
      pins.delete(container);
      clearButton.hidden = true;
      crosshair.setAttribute("visibility", "hidden");
      readoutHeading.textContent = "Move across the profiles to compare a depth.";
      values.innerHTML = "";
      sourceDetails.hidden = true;
    }

    function pointerDepth(event) {
      const bounds = svg.getBoundingClientRect();
      const px = (event.clientX - bounds.left) / bounds.width * width;
      const py = (event.clientY - bounds.top) / bounds.height * height;
      if (px < left || px > width - right || py < top || py >= bottom) return null;
      return view.from + (py - top) / (bottom - top) * (view.to - view.from);
    }

    function pinDepth(depth) {
      pinned = depth;
      pins.set(container, { holeId, depth });
      showDepth(depth, true);
      if (typeof options.onDepthSelect === "function") options.onDepthSelect(depth);
    }

    svg.addEventListener("pointermove", (event) => {
      if (pinned !== null) return;
      const depth = pointerDepth(event);
      if (depth !== null) showDepth(depth);
    });
    svg.addEventListener("pointerleave", () => {
      if (pinned === null) crosshair.setAttribute("visibility", "hidden");
    });
    svg.addEventListener("click", (event) => {
      if (event.target.closest("[data-run], [data-candidate]")) return;
      const depth = pointerDepth(event);
      if (depth !== null) pinDepth(depth);
    });
    svg.addEventListener("keydown", (event) => {
      if (event.target !== svg) return;
      if (event.key === "Escape") { event.preventDefault(); clearPin(); }
      else if (["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const previous = currentDepth ?? view.from + .5;
        const depth = event.key === "Home" ? view.from + .001 : event.key === "End" ? view.to - .001 : Math.max(view.from, Math.min(view.to - .001, previous + (event.key === "ArrowUp" ? -1 : 1)));
        if (pinned !== null) pinDepth(depth); else showDepth(depth);
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault(); pinDepth(currentDepth ?? view.from + Math.min(.5, (view.to - view.from) / 2));
      }
    });
    clearButton.addEventListener("click", clearPin);
    if (pinned !== null) showDepth(pinned, true);
  }

  window.HyLoggerProfiles = {render, pin(container, holeId, depth) { pins.set(container, {holeId, depth}); }};
})();
