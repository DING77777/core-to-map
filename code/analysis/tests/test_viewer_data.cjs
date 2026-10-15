"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const tools = require("../viewer/viewer-data.js");

const sample = {
  from: 0, to: 8, metres: [0, 1, 4, 5, 6, 7], gaps: [[2, 4]],
  blocks: [{ from_m: 0, to_m: 2 }, { from_m: 4, to_m: 8 }],
  swir: { names: ["Chlorite"], values: [[0], [1], [0.5], [0.5], [1], [1]] },
  tir: { names: ["Silica"], values: [[1], [1], [1], [1], [1], [1]] }
};

test("segments split at missing coverage and respect candidate boundaries", () => {
  const segments = tools.segments(sample, 0, 8, [{ depth: 6 }]);
  assert.deepEqual(segments.map((s) => [s.from, s.to]), [[0, 2], [4, 6], [6, 8]]);
  assert.equal(segments[1].startReason, "start of covered block");
  assert.equal(segments[2].top.depth, 6);
});

test("blocks and explicit gaps remain separate even if metre rows span them", () => {
  const d = { ...sample, blocks: [{ from_m: 0, to_m: 6 }, { from_m: 6, to_m: 8 }] };
  assert.deepEqual(tools.coveredRanges(d, 0, 8), [[0, 2], [4, 6], [6, 8]]);
  assert.deepEqual(tools.coveredRanges({ ...sample, gaps: [[4.5, 5.5]] }, 4, 6), [[4, 4.5], [5.5, 6]]);
});

test("a fractional crop weights available metre records and retains numeric zero", () => {
  const result = tools.segments(sample, 0.5, 2, []);
  assert.equal(result.length, 1);
  assert.equal(result[0].swir, "Chlorite 0.67");
  assert.equal(result[0].from, 0.5);
  assert.equal(result[0].to, 2);
});

test("group colours are independent of hole order and the selected cohort", () => {
  const extra = { swir: { names: ["White-Mica", "Chlorite"] }, tir: { names: ["Amphibole"] } };
  const alone = tools.sharedColours([sample]);
  const both = tools.sharedColours([sample, extra]);
  assert.equal(alone.Chlorite, both.Chlorite);
  assert.deepEqual(both, tools.sharedColours([extra, sample]));
  assert.equal(new Set(Object.values(both)).size, Object.keys(both).length);
  assert.equal(tools.colour("Future group"), tools.colour("Future group"));
});

test("all packaged hole exports avoid gaps at every provided setting", () => {
  const dir = path.join(__dirname, "../viewer/data");
  let count = 0;
  for (const name of fs.readdirSync(dir).filter((n) => n.endsWith(".js") && n !== "index.js")) {
    const context = { window: {} };
    vm.runInNewContext(fs.readFileSync(path.join(dir, name), "utf8"), context);
    const d = Object.values(context.window.HOLE_DATA)[0];
    for (const candidates of Object.values(d.settings)) {
      const segments = tools.segments(d, d.from, d.to, candidates);
      for (const s of segments) {
        assert.ok(s.to > s.from, d.hole);
        assert.ok(!(d.gaps || []).some(([a, b]) => s.from < b && s.to > a), d.hole);
        assert.ok((d.blocks || []).some((b) => s.from >= b.from_m && s.to <= b.to_m), d.hole);
      }
    }
    count++;
  }
  assert.equal(count, 42);
});
