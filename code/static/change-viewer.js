"use strict";

(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[char]));
  const format = value => Number(value).toLocaleString("en-US", {maximumFractionDigits:2});

  function create(root, onInspect) {
    const el = id => root.querySelector(`#${id}`);
    const frame = el("change-frame"), section = el("change-content");
    let scope = null, snapshot = null, selected = new Set(), scopeKey = "";
    let timer = null, loading = false, posting = false, failure = "", frameKey = "", choiceKey = "";
    let epoch = 0, refreshPending = false, forcePending = false;
    let frameRevision = 0;
    let settings = {beta:2, min:2, showlog:1};

    const rows = () => new Map((snapshot?.holes || []).map(hole => [hole.hole_id, hole]));
    const ids = () => el("change-mode").value === "current" ? (scope?.selectedHole ? [scope.selectedHole] : []) : [...selected];
    const running = () => ["queued", "running"].includes(snapshot?.job?.status);

    async function request(body) {
      const response = await fetch("/api/change-viewer" + (body ? "/compute" : ""), {
        cache:"no-store", ...(body ? {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)} : {})
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || value.message || "Could not load mineral changes.");
      return value;
    }

    async function refresh(force = false) {
      if (loading) { refreshPending = true; forcePending ||= force; return; }
      const generation = epoch;
      loading = true;
      try {
        const value = await request();
        if (generation === epoch) { snapshot = value; failure = ""; if (force) frameKey = ""; }
      }
      catch (error) { if (generation === epoch) failure = error.message; }
      finally {
        loading = false;
        if (generation === epoch) {
          render(); clearTimeout(timer);
          if (running()) timer = setTimeout(refresh, 1200);
        }
        if (refreshPending) {
          const reload = forcePending; refreshPending = false; forcePending = false;
          refresh(reload);
        }
      }
    }

    function link(holeIds, embed) {
      const hash = new URLSearchParams({holes:holeIds.join(","), from:scope.from, to:scope.to, ...settings});
      return `/change-viewer/index.html${embed ? `?embed=1&revision=${frameRevision}` : ""}#${hash}`;
    }

    function renderChoices() {
      const available = rows(), holes = scope?.holeIds || [];
      const key = JSON.stringify([holes, [...selected], [...available].map(([id, row]) => [id, row.status])]);
      el("change-choices").hidden = el("change-mode").value === "current";
      if (key === choiceKey) return;
      choiceKey = key;
      el("change-holes").innerHTML = holes.map(id => {
        const row = available.get(id), checked = selected.has(id);
        const label = ({ready:"Saved", missing:"Not calculated", stale:"Source changed", running:"Calculating", error:"Retry available", unsupported:"Unavailable"})[row?.status] || "Checking";
        return `<label><input type="checkbox" value="${escape(id)}" ${checked ? "checked" : ""} ${!checked && selected.size >= 6 ? "disabled" : ""}><span>${escape(id)}<small>${escape(label)}</small></span></label>`;
      }).join("");
    }

    function renderFrame(ready) {
      const openLink = el("change-open");
      openLink.hidden = !ready.length;
      if (ready.length) openLink.href = link(ready, false);
      frame.hidden = !ready.length;
      if (!ready.length || !section.open || !scope) return;
      const available = rows();
      const key = JSON.stringify(ready.map(id => {
        const row = available.get(id);
        return [id, row?.source_sha256, row?.computed_from, row?.has_company_log, row?.candidate_count];
      }));
      const reload = key !== frameKey || !frame.getAttribute("src");
      if (reload) frameRevision++;
      const url = link(ready, true);
      if (reload) {
        frameKey = key;
        // Reload the index when completed calculations add a hole to the viewer.
        frame.src = url;
      } else if (frame.contentWindow) {
        const hash = url.slice(url.indexOf("#"));
        try { if (frame.contentWindow.location.hash !== hash) frame.contentWindow.location.replace(url); }
        catch { frame.src = url; }
      }
    }

    function render() {
      renderChoices();
      const available = rows(), chosen = ids();
      const ready = chosen.filter(id => available.get(id)?.status === "ready");
      const pending = chosen.filter(id => available.get(id)?.can_compute);
      el("change-range").textContent = scope ? `${format(scope.from)}–${format(scope.to)} m · follows View depth above` : "Apply a view to choose holes and depths.";
      const summary = !snapshot ? "Checking saved results…" : `${ready.length} of ${chosen.length} selected ${chosen.length === 1 ? "hole" : "holes"} ready`;
      el("change-summary").textContent = summary;
      el("change-compute").hidden = !pending.length;
      el("change-compute").disabled = posting || running() || !pending.length;
      el("change-compute").textContent = `Calculate mineral changes${pending.length > 1 ? ` · ${pending.length} holes` : ""}`;
      el("change-refresh").disabled = loading || posting;
      let message = !chosen.length ? "Choose up to six applied holes to compare." : ready.length === chosen.length ? "Saved results match the current source files. No calculation needed." : "Calculate the holes without current results; saved holes can be viewed now.";
      if (running()) {
        const job = snapshot.job;
        message = `Calculating ${job.completed || 0} / ${job.total || 0} holes${job.current_hole ? ` · ${job.current_hole}` : ""}. You can keep using the profiles above.`;
      }
      if (posting) message = "Starting calculation…";
      if (failure) message = failure;
      el("change-status").textContent = message;
      el("change-status").classList.toggle("change-error", Boolean(failure));
      el("change-progress").hidden = !running();
      if (running()) { el("change-progress").max = snapshot.job.total || 1; el("change-progress").value = snapshot.job.completed || 0; }
      const details = chosen.filter(id => available.get(id)?.status !== "ready").map(id => {
        const row = available.get(id);
        return row?.reason ? `${id}: ${row.reason}` : "";
      }).filter(Boolean);
      el("change-reasons").textContent = details.join(" · ");
      el("change-reasons").hidden = !details.length;
      renderFrame(ready);
    }

    el("change-mode").addEventListener("change", render);
    el("change-holes").addEventListener("change", event => {
      if (event.target.type !== "checkbox") return;
      const id = event.target.value;
      if (event.target.checked && selected.size < 6) selected.add(id); else selected.delete(id);
      render();
    });
    el("change-refresh").addEventListener("click", () => refresh(true));
    section.addEventListener("toggle", () => { if (section.open) { render(); refresh(); } });
    el("change-compute").addEventListener("click", async () => {
      const available = rows(), hole_ids = ids().filter(id => available.get(id)?.can_compute);
      if (!hole_ids.length || posting || running()) return;
      const generation = epoch;
      posting = true; failure = ""; render();
      try { const value = await request({hole_ids}); if (generation === epoch) snapshot = value; }
      catch (error) { if (generation === epoch) failure = error.message; }
      finally { posting = false; render(); clearTimeout(timer); timer = setTimeout(refresh, 800); }
    });
    window.addEventListener("message", event => {
      if (event.origin !== location.origin || event.source !== frame.contentWindow || !scope) return;
      const data = event.data;
      if (data?.type === "hylogger-change-height" && Number.isFinite(data.height)) {
        frame.style.height = `${Math.max(480, Math.min(4200, data.height + 12))}px`;
      } else if (data?.type === "hylogger-change-state") {
        if (![1, 2, 4, 8].includes(Number(data.beta)) || ![2, 3, 5].includes(Number(data.min))) return;
        settings = {beta:Number(data.beta), min:Number(data.min), showlog:data.showlog ? 1 : 0};
        const ready = ids().filter(id => rows().get(id)?.status === "ready");
        if (ready.length) el("change-open").href = link(ready, false);
      } else if (data?.type === "hylogger-change-select" && ids().includes(data.hole_id) &&
          Number.isFinite(data.depth_m) && data.depth_m >= scope.from && data.depth_m < scope.to) {
        onInspect(data.hole_id, data.depth_m);
      }
    });

    return {
      update(next) {
        scope = next;
        const key = JSON.stringify(next?.holeIds || []);
        if (key !== scopeKey) {
          scopeKey = key;
          selected = new Set((next?.holeIds || []).length <= 6 ? next.holeIds : next?.selectedHole ? [next.selectedHole] : []);
          refresh();
        }
        render();
      },
      reset() {
        epoch++; refreshPending = loading; clearTimeout(timer);
        scope = null; scopeKey = ""; snapshot = null; frameKey = "";
        frame.removeAttribute("src"); frame.hidden = true; render();
      }
    };
  }
  window.HyLoggerChangeViewer = {create};
})();
