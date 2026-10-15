"use strict";
(function () {
  const OTHER = "#d6d4cd", INK = "#0b0b0b", INK2 = "#52514e", GRID = "#e4e2dc", LOG = "#8a8780";
  const MAX_HOLES = 6;
  const embedded = new URLSearchParams(location.search).get("embed") === "1" && window.parent !== window;
  const dataTools = window.MineralChangeData;
  if (embedded) document.body.classList.add("embedded");
  const $ = (id) => document.getElementById(id);
  const index = (window.HOLE_INDEX || []).slice().sort();
  window.HOLE_DATA = window.HOLE_DATA || {};
  const state = { holes: [], from: null, to: null, beta: "2", min: "2", showLog: true };
  let drawn = [], palette = {}, loadSequence = 0;

  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  function fmt(x, d) { return Number(x).toFixed(d); }

  function load(id) {
    if (window.HOLE_DATA[id]) return Promise.resolve(window.HOLE_DATA[id]);
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "data/" + encodeURIComponent(id) + ".js";
      s.onload = () => (window.HOLE_DATA[id] ? resolve(window.HOLE_DATA[id]) : reject(new Error(id)));
      s.onerror = () => reject(new Error(id));
      document.head.appendChild(s);
    });
  }

  function readHash() {
    const hash = location.hash.slice(1);
    if (!hash) return;
    const params = new URLSearchParams(hash.includes("=") ? hash : "holes=" + hash);
    if (params.has("holes")) state.holes = [...new Set((params.get("holes") || "").split(",").filter((x) => index.includes(x)))].slice(0, MAX_HOLES);
    ["from", "to"].forEach((key) => {
      if (params.has(key)) {
        const token = params.get(key), value = Number(token);
        state[key] = token !== "" && Number.isFinite(value) ? value : null;
      }
    });
    if (["1", "2", "4", "8"].includes(params.get("beta"))) state.beta = params.get("beta");
    if (["2", "3", "5"].includes(params.get("min"))) state.min = params.get("min");
    if (params.has("showlog")) state.showLog = params.get("showlog") !== "0";
  }

  function writeHash() {
    const parts = ["holes=" + state.holes.join(",")];
    if (state.from !== null) parts.push("from=" + state.from);
    if (state.to !== null) parts.push("to=" + state.to);
    parts.push("beta=" + state.beta, "min=" + state.min, "showlog=" + (state.showLog ? "1" : "0"));
    history.replaceState(null, "", "#" + parts.join("&"));
  }

  function holeList() {
    const q = $("filter").value.trim().toUpperCase();
    $("holes").innerHTML = index.filter((id) => !q || id.toUpperCase().includes(q)).map((id) => {
      const d = window.HOLE_DATA[id];
      const badge = d && d.validation ? d.validation.result : "";
      return `<label><input type="checkbox" value="${esc(id)}" ${state.holes.includes(id) ? "checked" : ""}> ${esc(id)}<span class="badge">${esc(badge)}</span></label>`;
    }).join("") || '<p class="hint">No hole matches.</p>';
  }

  function candidates(d) { return d.settings[state.beta + "-" + state.min] || []; }
  function nearLog(d, depth) { return (d.log || []).some((x) => Math.abs(x - depth) <= 1.0); }

  function niceStep(span) {
    const steps = [0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500];
    return steps.find((s) => span / s <= 10) || 1000;
  }

  function view() {
    const ds = state.holes.map((h) => window.HOLE_DATA[h]).filter(Boolean);
    const lo = Math.min(...ds.map((d) => d.from)), hi = Math.max(...ds.map((d) => d.to));
    let from = state.from === null ? lo : state.from, to = state.to === null ? hi : state.to;
    if (!(to > from)) { from = lo; to = hi; }
    return [from, to];
  }

  function draw(panel, d, from, to) {
    const canvas = panel.querySelector("canvas");
    const showLog = state.showLog && Array.isArray(d.log);
    const L = { axis: 46, strip: 140, gap: 10 };
    L.x0 = L.axis + 6; L.xs = L.x0; L.xt = L.xs + L.strip + L.gap;
    L.xl = L.xt + L.strip + 8; L.w = L.xl + (showLog ? 24 : 0) + 8;
    const H = embedded ? 480 : Math.max(380, Math.min(1000, window.innerHeight - 300)), top = 24, bottom = 10;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = L.w * dpr; canvas.height = H * dpr;
    canvas.style.width = L.w + "px"; canvas.style.height = H + "px";
    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, L.w, H);
    const y = (z) => top + (z - from) / (to - from) * (H - top - bottom);
    const col = palette;

    g.fillStyle = INK2; g.font = "11px system-ui, sans-serif"; g.textAlign = "center";
    g.fillText("SWIR groups", L.xs + L.strip / 2, 14);
    g.fillText("TIR groups", L.xt + L.strip / 2, 14);
    if (showLog) g.fillText("log", L.xl + 12, 14);

    g.fillStyle = "#f4f3ef";
    [[L.xs, L.strip], [L.xt, L.strip]].forEach(([x, w]) => g.fillRect(x, top, w, H - top - bottom));

    const step = niceStep(to - from);
    g.strokeStyle = GRID; g.lineWidth = 1; g.textAlign = "right"; g.fillStyle = INK2;
    for (let t = Math.ceil(from / step) * step; t <= to + 1e-9; t += step) {
      const yy = Math.round(y(t)) + 0.5;
      g.beginPath(); g.moveTo(L.axis, yy); g.lineTo(L.w - 4, yy); g.stroke();
      g.fillText(String(Math.round(t * 10) / 10), L.axis - 4, yy + 4);
    }

    d.metres.forEach((m, i) => {
      if (m + 1 <= from || m >= to) return;
      const y0 = y(Math.max(m, from)), y1 = y(Math.min(m + 1, to)), h = Math.max(0.6, y1 - y0);
      [[d.swir, L.xs], [d.tir, L.xt]].forEach(([s, x0]) => {
        let x = x0, used = 0;
        Object.keys(col).forEach((n) => {
          const k = s.names.indexOf(n), v = k < 0 ? 0 : s.values[i][k];
          if (v <= 0) return;
          g.fillStyle = col[n]; g.fillRect(x, y0, v * L.strip, h); x += v * L.strip; used += v;
        });
        g.fillStyle = OTHER; g.fillRect(x, y0, Math.max(0, (1 - used) * L.strip), h);
      });
    });

    if (showLog) {
      g.strokeStyle = LOG; g.lineWidth = 1.3;
      d.log.forEach((z) => { if (z >= from && z < to) { const yy = Math.round(y(z)) + 0.5; g.beginPath(); g.moveTo(L.xl, yy); g.lineTo(L.xl + 22, yy); g.stroke(); } });
    }

    const lines = [];
    candidates(d).forEach((c) => {
      if (c.depth < from || c.depth >= to) return;
      const yy = Math.round(y(c.depth)) + 0.5;
      const noReference = state.showLog && !Array.isArray(d.log);
      const solid = !state.showLog || (showLog && nearLog(d, c.depth));
      g.strokeStyle = solid ? INK : INK2; g.lineWidth = solid ? 1.6 : 1.2;
      g.setLineDash(noReference ? [1, 3] : solid ? [] : [4, 3]);
      g.beginPath(); g.moveTo(L.x0 - 4, yy); g.lineTo(L.xl - 2, yy); g.stroke();
      g.setLineDash([]);
      lines.push({ y: yy, c });
    });

    (d.gaps || []).forEach(([a, b]) => {
      if (b <= from || a >= to) return;
      g.fillStyle = "rgba(252,252,251,0.9)";
      [[L.xs, L.strip], [L.xt, L.strip]].forEach(([x, w]) => g.fillRect(x, y(Math.max(a, from)), w, Math.max(1, y(Math.min(b, to)) - y(Math.max(a, from)))));
    });
    drawn.push({ canvas, d, y, from, to, L, lines, col });
  }

  function validationText(d) {
    const v = d.validation;
    if (!v) return "Not included in the reported validation study.";
    if (v.result === "development") return "Used to choose the tested settings (not an independent test).";
    if (v.result === "not scored") return "Tested hole, not scored: the log has no code change inside the scanned depths.";
    const expected = Number(v.random_f1_mean) * (Number(v.candidates) + Number(v.log_changes)) / 2;
    return `Full-hole result at tested default: ${v.matched_1m} of ${v.log_changes} log changes found within 1 m (random lines: about ${fmt(expected, 0)}). ${v.result[0].toUpperCase() + v.result.slice(1)}.`;
  }

  function legendHtml() {
    return Object.keys(palette).map((n) => `<span><i style="background:${palette[n]}"></i>${esc(n)}</span>`).join("") +
      `<span><i style="background:${OTHER}"></i>Other groups / unclassified remainder</span>`;
  }

  function changeLegend(ds) {
    if (!state.showLog) return "<span><b></b>Candidate change</span>";
    const hasReference = ds.some((d) => Array.isArray(d.log));
    const missingReference = ds.some((d) => !Array.isArray(d.log));
    return (hasReference ? '<span><b></b>Candidate, company-log change within 1 m</span><span><b class="dash"></b>Candidate, no log change within 1 m</span><span><b class="log"></b>Company-log code change</span>' : "") +
      (missingReference ? '<span><b class="no-reference"></b>Candidate, company-log reference unavailable</span>' : "");
  }

  function reportHeight() {
    if (!embedded) return;
    requestAnimationFrame(() => window.parent.postMessage({
      type: "hylogger-change-height",
      height: Math.ceil(document.querySelector("main").getBoundingClientRect().height)
    }, location.origin));
  }

  function selectDepth(holeId, depth) {
    if (!embedded || !Number.isFinite(depth)) return;
    window.parent.postMessage({ type: "hylogger-change-select", hole_id: holeId, depth_m: depth }, location.origin);
  }

  async function loadSelected() {
    const sequence = ++loadSequence, requested = state.holes.slice();
    await Promise.all(requested.map((h) => load(h).catch(() => null)));
    if (sequence !== loadSequence) return;
    state.holes = requested.filter((h) => window.HOLE_DATA[h]);
    render();
  }

  function render() {
    writeHash();
    if (embedded) window.parent.postMessage({ type: "hylogger-change-state",
      beta: state.beta, min: state.min, showlog: state.showLog }, location.origin);
    $("beta").value = state.beta; $("min").value = state.min; $("showlog").checked = state.showLog;
    holeList();
    drawn = [];
    const ds = state.holes.map((h) => window.HOLE_DATA[h]).filter(Boolean);
    const isDefault = state.beta === "2" && state.min === "2";
    $("settingsnote").textContent = isDefault
      ? "Tested default: unchanged settings on 40 test holes. Candidates are precomputed for each whole hole; changing the depth window crops the view."
      : "Exploratory settings. Validation numbers below describe the full-hole tested default, not these settings or this depth window.";
    if (!ds.length) {
      $("panels").innerHTML = '<p class="hint">No precomputed hole is selected.</p>';
      $("list").innerHTML = ""; $("legend").innerHTML = ""; $("groups").innerHTML = "";
      $("panelhint").hidden = true;
      reportHeight();
      return;
    }
    const [from, to] = view();
    $("from").value = Math.round(from * 10) / 10; $("to").value = Math.round(to * 10) / 10;
    palette = dataTools.sharedColours(ds);
    $("groups").innerHTML = legendHtml();
    $("panels").innerHTML = ds.map((d) => `<div class="panel" data-hole="${esc(d.hole)}"><h3>${esc(d.hole)}</h3>
      <p class="sub">${esc(validationText(d))}</p>${d.reference_note ? `<p class="sub reference-note">${esc(d.reference_note)}</p>` : ""}${state.showLog && !Array.isArray(d.log) ? '<p class="sub reference-status">Company-log reference unavailable for this hole.</p>' : ""}<canvas></canvas></div>`).join("");
    ds.forEach((d) => draw(document.querySelector(`.panel[data-hole="${CSS.escape(d.hole)}"]`), d, from, to));
    $("panelhint").hidden = $("panels").scrollWidth <= $("panels").clientWidth + 1;
    $("legend").innerHTML = changeLegend(ds);
    const rows = [];
    ds.forEach((d) => candidates(d).forEach((c) => {
      if (c.depth < from || c.depth >= to) return;
      rows.push(`<tr data-hole="${esc(d.hole)}" data-depth="${c.depth}"><td>${esc(d.hole)}</td><td><button type="button" class="depth-link" aria-label="Inspect ${esc(d.hole)} at ${fmt(c.depth, 1)} metres">${fmt(c.depth, 1)}</button></td>
        <td>${c.changes.slice(0, 2).map((x) => `${esc(x.group)} (${x.region}) ${fmt(x.above, 2)} → ${fmt(x.below, 2)}`).join("; ")}</td>
        <td>${c.stability === undefined ? "—" : Math.round(c.stability * 3) + " of 3"}</td>
        <td>${d.log ? (nearLog(d, c.depth) ? "yes" : "no") : "—"}</td></tr>`);
    }));
    $("list").innerHTML = rows.join("") || '<tr><td colspan="5">No candidate in this depth window.</td></tr>';
    reportHeight();
  }

  function hover(ev) {
    const hit = drawn.find((x) => x.canvas === ev.target);
    if (!hit) return;
    const r = ev.target.getBoundingClientRect(), px = ev.clientX - r.left, py = ev.clientY - r.top;
    const line = hit.lines.reduce((best, l) => (Math.abs(l.y - py) < 5 && (!best || Math.abs(l.y - py) < Math.abs(best.y - py)) ? l : best), null);
    let html = "";
    if (line) {
      const c = line.c;
      html = `<strong>${esc(hit.d.hole)} · candidate change at ${fmt(c.depth, 1)} m</strong>` +
        c.changes.map((x) => `${esc(x.group)} (${x.region}): ${fmt(x.above, 2)} → ${fmt(x.below, 2)}`).join("<br>") +
        `<br>Segments: ${fmt(c.above[0], 0)}–${fmt(c.above[1], 0)} m above, ${fmt(c.below[0], 0)}–${fmt(c.below[1], 0)} m below` +
        (c.stability === undefined ? "" : `<br>Kept at ${Math.round(c.stability * 3)} of 3 nearby settings`);
    } else if (px >= hit.L.xs && px <= hit.L.xt + hit.L.strip) {
      const depth = hit.from + (py - 24) / (hit.canvas.clientHeight - 34) * (hit.to - hit.from);
      const i = hit.d.metres.findIndex((m) => depth >= m && depth < m + 1);
      if (i >= 0) {
        const part = (s, reg) => s.names.map((n, k) => [n, s.values[i][k]]).filter(([, v]) => v >= 0.05).map(([n, v]) => `${esc(n)} ${fmt(v, 2)}`).join(", ") || "nothing above 0.05";
        html = `<strong>${esc(hit.d.hole)} · ${hit.d.metres[i]}–${hit.d.metres[i] + 1} m</strong>SWIR: ${part(hit.d.swir)}<br>TIR: ${part(hit.d.tir)}`;
      }
    }
    const tip = $("tip");
    if (!html) { tip.hidden = true; return; }
    tip.innerHTML = html; tip.hidden = false;
    tip.style.left = Math.min(window.innerWidth - 380, ev.clientX + 14) + "px";
    tip.style.top = Math.min(window.innerHeight - 140, ev.clientY + 14) + "px";
  }

  function wheel(ev) {
    if (embedded) return;
    const hit = drawn.find((x) => x.canvas === ev.target);
    if (!hit) return;
    ev.preventDefault();
    const r = ev.target.getBoundingClientRect();
    const at = hit.from + (ev.clientY - r.top - 24) / (hit.canvas.clientHeight - 34) * (hit.to - hit.from);
    const k = ev.deltaY > 0 ? 1.25 : 0.8, span = Math.max(5, (hit.to - hit.from) * k);
    state.from = Math.round((at - (at - hit.from) * span / (hit.to - hit.from)) * 10) / 10;
    state.to = Math.round((state.from + span) * 10) / 10;
    render();
  }

  function segmentsCsv() {
    const [from, to] = view();
    const out = [["hole_id", "from_m", "to_m", "length_m", "main_swir_groups", "main_tir_groups", "change_at_top", "log_change_within_1m_of_top"]];
    state.holes.map((h) => window.HOLE_DATA[h]).filter(Boolean).forEach((d) => {
      dataTools.segments(d, from, to, candidates(d)).forEach(({ from: f, to: t, swir, tir, top, startReason }) => {
        out.push([d.hole, fmt(f, 1), fmt(t, 1), fmt(t - f, 1), swir, tir,
          top ? top.changes.map((x) => `${x.group} (${x.region}) ${fmt(x.above, 2)}->${fmt(x.below, 2)}`).join("; ") : startReason,
          top && d.log ? (nearLog(d, top.depth) ? "yes" : "no") : ""]);
      });
    });
    return out.map((r) => r.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(",")).join("\r\n");
  }

  function bind() {
    $("filter").addEventListener("input", holeList);
    $("holes").addEventListener("change", (ev) => {
      const id = ev.target.value;
      if (ev.target.checked) {
        if (state.holes.length >= MAX_HOLES) { ev.target.checked = false; return; }
        load(id).then(() => { state.holes.push(id); render(); });
      } else { state.holes = state.holes.filter((h) => h !== id); render(); }
    });
    $("from").addEventListener("change", () => { state.from = $("from").value === "" ? null : Number($("from").value); render(); });
    $("to").addEventListener("change", () => { state.to = $("to").value === "" ? null : Number($("to").value); render(); });
    $("fit").addEventListener("click", () => { state.from = null; state.to = null; render(); });
    $("beta").addEventListener("change", () => { state.beta = $("beta").value; render(); });
    $("min").addEventListener("change", () => { state.min = $("min").value; render(); });
    $("showlog").addEventListener("change", () => { state.showLog = $("showlog").checked; render(); });
    $("download").addEventListener("click", () => {
      const blob = new Blob(["﻿" + segmentsCsv()], { type: "text/csv" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "segments_" + state.holes.join("_") + ".csv"; a.click();
    });
    $("panels").addEventListener("mousemove", hover);
    $("panels").addEventListener("mouseleave", () => { $("tip").hidden = true; });
    $("panels").addEventListener("wheel", wheel, { passive: false });
    $("panels").addEventListener("click", (ev) => {
      const hit = drawn.find((x) => x.canvas === ev.target);
      if (!hit) return;
      const py = ev.clientY - hit.canvas.getBoundingClientRect().top;
      const line = hit.lines.reduce((best, l) => Math.abs(l.y - py) < 6 && (!best || Math.abs(l.y - py) < Math.abs(best.y - py)) ? l : best, null);
      if (line) selectDepth(hit.d.hole, line.c.depth);
    });
    $("list").addEventListener("click", (ev) => {
      const tr = ev.target.closest("tr[data-depth]");
      if (!tr) return;
      const z = Number(tr.dataset.depth);
      if (embedded) { selectDepth(tr.dataset.hole, z); return; }
      state.from = Math.round((z - 8) * 10) / 10; state.to = Math.round((z + 8) * 10) / 10; render();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    window.addEventListener("resize", render);
    window.addEventListener("hashchange", () => { readHash(); loadSelected(); });
  }

  readHash();
  if (!state.holes.length && index.length && !location.hash) state.holes = [index[0]];
  $("beta").value = state.beta; $("min").value = state.min;
  bind();
  loadSelected();
})();
