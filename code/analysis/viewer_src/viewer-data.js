"use strict";
(function (root) {
  const colours = Object.freeze({
    "Amphibole": "#2a78d6", "Carbonate": "#cc8b25", "Chlorite": "#168a53",
    "Dark-Mica": "#795032", "Epidote": "#8b941e", "K-Feldspar": "#d75b82",
    "Kaolin": "#ce6634", "Other-AlOH": "#a078b7", "Other-MgOH": "#47959d",
    "Plagioclase": "#8a64cf", "Pyroxene": "#355aa8", "Serpentine": "#00785f",
    "Silica": "#d7ae51", "Smectite": "#be4e4e", "Sulphate": "#b49173",
    "Tourmaline": "#755589", "White-Mica": "#d78ba7"
  });

  function colour(name) {
    if (colours[name]) return colours[name];
    let hash = 2166136261;
    for (const ch of name) hash = Math.imul(hash ^ ch.charCodeAt(0), 16777619) >>> 0;
    return `hsl(${hash % 360} 52% 44%)`;
  }

  function sharedColours(data) {
    const names = new Set();
    data.forEach((d) => [d.swir, d.tir].forEach((s) => s.names.forEach((n) => names.add(n))));
    return Object.fromEntries([...names].sort().map((name) => [name, colour(name)]));
  }

  function coveredRanges(d, from, to) {
    const blocks = d.blocks || [{ from_m: d.from, to_m: d.to }];
    const ranges = [];
    blocks.forEach((block) => {
      const cells = d.metres.map((m) => [Math.max(m, from, block.from_m), Math.min(m + 1, to, block.to_m)])
        .filter(([a, b]) => b > a).sort((a, b) => a[0] - b[0]);
      const joined = [];
      cells.forEach(([a, b]) => {
        const last = joined[joined.length - 1];
        if (last && a <= last[1] + 1e-9) last[1] = Math.max(last[1], b);
        else joined.push([a, b]);
      });
      let valid = joined;
      (d.gaps || []).forEach(([g0, g1]) => {
        valid = valid.flatMap(([a, b]) => {
          if (g1 <= a || g0 >= b) return [[a, b]];
          return [[a, Math.min(g0, b)], [Math.max(g1, a), b]].filter(([x, y]) => y > x);
        });
      });
      ranges.push(...valid);
    });
    return ranges.sort((a, b) => a[0] - b[0]);
  }

  function segments(d, from, to, candidates) {
    const out = [];
    coveredRanges(d, from, to).forEach(([a, b]) => {
      const boundaries = candidates.filter((c) => c.depth > a && c.depth < b).sort((p, q) => p.depth - q.depth);
      const edges = [...new Set([a, ...boundaries.map((c) => c.depth), b])];
      for (let k = 0; k < edges.length - 1; k++) {
        const f = edges[k], t = edges[k + 1];
        const rows = d.metres.map((m, i) => [i, Math.max(0, Math.min(m + 1, t) - Math.max(m, f))])
          .filter(([, overlap]) => overlap > 0);
        const width = rows.reduce((sum, [, overlap]) => sum + overlap, 0);
        const mean = (s) => s.names.map((n, j) => [n, rows.reduce((sum, [i, overlap]) => sum + overlap * s.values[i][j], 0) / width])
          .filter(([, v]) => v >= 0.05).sort((p, q) => q[1] - p[1])
          .map(([n, v]) => `${n} ${v.toFixed(2)}`).join("; ");
        out.push({ from: f, to: t, swir: mean(d.swir), tir: mean(d.tir),
          top: candidates.find((c) => Math.abs(c.depth - f) < 1e-9) || null,
          startReason: f === from ? "start of view" : "start of covered block" });
      }
    });
    return out;
  }

  const api = { colour, sharedColours, coveredRanges, segments };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MineralChangeData = api;
})(typeof window !== "undefined" ? window : globalThis);
