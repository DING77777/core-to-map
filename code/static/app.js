"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[character]));
  const format = (value, digits = 2) => Number.isFinite(Number(value)) && value !== null && value !== "" ? Number(value).toLocaleString("en-US", {maximumFractionDigits: digits}) : "—";
  const interval = (run) => `[${format(run.from_m)}, ${format(run.to_m)}) m`;
  const state = {catalog:null, result:null, selectedHole:null, selectedRun:null, records:new Map(), busy:false, requestSequence:0, map:null, mapHole:null, depthView:null, toastTimer:null, basemap:null, basemapError:null, regionalView:null, regionalPreset:"library", localHoleIds:null};
  const regionalPresets = {region:[113.5, -33.5, 126, -24.5], wa:[111, -36, 130, -13]};
  let scalarPicker = null;
  let changeViewer = null;
  const availability = {key:null, sequence:0, timer:null, loading:false, items:[], promise:null, error:""};
  const picker = {selected:new Set(), list:new Set(), group:"", search:"", page:0, pageSize:12};
  const holeNameOrder = new Intl.Collator("en", {numeric:true, sensitivity:"base"});
  const core = {context:"", shown:null};
  let depthRangeKey = null;

  function listedDepthHoles() {
    return (state.catalog?.holes || []).filter(hole => picker.list.has(hole.hole_id))
      .sort((a, b) => holeNameOrder.compare(a.hole_id, b.hole_id));
  }

  function hasDepthRange(item) {
    return item && Number.isFinite(item.depth_from_m) && Number.isFinite(item.depth_to_m) && item.depth_to_m > item.depth_from_m;
  }

  function sourceDepthLabel(holeId) {
    const hole = state.catalog?.holes.find(item => item.hole_id === holeId);
    return hasDepthRange(hole) ? `Source records: ${format(hole.depth_from_m)}–${format(hole.depth_to_m)} m along hole` : "No loaded source depth range";
  }

  function fillDepthRange(from, to) {
    $("depth-from").value = from;
    $("depth-to").value = to;
    showError("form-error", "");
    updateControls();
    toast(`Depth range filled: ${format(from)}–${format(to)} m. Choose Update view to apply.`);
  }

  function renderDepthRanges() {
    const holes = listedDepthHoles(), present = holes.filter(hasDepthRange);
    const selected = scalarPicker?.getSelected() || [];
    const from = present.length ? Math.min(...present.map(hole => hole.depth_from_m)) : null;
    const to = present.length ? Math.max(...present.map(hole => hole.depth_to_m)) : null;
    $("depth-data-summary").textContent = present.length ? `${format(from)}–${format(to)} m · ${holes.length} ${holes.length === 1 ? "hole" : "holes"}` : "No holes with loaded records";
    $("depth-use-full").disabled = !present.length || state.busy;
    const key = JSON.stringify([holes.map(hole => hole.hole_id), selected]);
    if (depthRangeKey !== key) {
      depthRangeKey = key;
      const open = new Set([...$("depth-ranges").querySelectorAll("details[open]")].map(item => item.dataset.hole));
      $("depth-ranges").innerHTML = holes.map(hole => {
        const ranges = state.catalog?.depth_ranges?.[hole.hole_id];
        const values = selected.map(id => {
          const value = ranges?.[id], label = metricDetails(id).label || id;
          const range = value?.numeric_count > 0
            ? `<button type="button" data-depth-from="${value.from_m}" data-depth-to="${value.to_m}" aria-label="Use ${escapeHTML(label)} numeric depth range for ${escapeHTML(hole.hole_id)}: ${format(value.from_m)} to ${format(value.to_m)} metres">${format(value.from_m)}–${format(value.to_m)} m ↗</button><span>${format(value.numeric_count)} / ${format(hole.record_count)} records have values</span>`
            : `<span>${ranges ? "No numeric values in this hole" : "Numeric ranges unavailable"}</span>`;
          return `<div class="depth-indicator"><strong>${escapeHTML(label)}</strong>${range}</div>`;
        }).join("");
        const gaps = hole.extent_span_m - hole.covered_record_length_m;
        const span = hasDepthRange(hole) ? `${format(hole.depth_from_m)}–${format(hole.depth_to_m)} m` : "No source records";
        return `<details class="depth-hole" data-hole="${escapeHTML(hole.hole_id)}"${holes.length === 1 || open.has(hole.hole_id) ? " open" : ""}><summary><strong>${escapeHTML(hole.hole_id)}</strong><span>Source records: ${span}</span></summary><p class="depth-source-note">${format(hole.record_count)} one-metre records${gaps > 0 ? ` · ${format(gaps)} m of missing rows inside this span` : ""}. Indicator ranges below cover the full hole's loaded records.</p>${values || '<p class="depth-source-note">Choose indicators to see where they have values.</p>'}<p class="depth-source-note">Click a numeric range to fill From / To, then Update view. The analysis list stays the same.</p></details>`;
      }).join("");
    }
    const scope = scopeQuery(), missed = scope ? present.filter(hole => hole.depth_to_m <= scope.depth_from_m || hole.depth_from_m >= scope.depth_to_m) : [];
    const noNumbers = scope && selected.length && !availability.loading && !availability.error && availability.items.length && !availability.items.some(item => selected.includes(item.metric_id) && item.enabled);
    let message = !holes.length ? "Add holes to the analysis list to see their depths." : !scope ? "Enter a depth window, or use the full range above." : "Full range uses the shallowest start and deepest end across your list.";
    if (missed.length) message = missed.length === holes.length ? "Your window misses all loaded records. Use the full range above." : `Your window misses the source records in ${missed.length} of ${holes.length} holes.`;
    else if (noNumbers) message = "Your selected indicators have no numbers in this window. Expand a hole to find their depths.";
    $("depth-range-status").textContent = message;
    $("depth-range-status").className = missed.length || noNumbers ? "range-warning" : "";
  }

  function showError(id, message) {
    $(id).textContent = message || "";
    $(id).hidden = !message;
  }

  function metricId() {
    return $("metric").value || state.catalog?.metric?.metric_id || "2200W_AlOH";
  }

  function metrics() {
    return state.catalog?.metrics || Object.values(state.catalog?.metric_registry || {});
  }

  function metricDetails(id = metricId()) {
    return metrics().find((metric) => (metric.metric_id || metric.id) === id) || state.catalog?.metric || {};
  }

  function appliedMetric() {
    return state.result?.metric || metricDetails(state.result?.query.metric_id);
  }

  function unitLabel(metric) {
    if (["dimensionless", "unitless"].includes(metric.unit)) return "unitless";
    return String(metric.unit || "").startsWith("relative") ? "relative proportion" : metric.unit || "";
  }

  function updateMetric(resetThreshold = false) {
    const metric = metricDetails();
    $("metric-description").textContent = metric.definition || metric.source_field || metric.metric_id;
    $("threshold-unit").textContent = unitLabel(metric);
    $("threshold").setAttribute("aria-label", (metric.label || "Scalar") + " greater than or equal to threshold, " + unitLabel(metric));
    if (resetThreshold) $("threshold").value = metric.default_threshold ?? 0;
  }

  function scopeQuery() {
    const hole_ids = [...picker.list].sort();
    const from = $("depth-from").value.trim(), to = $("depth-to").value.trim();
    const depth_from_m = Number(from), depth_to_m = Number(to);
    if (!hole_ids.length || !from || !to || !Number.isInteger(depth_from_m) || !Number.isInteger(depth_to_m) || depth_from_m < 0 || depth_to_m <= depth_from_m) return null;
    return {hole_ids, depth_from_m, depth_to_m};
  }

  function updateFilterOptions() {
    const selected = scalarPicker?.getSelected() || [], previous = $("metric").value;
    const byId = new Map(availability.items.map(item => [item.metric_id, item]));
    $("metric").innerHTML = selected.map(id => {
      const metric = metricDetails(id), item = byId.get(id);
      const disabled = availability.loading || !item?.enabled;
      return `<option value="${escapeHTML(id)}"${disabled ? " disabled" : ""}>${escapeHTML(metric.label || id)}${item && !item.enabled ? " · no values" : ""}</option>`;
    }).join("");
    const next = selected.includes(previous) ? previous : selected.find(id => byId.get(id)?.enabled) || selected[0];
    if (next) $("metric").value = next;
    if (next !== previous) updateMetric(true); else updateMetric();
  }

  function queueAvailability() {
    if (!state.catalog || !scalarPicker) return;
    const scope = scopeQuery(), key = JSON.stringify(scope);
    if (availability.key === key) return;
    clearTimeout(availability.timer);
    availability.key = key; availability.sequence++; availability.items = []; availability.error = "";
    availability.loading = !!scope;
    const message = scope ? "Checking indicators for this depth window…" : "Add holes and enter a valid depth window.";
    scalarPicker.setAvailability([], {loading:true, message});
    $("availability-status").textContent = message;
    updateFilterOptions();
    if (scope) availability.timer = setTimeout(() => refreshAvailability(), 220);
  }

  async function refreshAvailability() {
    clearTimeout(availability.timer);
    const scope = scopeQuery();
    if (!scope) return;
    const sequence = ++availability.sequence;
    availability.key = JSON.stringify(scope); availability.loading = true;
    availability.promise = api("/api/availability", scope);
    try {
      const result = await availability.promise;
      if (sequence !== availability.sequence) return;
      availability.items = result.metrics; availability.loading = false; availability.error = "";
      const enabled = result.metrics.filter(item => item.enabled).length;
      const message = `${enabled} of ${result.metrics.length} indicators have numbers · ${scope.hole_ids.length} holes · [${scope.depth_from_m}, ${scope.depth_to_m}) m`;
      scalarPicker.setAvailability(result.metrics, {loading:false, message});
      $("availability-status").textContent = "Grey options have no numeric values here. Partial coverage stays selectable.";
      updateFilterOptions(); updateControls();
    } catch (error) {
      if (sequence !== availability.sequence) return;
      availability.loading = false; availability.error = error.message;
      scalarPicker.setAvailability([], {loading:true, message:"Availability check failed. Update view to retry."});
      $("availability-status").textContent = "Could not check availability: " + error.message;
    }
  }

  function groups() {
    const available = new Set((state.catalog?.holes || []).map((hole) => hole.hole_id));
    const fallback = [
      {id:"tbdd", label:"TBDD · nearby holes", hole_ids:["TBDD126","TBDD127","TBDD128"], depth_from_m:96, depth_to_m:175},
      {id:"cmdd", label:"CMDD · reference pair", hole_ids:["CMDD001","CMDD002"], depth_from_m:0, depth_to_m:150},
      {id:"other", label:"Other regions", hole_ids:["EHD001","DRDD380","RBDD008"], depth_from_m:0, depth_to_m:1312}
    ];
    return (state.catalog?.groups || fallback).filter((group) => group.hole_ids?.some((id) => available.has(id)));
  }

  function syncGroup(matchSelection = false) {
    if (matchSelection) {
      const chosen = [...picker.list].sort().join("|");
      picker.group = groups().find(item => [...item.hole_ids].sort().join("|") === chosen)?.id || "";
    }
    $("hole-group").value = picker.group;
    const group = groups().find(item => item.id === picker.group);
    $("group-note").textContent = group
      ? `${group.description || group.label || group.id}. Curated browsing group, not an official geological area.`
      : "All library holes, sorted by name. Groups only filter this browser.";
  }

  function filteredHoles() {
    const group = groups().find(item => item.id === picker.group);
    const ids = group ? new Set(group.hole_ids) : null;
    const search = picker.search.trim().toLocaleLowerCase("en");
    return (state.catalog?.holes || []).filter(hole => (!ids || ids.has(hole.hole_id)) && hole.hole_id.toLocaleLowerCase("en").includes(search))
      .sort((a, b) => holeNameOrder.compare(a.hole_id, b.hole_id));
  }

  function updatePickerCount() {
    $("hole-count").textContent = `${picker.selected.size} checked · ${filteredHoles().length} filtered · ${state.catalog?.holes.length || 0} total`;
    $("holes-clear").disabled = !picker.selected.size;
    $("holes-add").disabled = !picker.selected.size;
  }

  function renderAnalysisList() {
    const ids = [...picker.list].sort(holeNameOrder.compare);
    $("analysis-list-count").textContent = `${ids.length} holes`;
    $("analysis-list").innerHTML = ids.map(id => `<li><button class="analysis-locate" type="button" data-locate-hole="${escapeHTML(id)}" aria-label="Locate ${escapeHTML(id)} on the map">${escapeHTML(id)}</button><button type="button" data-remove-analysis-hole="${escapeHTML(id)}" aria-label="Remove ${escapeHTML(id)} from analysis list">×</button></li>`).join("") || '<li class="analysis-list-empty">Add drillholes from the browser above.</li>';
    $("analysis-list-clear").disabled = !ids.length;
    if (state.catalog) { drawMap(); drawRegionalMap(); }
  }

  function renderHolePicker() {
    const filtered = filteredHoles(), pages = Math.max(1, Math.ceil(filtered.length / picker.pageSize));
    picker.page = Math.min(picker.page, pages - 1);
    $("hole-options").innerHTML = filtered.slice(picker.page * picker.pageSize, (picker.page + 1) * picker.pageSize).map(hole => `<label class="hole-choice"><input type="checkbox" name="hole_id" value="${escapeHTML(hole.hole_id)}"${picker.selected.has(hole.hole_id) ? " checked" : ""}><strong>${escapeHTML(hole.hole_id)}</strong></label>`).join("") || '<p class="subtle">No matching hole names in this set.</p>';
    $("holes-page").textContent = `Page ${picker.page + 1} / ${pages}`;
    $("holes-previous").disabled = picker.page === 0;
    $("holes-next").disabled = picker.page >= pages - 1;
    $("holes-select-filtered").disabled = !filtered.length;
    updatePickerCount();
  }

  function chooseGroup() {
    picker.group = $("hole-group").value; picker.page = 0; picker.search = ""; $("hole-search").value = "";
    syncGroup();
    renderHolePicker();
    updateControls();
  }

  function draftQuery() {
    const ids = [...picker.list].sort();
    if (!ids.length) throw new Error("Add at least one drillhole to the analysis list.");
    if (!scopeQuery()) throw new Error("Use whole-metre depths with 0 ≤ from < to.");
    const from = Number($("depth-from").value), to = Number($("depth-to").value);
    const display_metric_ids = scalarPicker?.getSelected() || [];
    if (!display_metric_ids.length) throw new Error("Choose at least one indicator to compare.");
    const filtering = $("filter-enabled").checked;
    const length = !filtering || $("min-length").value.trim() === "" ? null : Number($("min-length").value);
    if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || to <= from) throw new Error("Use whole-metre depths with 0 ≤ from < to.");
    if (length !== null && (!Number.isInteger(length) || length < 1)) throw new Error("Enter a positive whole-metre minimum, or leave it blank.");
    if (filtering && ($("threshold").value.trim() === "" || !Number.isFinite(Number($("threshold").value)))) throw new Error("Enter a numeric threshold for the optional condition.");
    if (filtering && !availability.loading && !availability.items.find(item => item.metric_id === metricId())?.enabled) throw new Error("The condition indicator has no numeric values in this window. Choose another or turn the condition off.");
    return {metric_id:metricId(), display_metric_ids, hole_ids:ids, depth_from_m:from, depth_to_m:to, operator:filtering ? "gte" : "none", threshold:filtering ? Number($("threshold").value) : null, min_run_m:length};
  }

  function signature(query) {
    return JSON.stringify({metric_id:query.metric_id, display_metric_ids:query.display_metric_ids || [query.metric_id], hole_ids:[...(query.hole_ids || [])].sort(), depth_from_m:Number(query.depth_from_m), depth_to_m:Number(query.depth_to_m), operator:query.operator || "gte", threshold:query.threshold == null ? null : Number(query.threshold), min_run_m:query.min_run_m == null ? null : Number(query.min_run_m)});
  }

  function isDirty() {
    if (!state.result) return true;
    try { return signature(draftQuery()) !== signature(state.result.query); } catch { return true; }
  }

  function updateControls() {
    queueAvailability();
    renderDepthRanges();
    const dirty = isDirty();
    $("run-button").disabled = !state.catalog || state.busy;
    $("refresh-library").disabled = state.busy;
    $("restore-button").disabled = !state.catalog || state.busy;
    $("export-button").disabled = !state.result || dirty || state.busy;
    $("export-button").title = dirty ? "Run the edited query before exporting." : "Download the applied query and its evidence.";
    $("run-button").firstElementChild.textContent = state.busy ? "Working…" : "Update view";
    $("query-status").className = "status-pill" + (state.busy ? " busy" : dirty && state.result ? " dirty" : "");
    $("query-status").textContent = state.busy ? "Working" : !state.catalog ? "Loading" : !state.result ? "Ready to query" : dirty ? "Changes not applied" : "Applied";
    $("draft-status").className = "draft-status" + (dirty && state.result ? " dirty" : "");
    $("draft-status").textContent = state.busy ? "Running query…" : !state.result ? "Ready to run." : dirty ? "Edited. Run query to update results." : "Showing the applied query.";
    document.querySelectorAll("[data-min-length]").forEach((button) => button.classList.toggle("active", button.dataset.minLength === $("min-length").value));
    $("filter-fields").disabled = !$("filter-enabled").checked;
    $("results").setAttribute("aria-busy", state.busy ? "true" : "false");
  }

  async function api(path, body, asBlob = false) {
    const response = await fetch(path, body === undefined ? {credentials:"same-origin"} : {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
    if (!response.ok) {
      let message = `Request failed (${response.status}).`;
      try { const detail = await response.json(); message = typeof detail.error === "string" ? detail.error : detail.error?.message || detail.message || message; } catch { /* Keep a clear status if the error body is not JSON. */ }
      throw new Error(message);
    }
    return asBlob ? response.blob() : response.json();
  }

  async function runQuery() {
    if (state.busy) return;
    const sequence = ++state.requestSequence, scope = JSON.stringify(scopeQuery());
    state.busy = true; updateControls();
    showError("form-error", ""); showError("request-error", "");
    try {
      if (availability.loading || availability.error) await refreshAvailability();
      if (scope !== JSON.stringify(scopeQuery()) || availability.loading) throw new Error("Selection changed while checking indicators. Choose Update view again.");
      if (availability.error) throw new Error("Could not check indicator availability. " + availability.error);
      const query = draftQuery();
      const result = await api("/api/query", query);
      if (sequence === state.requestSequence) commitResult(result, false);
    } catch (error) {
      if (sequence === state.requestSequence) showError("form-error", error.message);
    } finally {
      if (sequence === state.requestSequence) { state.busy = false; updateControls(); }
    }
  }

  function applyForm(query) {
    const available = new Set(state.catalog.holes.map(hole => hole.hole_id));
    picker.list = new Set(query.hole_ids.filter(id => available.has(id)));
    picker.selected.clear();
    picker.page = 0; picker.search = ""; $("hole-search").value = "";
    scalarPicker.setSelected(query.display_metric_ids || [query.metric_id]);
    updateFilterOptions();
    $("metric").value = query.metric_id;
    updateMetric();
    $("filter-enabled").checked = query.operator !== "none";
    $("filter-fields").disabled = !$("filter-enabled").checked;
    syncGroup(true); renderHolePicker(); renderAnalysisList();
    $("depth-from").value = query.depth_from_m;
    $("depth-to").value = query.depth_to_m;
    $("threshold").value = query.threshold ?? metricDetails().default_threshold ?? "";
    $("min-length").value = query.min_run_m ?? "";
    availability.key = null;
  }

  function commitResult(result, restored) {
    if (!result || !result.query || !Array.isArray(result.holes) || !Array.isArray(result.runs) || !result.query_id) throw new Error("The server returned an incomplete result.");
    if (restored) applyForm(result.query);
    state.result = result;
    state.records = new Map((result.records || []).map((row) => [String(row.record_id), row]));
    state.selectedRun = null;
    if (result.holes.some(hole => hole.hole_id === state.mapHole)) state.selectedHole = state.mapHole;
    if (!result.holes.some((hole) => hole.hole_id === state.selectedHole)) state.selectedHole = result.holes[0]?.hole_id || null;
    state.mapHole = state.selectedHole;
    state.depthView = {from:Number(result.query.depth_from_m), to:Number(result.query.depth_to_m)};
    const expanded = (result.profiles || []).length > 1;
    document.querySelector(".visual-grid").classList.toggle("profile-expanded", expanded);
    $("depth-expand").setAttribute("aria-pressed", String(expanded));
    $("depth-expand").textContent = expanded ? "Compact profile" : "Expand profile";
    $("view-from").value = state.depthView.from; $("view-to").value = state.depthView.to;
    showError("view-error", ""); showError("transfer-error", "");
    if (!state.map) fitMap(false, result.query.hole_ids);
    const focusedPoint = collarPoints().find(hole => hole.hole_id === state.mapHole);
    if (focusedPoint && !pointInView(focusedPoint)) fitMap(false, [state.mapHole]);
    renderResult();
    const firstRun = result.runs.find((run) => run.hole_id === state.selectedHole);
    if (firstRun) selectRun(firstRun.run_id);
  }

  function holeStatus(hole) {
    if (state.result?.query.operator === "none" && Number(hole.numeric_coverage_m) > 0) return {key:"complete", short:"Values available", full:"Browsing source values; no condition applied", color:"var(--complete)"};
    if (Number(hole.run_count) > 0) return {key:"match", short:"Match found", full:"Match found", color:"var(--match)"};
    if (!(Number(hole.numeric_coverage_m) > 0)) {
      const label = hole.status || "No usable values";
      return {key:"no-data", short:label, full:label + ". Source N.A., unknown missing values and uncovered metres are counted separately.", color:"var(--no-data)"};
    }
    if (Number(hole.numeric_coverage_fraction) >= 1 - 1e-10) return {key:"complete", short:"No match · complete", full:"No match / complete numeric coverage", color:"var(--complete)"};
    return {key:"incomplete", short:"No match · incomplete", full:"No match / incomplete numeric coverage", color:"var(--incomplete)"};
  }

  function renderResult() {
    const result = state.result, query = result.query;
    const browsing = query.operator === "none";
    const totalLength = result.runs.reduce((sum, run) => sum + Number(run.length_m), 0);
    const matchHoles = result.holes.filter((hole) => Number(hole.run_count) > 0).length;
    const indicators = result.profiles?.length || 1;
    const condition = browsing ? "No condition applied" : `${appliedMetric().label || query.metric_id} ≥ ${format(query.threshold, 6)} ${unitLabel(appliedMetric())} · ${query.min_run_m == null ? "no minimum length" : `length ≥ ${format(query.min_run_m)} m`}`;
    $("applied-summary").textContent = `${query.hole_ids.join(" + ")} · [${format(query.depth_from_m)}, ${format(query.depth_to_m)}) m · ${indicators} indicators · ${condition}`;
    const requested = (Number(query.depth_to_m) - Number(query.depth_from_m)) * result.holes.length;
    const covered = result.holes.reduce((sum, hole) => sum + Number(hole.numeric_coverage_m || 0), 0);
    $("stat-coverage").innerHTML = format(requested ? covered / requested * 100 : 0, 1) + "<small>%</small>";
    $("stat-runs").textContent = browsing ? indicators : result.runs.length;
    $("stat-runs").nextElementSibling.textContent = browsing ? "indicators side by side" : "matching intervals";
    $("stat-length").innerHTML = `${format(browsing ? query.depth_to_m - query.depth_from_m : totalLength)}<small> m</small>`;
    $("stat-length").nextElementSibling.textContent = browsing ? "depth window per hole" : "total matched length";
    $("stat-holes").innerHTML = browsing ? String(result.holes.length) : `${matchHoles}<small> / ${result.holes.length}</small>`;
    $("stat-holes").nextElementSibling.textContent = browsing ? "holes selected" : "holes with a match";
    $("stat-coverage").nextElementSibling.textContent = `${appliedMetric().label || query.metric_id} · numeric / window`;
    $("profile-note").textContent = "Each track keeps its own units. Move over the plots to compare one depth; click to pin it. Zoom changes every track together." + (browsing ? "" : " Pink bands mark the chosen condition, not confirmed geological units.");
    document.querySelectorAll(".profile-legend > span").forEach((span, index) => { if (index > 0) span.hidden = browsing; });
    document.querySelectorAll(".map-legend > span").forEach((span, index) => {
      span.hidden = browsing && (index === 0 || index === 2);
      const labels = browsing ? ["", "Values available", "", "No values", "Not in applied result"] : ["Match", "No match, complete", "No match, incomplete", "No values", "Not in applied result"];
      span.lastChild.textContent = labels[index];
    });
    $("holes-tab-count").textContent = result.holes.length; $("runs-tab-count").textContent = result.runs.length;
    $("selected-hole").innerHTML = result.holes.map((hole) => `<option value="${escapeHTML(hole.hole_id)}">${escapeHTML(hole.hole_id)}</option>`).join("");
    $("selected-hole").disabled = !result.holes.length;
    $("selected-hole").value = state.selectedHole || "";
    renderTables(); drawMap(); drawRegionalMap(); drawDepth(); renderEvidence(); renderProvenance(); renderCorePhoto();
  }

  function renderTables() {
    if (!state.result) return;
    const windowLength = Number(state.result.query.depth_to_m) - Number(state.result.query.depth_from_m);
    $("holes-body").innerHTML = state.result.holes.map((hole) => {
      const status = holeStatus(hole), fraction = Math.max(0, Math.min(1, Number(hole.numeric_coverage_fraction) || 0));
      const length = hole.total_length_m ?? hole.matched_length_m ?? state.result.runs.filter((run) => run.hole_id === hole.hole_id).reduce((total, run) => total + Number(run.length_m), 0);
      const coverageNote = `Reported: ${format(hole.row_coverage_m)} m; source N.A.: ${format(hole.source_na_m || 0)} m; gaps inside summary span: ${format(hole.source_gap_m || 0)} m; unknown missing values: ${format(hole.unknown_missing_m || 0)} m; outside summary span: ${format(hole.outside_summary_span_m || 0)} m.`;
      const conflict = hole.summary_depth_conflict ? ` Depth conflict: summary reaches ${format(hole.summary_depth_conflict.summary_to_m)} m; collar total depth is ${format(hole.summary_depth_conflict.collar_max_depth_m)} m.` : "";
      return `<tr class="selectable-row${state.selectedHole === hole.hole_id ? " selected" : ""}" data-hole="${escapeHTML(hole.hole_id)}" tabindex="0" aria-label="Inspect ${escapeHTML(hole.hole_id)}, ${escapeHTML(status.full)}"><td class="hole-name">${escapeHTML(hole.hole_id)}${conflict ? '<span class="interval-note">Depth conflict</span>' : ""}</td><td><span class="table-status ${status.key}" title="${escapeHTML(status.full)}">${status.short}</span></td><td>${state.result.query.operator === "none" ? "—" : format(hole.run_count)}</td><td>${state.result.query.operator === "none" ? "—" : format(length) + " m"}</td><td class="coverage-cell" title="${escapeHTML(coverageNote + conflict)}"><div class="coverage-detail">${format(hole.numeric_coverage_m)} / ${format(windowLength)} m <span>${format(fraction * 100, 1)}%</span></div><div class="coverage-track" aria-hidden="true"><i style="width:${fraction * 100}%"></i></div><details class="coverage-breakdown"><summary>Coverage details</summary><p>${escapeHTML(coverageNote + conflict)}</p></details></td></tr>`;
    }).join("") || '<tr><td colspan="5" class="table-empty">No holes in this query.</td></tr>';
    $("runs-body").innerHTML = state.result.runs.map((run) => `<tr class="selectable-row${state.selectedRun === run.run_id ? " selected" : ""}" data-run="${escapeHTML(run.run_id)}" tabindex="0" aria-label="Inspect ${escapeHTML(run.hole_id)}, ${interval(run)}"><td class="hole-name">${escapeHTML(run.hole_id)}</td><td>${interval(run)}${[run.start_reason, run.end_reason].includes("window_continues") ? '<span class="interval-note">Continues beyond query window</span>' : ""}</td><td>${format(run.length_m)} m</td><td>${(run.record_ids || []).length}</td><td><button class="evidence-button" type="button" data-run="${escapeHTML(run.run_id)}">View source <span aria-hidden="true">↗</span></button></td></tr>`).join("") || `<tr><td colspan="5" class="table-empty">${state.result.query.operator === "none" ? "No condition applied. Browse the profiles above, or enable Highlight a condition." : "No intervals match this query. Check each hole’s numeric coverage above."}</td></tr>`;
  }

  function collarPoints() {
    const summaries = new Map((state.result?.holes || []).map(hole => [hole.hole_id, hole]));
    return (state.catalog?.holes || []).flatMap((source) => {
      if (source.located !== true || source.verified !== true || source.longitude == null || source.latitude == null || source.longitude === "" || source.latitude === "") return [];
      const longitude = Number(source.longitude), latitude = Number(source.latitude);
      if (!Number.isFinite(longitude) || !Number.isFinite(latitude) || Math.abs(longitude) > 180 || Math.abs(latitude) > 90) return [];
      return [{...source, longitude, latitude, summary:summaries.get(source.hole_id)}];
    });
  }

  function pointInView(point) {
    const view = state.map;
    return !!view && point.longitude >= view.cx - view.spanX / 2 && point.longitude <= view.cx + view.spanX / 2 && point.latitude >= view.cy - view.spanY / 2 && point.latitude <= view.cy + view.spanY / 2;
  }

  function mapPointStatus(point) {
    if ($("map-colour-by").value === "result") return point.summary ? holeStatus(point.summary) : {color:"#a9a3a6", full:"Not in applied result"};
    return picker.list.has(point.hole_id) ? {color:"var(--accent)", full:"In analysis list"} : {color:"#728399", full:"Not in analysis list"};
  }

  function renderMapSelection() {
    const points = collarPoints(), visible = points.filter(pointInView).sort((a, b) => holeNameOrder.compare(a.hole_id, b.hole_id));
    const focus = (state.catalog?.holes || []).find(hole => hole.hole_id === state.mapHole);
    const choices = [...visible];
    if (focus && !choices.some(hole => hole.hole_id === focus.hole_id)) choices.push(focus);
    $("map-hole-select").innerHTML = '<option value="">Choose a collar…</option>' + choices.map(hole => `<option value="${escapeHTML(hole.hole_id)}">${escapeHTML(hole.hole_id)}${picker.list.has(hole.hole_id) ? " · in list" : ""}</option>`).join("");
    $("map-hole-select").value = focus?.hole_id || "";
    $("map-hole-select").disabled = !choices.length;
    $("map-toggle-analysis").disabled = !focus;
    $("map-toggle-analysis").textContent = focus && picker.list.has(focus.hole_id) ? "Remove from Analysis List" : "Add to Analysis List";
    const applied = (state.result?.holes || []).find(hole => hole.hole_id === state.mapHole);
    $("map-inspect-current").disabled = !applied;
    $("map-fit-list").disabled = !points.some(point => picker.list.has(point.hole_id));
    const point = points.find(hole => hole.hole_id === state.mapHole);
    const range = hasDepthRange(focus) ? ` · loaded depths ${format(focus.depth_from_m)}–${format(focus.depth_to_m)} m` : "";
    $("map-hole-detail").textContent = focus ? `${focus.hole_id}${point ? ` · ${format(point.longitude, 6)}° E, ${format(Math.abs(point.latitude), 6)}° ${point.latitude < 0 ? "S" : "N"} · GDA2020` : " · no verified collar coordinates"}${range}. ${applied ? "Applied result: " + holeStatus(applied).short + "." : "Not in the applied result yet."}` : "Click a collar to see its source location and add it to your analysis list.";
    const appliedIds = new Set(state.result?.query.hole_ids || []);
    const changed = appliedIds.size !== picker.list.size || [...picker.list].some(id => !appliedIds.has(id));
    $("map-list-status").textContent = `${picker.list.size} holes in Analysis List · ${points.length} located in library. ${changed ? "List changed — Update view to apply." : "List matches the applied result."}`;
    document.querySelector(".map-legend").hidden = $("map-colour-by").value !== "result";
  }

  function focusMapHole(holeId, inspect = true) {
    const source = state.catalog?.holes.find(hole => hole.hole_id === holeId);
    if (!source) return;
    state.mapHole = holeId;
    const point = collarPoints().find(hole => hole.hole_id === holeId);
    if (point && (!pointInView(point) || state.map.spanY > 0.1)) fitMap(false, [holeId]);
    if (inspect && state.result?.holes.some(hole => hole.hole_id === holeId)) selectHole(holeId);
    else drawMap();
    drawRegionalMap(); renderMapSelection();
  }

  function fitMap(redraw = true, holeIds = null) {
    state.localHoleIds = holeIds;
    const points = collarPoints().filter((point) => !holeIds || holeIds.includes(point.hole_id));
    if (!points.length) { state.map = null; if (redraw) drawMap(); return; }
    const xs = points.map((point) => point.longitude), ys = points.map((point) => point.latitude);
    const xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys);
    const spanY = Math.max((ymax - ymin) * 2.15, (xmax - xmin) / 1.7 * 2.15, 0.0012);
    state.map = {cx:(xmin + xmax) / 2, cy:(ymin + ymax) / 2, spanY, spanX:spanY * 1.7};
    if (redraw) drawMap();
  }

  function drawMap() {
    const points = collarPoints().filter(pointInView), view = state.map;
    $("local-count").textContent = points.length ? "· " + points.length + " holes" : "";
    if (!view) {
      $("map-area").innerHTML = '<div class="chart-empty">Choose an area above to inspect library holes.<br>Holes without verified coordinates remain selectable on the left.</div>';
      $("map-area").dataset.imagery = "off";
      $("local-imagery-status").hidden = true;
      $("local-imagery-credit").hidden = true;
      $("location-note").textContent = "Unlocated holes remain queryable. No placeholder coordinates are used.";
      renderMapSelection();
      return;
    }
    const width = 560, height = 245, left = 43, right = 544, top = 18, bottom = 217;
    const xmin = view.cx - view.spanX / 2, xmax = view.cx + view.spanX / 2, ymin = view.cy - view.spanY / 2, ymax = view.cy + view.spanY / 2;
    const x = (longitude) => left + (longitude - xmin) / (xmax - xmin) * (right - left);
    const y = (latitude) => bottom - (latitude - ymin) / (ymax - ymin) * (bottom - top);
    const satellite = window.HyLoggerImagery.view("local", {west:xmin, south:ymin, east:xmax, north:ymax, width:1002, height:398}, drawMap);
    $("map-area").dataset.imagery = satellite.status;
    $("local-imagery-status").hidden = satellite.status === "off";
    $("local-imagery-status").textContent = satellite.status === "ready"
      ? satellite.message + (satellite.crs === "EPSG:7844" ? " · GDA2020. Surface context only." : " · Approximate GDA2020 / WGS84 overlay. Surface context only.")
      : satellite.message + " Source collar coordinates remain available.";
    if (satellite.detail?.samples?.length === 1 && satellite.detail.samples[0].accuracy_m) {
      $("local-imagery-status").textContent += ` Image index positional accuracy: ${satellite.detail.samples[0].accuracy_m} m.`;
    }
    const source = window.HyLoggerImagery.metadata();
    $("local-imagery-credit").hidden = satellite.status === "off";
    $("local-imagery-credit").innerHTML = `<a href="${escapeHTML(source.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(source.attribution)}</a>`;
    renderProvenance();
    const precision = Math.max(3, Math.min(7, Math.ceil(-Math.log10(view.spanY)) + 1));
    const fragments = [`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="GDA2020 collar coordinates; north is up"><title>Source GDA2020 longitude and latitude. All verified library holes; list selection is separate from applied results. No underground trajectories.</title><defs><clipPath id="map-clip"><rect x="${left}" y="${top}" width="${right - left}" height="${bottom - top}"/></clipPath></defs>`];
    fragments.push(`<g clip-path="url(#map-clip)"><rect x="${left}" y="${top}" width="${right - left}" height="${bottom - top}" class="regional-ocean"/>`);
    fragments.push(...geographicPaths((coordinate) => [x(Number(coordinate[0])), y(Number(coordinate[1]))]));
    if (satellite.href) fragments.push(`<image data-satellite="local" href="${escapeHTML(satellite.href)}" x="${left}" y="${top}" width="${right - left}" height="${bottom - top}" preserveAspectRatio="none"/>`);
    fragments.push('</g>');
    for (let index = 0; index <= 4; index++) {
      const longitude = xmin + (xmax - xmin) * index / 4, latitude = ymin + (ymax - ymin) * index / 4;
      fragments.push(`<line class="map-grid" x1="${x(longitude)}" x2="${x(longitude)}" y1="${top}" y2="${bottom}"/><line class="map-grid" x1="${left}" x2="${right}" y1="${y(latitude)}" y2="${y(latitude)}"/><text class="map-axis-text" x="${x(longitude)}" y="236" text-anchor="${index === 0 ? "start" : index === 4 ? "end" : "middle"}">${longitude.toFixed(precision)}°</text><text class="map-axis-text" x="${left + 5}" y="${y(latitude) - 5}">${latitude.toFixed(precision)}°</text>`);
    }
    fragments.push('<g clip-path="url(#map-clip)">');
    points.forEach((point, index) => {
      const status = mapPointStatus(point), px = x(point.longitude), py = y(point.latitude), selected = point.hole_id === state.mapHole;
      const labelRight = px < right - 125;
      const depthLabel = sourceDepthLabel(point.hole_id);
      fragments.push(`<g class="collar-hit" data-hole="${escapeHTML(point.hole_id)}" data-in-list="${picker.list.has(point.hole_id)}" data-in-result="${!!point.summary}" data-focused="${selected}" tabindex="0" role="button" aria-label="Inspect ${escapeHTML(point.hole_id)}. ${escapeHTML(status.full)}. ${escapeHTML(depthLabel)}"><title>${escapeHTML(point.hole_id)} · ${status.full}\n${escapeHTML(depthLabel)}\nGDA2020 longitude ${point.longitude}; latitude ${point.latitude}</title><circle cx="${px}" cy="${py}" r="17" fill="transparent"/><circle class="collar-selection" cx="${px}" cy="${py}" r="12" fill="none" stroke="${selected ? "#246279" : picker.list.has(point.hole_id) ? "var(--accent)" : "transparent"}" stroke-width="1.5"/><circle cx="${px}" cy="${py}" r="6" fill="${status.color}" stroke="#fff" stroke-width="2"/><text class="map-hole-label" x="${px + (labelRight ? 17 : -17)}" y="${py + (index % 2 ? 4 : -10)}" text-anchor="${labelRight ? "start" : "end"}">${escapeHTML(point.hole_id)}</text></g>`);
    });
    fragments.push('</g><path d="M525 27L521 38L525 35L529 38Z" fill="var(--muted)"/><text x="525" y="21" text-anchor="middle" class="map-axis-text">N</text></svg>');
    $("map-area").innerHTML = fragments.join("");
    const unlocated = (state.catalog?.holes.length || 0) - collarPoints().length;
    const labelHole = state.mapHole || state.selectedHole;
    $("location-note").textContent = `${points.length} located holes in this view. ` + (labelHole ? `${labelHole} · ${sourceDepthLabel(labelHole)}. ` : "") + (unlocated ? `${unlocated} library hole(s) have no verified coordinates and remain selectable on the left.` : "Source collar locations · No underground trajectories");
    renderMapSelection();
  }

  function setRegionalPreset(name, redraw = true) {
    let bounds = regionalPresets[name] || regionalPresets.wa;
    const points = name === "library" ? collarPoints() : [];
    if (points.length) {
      const xs = points.map(point => point.longitude), ys = points.map(point => point.latitude);
      const padX = Math.max(0.5, (Math.max(...xs) - Math.min(...xs)) * 0.15), padY = Math.max(0.5, (Math.max(...ys) - Math.min(...ys)) * 0.15);
      bounds = [Math.min(...xs) - padX, Math.min(...ys) - padY, Math.max(...xs) + padX, Math.max(...ys) + padY];
    }
    const [west, south, east, north] = bounds;
    const cy = (south + north) / 2;
    const cosine = Math.cos(cy * Math.PI / 180);
    const spanY = Math.max(north - south, (east - west) * cosine / 1.8);
    state.regionalPreset = name;
    state.regionalView = {cx:(west + east) / 2, cy, spanY, spanX:spanY * 1.8 / cosine};
    for (const preset of ["library", "region", "wa"]) $("regional-" + preset).setAttribute("aria-pressed", String(preset === name));
    if (redraw) drawRegionalMap();
  }

  function basemapLayer(feature) {
    return String(feature.properties?.layer || "").toLowerCase();
  }

  function regionalPath(geometry, project) {
    if (!geometry) return "";
    const line = (coordinates, close = false) => {
      if (!Array.isArray(coordinates) || !coordinates.length) return "";
      const points = coordinates.filter((coordinate) => Array.isArray(coordinate) && Number.isFinite(Number(coordinate[0])) && Number.isFinite(Number(coordinate[1]))).map(project);
      return points.length ? points.map((point, index) => `${index ? "L" : "M"}${point[0].toFixed(2)},${point[1].toFixed(2)}`).join("") + (close ? "Z" : "") : "";
    };
    if (geometry.type === "Polygon") return geometry.coordinates.map((ring) => line(ring, true)).join("");
    if (geometry.type === "MultiPolygon") return geometry.coordinates.map((polygon) => polygon.map((ring) => line(ring, true)).join("")).join("");
    if (geometry.type === "LineString") return line(geometry.coordinates);
    if (geometry.type === "MultiLineString") return geometry.coordinates.map((coordinates) => line(coordinates)).join("");
    if (geometry.type === "GeometryCollection") return (geometry.geometries || []).map((item) => regionalPath(item, project)).join("");
    return "";
  }

  function geographicPaths(project) {
    const fragments = [];
    for (const layer of ["land", "admin", "lakes", "rivers", "roads"]) {
      for (const feature of (state.basemap?.features || []).filter((item) => basemapLayer(item) === layer)) {
        const path = regionalPath(feature.geometry, project);
        if (!path) continue;
        const name = feature.properties?.name || feature.properties?.NAME || "";
        fragments.push(`<path class="geo-${layer}" data-map-layer="${layer}" d="${path}" fill-rule="evenodd"><title>${escapeHTML(name || `Natural Earth ${layer}`)}</title></path>`);
      }
    }
    return fragments;
  }

  function drawRegionalMap() {
    if (!state.basemap && $("basemap-mode").value === "map") {
      if (state.basemapError) {
        $("map-background-status").dataset.state = "fallback";
        $("map-background-status").textContent = "Geographic background unavailable. Local collar view remains available.";
        $("regional-map-area").innerHTML = '<div class="regional-fallback"><strong>Regional background unavailable</strong><p>The offline geographic file could not be loaded. The local collar view, queries and source evidence remain available below.</p></div>';
      }
      return;
    }
    if (!state.regionalView) setRegionalPreset("library", false);
    const view = state.regionalView, width = 600, height = 344, left = 12, right = 588, top = 12, bottom = 332;
    const west = view.cx - view.spanX / 2, east = view.cx + view.spanX / 2, south = view.cy - view.spanY / 2, north = view.cy + view.spanY / 2;
    const satellite = window.HyLoggerImagery.view("regional", {west, south, east, north, width:1152, height:640}, drawRegionalMap);
    $("regional-map-area").dataset.imagery = satellite.status;
    const project = (coordinate) => [left + (Number(coordinate[0]) - west) / view.spanX * (right - left), bottom - (Number(coordinate[1]) - south) / view.spanY * (bottom - top)];
    const fragments = [`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Regional geographic context; approximate drill area only" data-map-background="${satellite.status === "off" ? "natural-earth" : "online"}"><title>Regional context. Nearby drill areas are grouped at this zoom. Use the collar view for unrounded source coordinates.</title><defs><clipPath id="regional-map-clip"><rect x="0" y="0" width="${width}" height="${height}" rx="5"/></clipPath></defs><rect width="${width}" height="${height}" class="regional-ocean"/><g clip-path="url(#regional-map-clip)">`];
    fragments.push(...geographicPaths(project));
    if (satellite.href) fragments.push(`<image data-satellite="regional" href="${escapeHTML(satellite.href)}" x="${left}" y="${top}" width="${right - left}" height="${bottom - top}" preserveAspectRatio="none"/>`);
    const grouped = new Map();
    for (const point of collarPoints()) {
      const longitude = Math.round(point.longitude * 10) / 10;
      const latitude = Math.round(point.latitude * 10) / 10;
      const key = longitude + "," + latitude;
      if (!grouped.has(key)) grouped.set(key, {longitude, latitude, holes:[]});
      grouped.get(key).holes.push(point.hole_id);
    }
    const areas = [...grouped.values()].map((area) => {
      const [x, y] = project([area.longitude, area.latitude]);
      return {...area, x, y, count:area.holes.length};
    });
    let merged = true;
    while (merged) {
      merged = false;
      for (let index = 0; index < areas.length && !merged; index++) {
        const area = areas[index];
        const nearby = areas.findIndex((other, next) => next > index && Math.hypot(other.x - area.x, other.y - area.y) < 30);
        if (nearby < 0) continue;
        const other = areas[nearby], count = area.count + other.count;
        area.x = (area.x * area.count + other.x * other.count) / count;
        area.y = (area.y * area.count + other.y * other.count) / count;
        area.holes.push(...other.holes); area.count = count;
        areas.splice(nearby, 1); merged = true;
      }
    }
    const boxes = areas.map((area) => ({x:area.x - 20, y:area.y - 22, width:130, height:42}));
    const places = (state.basemap?.features || []).filter((feature) => basemapLayer(feature) === "places" && feature.geometry?.type === "Point").sort((a, b) => Number(a.properties?.scalerank ?? 9) - Number(b.properties?.scalerank ?? 9));
    for (const feature of places) {
      const coordinates = feature.geometry.coordinates, longitude = Number(coordinates[0]), latitude = Number(coordinates[1]);
      if (longitude < west || longitude > east || latitude < south || latitude > north) continue;
      const [px, py] = project(coordinates), name = String(feature.properties?.name || feature.properties?.NAME || feature.properties?.nameascii || "");
      if (!name) continue;
      const labelWidth = name.length * 6.4 + 6, anchor = px + labelWidth + 8 > right ? "end" : "start";
      const box = {x:anchor === "end" ? px - labelWidth - 7 : px + 7, y:py - 12, width:labelWidth, height:16};
      const collides = boxes.some((other) => box.x < other.x + other.width && box.x + box.width > other.x && box.y < other.y + other.height && box.y + box.height > other.y);
      fragments.push(`<circle class="geo-place" cx="${px}" cy="${py}" r="2.3"><title>${escapeHTML(name)}</title></circle>`);
      if (!collides) { fragments.push(`<text class="geo-place-label" x="${anchor === "end" ? px - 7 : px + 7}" y="${py + 3}" text-anchor="${anchor}">${escapeHTML(name)}</text>`); boxes.push(box); }
    }
    const areaLabels = [];
    const labelPriority = area => area.holes.includes(state.mapHole) ? 2 : area.holes.some(id => picker.list.has(id)) ? 1 : 0;
    for (const area of [...areas].sort((a, b) => labelPriority(b) - labelPriority(a))) {
      const px = area.x, py = area.y;
      if (px < left || px > right || py < top || py > bottom) continue;
      const side = px > right - 130 ? -1 : 1;
      const prefixes = [...new Set(area.holes.map((id) => id.replace(/[0-9]+$/, "")))];
      const label = area.count === 1 ? area.holes[0] : prefixes.length === 1 ? prefixes[0] + " · " + area.count + " holes" : area.count + " holes";
      const listed = area.holes.filter(id => picker.list.has(id)).length;
      const selection = listed === 0 ? "none" : listed === area.count ? "all" : "partial";
      const labelWidth = label.length * 6.5, labelBox = {x:side > 0 ? px + 23 : px - 23 - labelWidth, y:py - 9, width:labelWidth, height:16};
      const overlaps = box => labelBox.x < box.x + box.width && labelBox.x + labelBox.width > box.x && labelBox.y < box.y + box.height && labelBox.y + labelBox.height > box.y;
      const showLabel = !areaLabels.some(overlaps) && !areas.some(other => other !== area && overlaps({x:other.x - 12, y:other.y - 12, width:24, height:24}));
      if (showLabel) areaLabels.push(labelBox);
      const labelSvg = showLabel ? `<text class="drill-area-label" x="${px + side * 23}" y="${py + 4}" text-anchor="${side > 0 ? "start" : "end"}">${escapeHTML(label)}</text>` : "";
      fragments.push(`<g class="regional-drill-area" data-drill-area="${escapeHTML(area.holes.join(","))}" data-selection="${selection}" data-listed-count="${listed}" data-focused="${area.holes.includes(state.mapHole)}" tabindex="0" role="button" aria-label="Inspect ${escapeHTML(area.holes.join(", "))} in the local view; ${listed} in analysis list"><title>${escapeHTML(area.holes.join(", "))} · ${listed} / ${area.count} in analysis list · nearby areas grouped at this zoom</title><circle cx="${px}" cy="${py}" r="12" fill="transparent"/><circle class="drill-area-halo" cx="${px}" cy="${py}" r="16"/><circle class="drill-area-center" cx="${px}" cy="${py}" r="9"/><text class="drill-area-count" x="${px}" y="${py + 3.5}" text-anchor="middle">${area.count}</text>${labelSvg}</g>`);
    }
    fragments.push('</g><g class="regional-north"><path d="M573 30L568 43L573 39L578 43Z"/><text x="573" y="24" text-anchor="middle">N</text></g></svg>');
    $("regional-map-area").innerHTML = fragments.join("");
    const points = collarPoints();
    $("regional-library-status").textContent = `${points.length} located library holes · ${points.filter(point => picker.list.has(point.hole_id)).length} in Analysis List. Nearby areas are grouped at this zoom. Select a group to inspect its collars below.`;
    $("map-background-status").dataset.state = satellite.status === "off" ? "ready" : satellite.status;
    $("map-background-status").textContent = satellite.status === "off" ? "Natural Earth · 1:10,000,000 · WGS84 · offline" : satellite.message + " · No-data areas: coarse geographic map underneath.";
    const source = window.HyLoggerImagery.metadata();
    $("basemap-attribution").textContent = satellite.status === "off" ? "Made with Natural Earth" : "© Landgate / SLIP · underlying map: Natural Earth";
    $("basemap-attribution").href = satellite.status === "off" ? "https://www.naturalearthdata.com/about/terms-of-use/" : source.source_url;
    $("regional-zoom-in").disabled = view.spanY <= 6.0001;
    $("regional-zoom-in").title = view.spanY <= 6.0001 ? "Regional-scale limit. Use the local collar view for individual holes." : "Zoom regional context in";
    $("regional-zoom-out").disabled = view.spanY >= 36;
  }

  async function loadBasemap() {
    try {
      const background = await api("/basemap.json");
      if (background?.type !== "FeatureCollection" || !Array.isArray(background.features) || !background.features.some((feature) => basemapLayer(feature) === "land" && ["Polygon", "MultiPolygon"].includes(feature.geometry?.type))) throw new Error("Invalid offline geographic background.");
      if (!background.metadata || background.metadata.nominal_scale !== 10000000 || background.metadata.crs !== "EPSG:4326") throw new Error("Unsupported geographic background metadata.");
      if (!background.features.some((feature) => basemapLayer(feature) === "land" && regionalPath(feature.geometry, (coordinate) => [Number(coordinate[0]), Number(coordinate[1])]))) throw new Error("No usable land geometry in the offline geographic background.");
      state.basemap = background; state.basemapError = null; if (!state.regionalView) setRegionalPreset("library", false); drawRegionalMap(); drawMap(); renderProvenance();
    } catch (error) {
      state.basemap = null; state.basemapError = error.message; drawRegionalMap();
      if ($("basemap-mode").value === "map") { $("regional-zoom-in").disabled = true; $("regional-zoom-out").disabled = true; }
    }
  }

  function drawDepth() {
    if (!state.result || !state.selectedHole || !state.depthView) return;
    window.HyLoggerProfiles.render($("depth-area"), {
      profiles:state.result.profiles || [{metric:appliedMetric(), records:state.result.records || []}],
      holeId:state.selectedHole, view:state.depthView, query:state.result.query,
      runs:state.result.runs, selectedRun:state.selectedRun
    });
    $("depth-selected").disabled = !state.selectedRun;
    changeViewer?.update({holeIds:state.result.query.hole_ids, selectedHole:state.selectedHole, ...state.depthView});
  }

  function inspectMineralChange(holeId, depth) {
    if (!state.result?.query.hole_ids.includes(holeId) || !Number.isFinite(depth)) return;
    selectHole(holeId);
    window.HyLoggerProfiles.pin($("depth-area"), holeId, depth);
    drawDepth();
    $("depth-title").scrollIntoView({behavior:"smooth", block:"start"});
    toast(`Pinned ${format(depth)} m in ${holeId}. Compare the scalar values above and below this candidate.`);
  }

  function selectHole(holeId) {
    if (!state.result?.holes.some((hole) => hole.hole_id === holeId)) return;
    state.selectedHole = holeId; state.mapHole = holeId; state.selectedRun = null;
    const point = collarPoints().find(hole => hole.hole_id === holeId);
    if (point && !pointInView(point)) fitMap(false, [holeId]);
    $("selected-hole").value = holeId;
    renderTables(); drawMap(); drawRegionalMap(); drawDepth(); renderEvidence(); renderCorePhoto();
  }

  function selectRun(runId) {
    const run = state.result?.runs.find((item) => item.run_id === runId);
    if (!run) return;
    state.selectedRun = runId; state.selectedHole = run.hole_id; state.mapHole = run.hole_id;
    const point = collarPoints().find(hole => hole.hole_id === run.hole_id);
    if (point && !pointInView(point)) fitMap(false, [run.hole_id]);
    $("selected-hole").value = run.hole_id;
    if (Number(run.from_m) < state.depthView.from || Number(run.to_m) > state.depthView.to) fitDepth();
    renderTables(); drawMap(); drawRegionalMap(); drawDepth(); renderEvidence(); renderCorePhoto();
  }

  function renderEvidence() {
    const run = state.result?.runs.find((item) => item.run_id === state.selectedRun);
    if (!run) {
      $("evidence-title").textContent = "Interval evidence";
      $("evidence-count").textContent = "No interval selected";
      $("evidence-content").className = "evidence-empty";
      $("evidence-content").innerHTML = '<span class="evidence-symbol" aria-hidden="true">≡</span><div><strong>Inspect values in the depth profiles.</strong><p>Click a depth to pin all indicators and their source references. If a condition is applied, select a matching interval to inspect its records here.</p></div>';
      return;
    }
    const ids = run.record_ids || [];
    let rows = ids.map((id) => state.records.get(String(id))).filter(Boolean);
    if (!rows.length && Array.isArray(state.result.evidence)) rows = state.result.evidence.filter((row) => row.run_id === run.run_id);
    else if (!rows.length && Array.isArray(state.result.evidence?.[run.run_id])) rows = state.result.evidence[run.run_id];
    $("evidence-title").textContent = `${run.hole_id} · ${interval(run)}`;
    $("evidence-count").textContent = `${rows.length} source records · ${format(run.length_m)} m`;
    $("evidence-content").className = "";
    const query = state.result.query;
    const missing = rows.length < ids.length ? ` ${ids.length - rows.length} referenced records could not be displayed.` : "";
    $("evidence-content").innerHTML = `<p class="evidence-explainer">Each adjacent source record is <strong>≥ ${format(query.threshold, 6)} ${escapeHTML(unitLabel(appliedMetric()))}</strong> across <strong>${format(run.length_m)} m along this hole</strong>, ${query.min_run_m == null ? "with no minimum-length restriction." : `meeting your ${format(query.min_run_m)} m minimum.`} This is a query match, not a geological boundary or proof of one rock type.${escapeHTML(missing)}</p><div class="table-scroll"><table class="evidence-table"><thead><tr><th scope="col">Depth interval</th><th scope="col">Value · ${escapeHTML(unitLabel(appliedMetric()))}</th><th scope="col">Original token</th><th scope="col">Source reference</th><th scope="col">Data record</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${interval(row)}</td><td><code>${escapeHTML(row.value)}</code></td><td><code>${escapeHTML(row.raw_token)}</code></td><td class="source-reference"><span title="Source ID: ${escapeHTML(row.source_id)}">${escapeHTML(row.source_filename || row.source_id)}</span><br><code title="Record ID: ${escapeHTML(row.record_id)}">${escapeHTML(String(row.record_id).slice(0, 14))}…</code></td><td>${escapeHTML(row.data_record_index)}</td></tr>`).join("") || '<tr><td colspan="5" class="table-empty">No source records available for this interval.</td></tr>'}</tbody></table></div>`;
    const endpoints = endpointDescription(run);
    if (endpoints) $("evidence-content").insertAdjacentHTML("afterbegin", `<p class="endpoint-explainer">${escapeHTML(endpoints)}</p>`);
  }

  function endpointDescription(run) {
    const reasons = {
      window_continues:"the query window clips a longer matching interval",
      nonmatch:"the adjacent record does not meet your threshold",
      source_na:"the adjacent source record is N.A.; no numeric value was reported",
      unknown_missing:"the adjacent record has an unknown missing value",
      invalid_value:"the adjacent value cannot be used",
      missing:"there is a gap in the source summary",
      source_start:"the available source summary starts here",
      source_end:"the available source summary ends here"
    };
    return [reasons[run.start_reason] ? "Start: " + reasons[run.start_reason] + "." : "", reasons[run.end_reason] ? "End: " + reasons[run.end_reason] + "." : ""].filter(Boolean).join(" ");
  }

  function fitDepth() {
    if (!state.result) return;
    state.depthView = {from:Number(state.result.query.depth_from_m), to:Number(state.result.query.depth_to_m)};
    $("view-from").value = state.depthView.from; $("view-to").value = state.depthView.to;
    showError("view-error", ""); drawDepth(); renderCorePhoto();
  }

  function zoomDepth(factor) {
    if (!state.result || !state.depthView) return;
    const query = state.result.query, center = (state.depthView.from + state.depthView.to) / 2;
    const span = Math.max(1, Math.min(query.depth_to_m - query.depth_from_m, (state.depthView.to - state.depthView.from) * factor));
    const from = Math.max(query.depth_from_m, Math.min(query.depth_to_m - span, center - span / 2));
    $("view-from").value = from;
    $("view-to").value = from + span;
    changeDepthView();
  }

  function zoomSelectedInterval() {
    const run = state.result?.runs.find((item) => item.run_id === state.selectedRun);
    if (!run) return;
    const query = state.result.query;
    const padding = Math.max(1, Number(run.length_m) * 0.15);
    $("view-from").value = Math.max(Number(query.depth_from_m), Number(run.from_m) - padding);
    $("view-to").value = Math.min(Number(query.depth_to_m), Number(run.to_m) + padding);
    changeDepthView();
    $("depth-area").scrollIntoView({block:"center", behavior:"smooth"});
  }

  function renderCorePhoto() {
    const run = state.result?.runs.find(item => item.run_id === state.selectedRun);
    const from = run ? Number(run.from_m) : state.depthView?.from;
    const to = run ? Number(run.to_m) : state.depthView?.to;
    const context = `${state.selectedHole}|${run?.run_id || "view"}|${from}|${to}`;
    const selected = context === core.context ? $("core-photo-select").value : null;
    core.context = context;
    const holePhotos = (state.catalog?.core_images || []).filter(photo => photo.hole_id === state.selectedHole);
    const photos = holePhotos.filter(photo => (photo.rows || []).some(row => row.from_m < to && row.to_m >= from))
      .sort((a, b) => a.depth_from_m - b.depth_from_m || a.tray_number - b.tray_number);
    const position = Math.max(0, photos.findIndex(photo => photo.photo_id === selected));
    const photo = photos[position];
    $("core-photo-select").innerHTML = photos.map(item => `<option value="${escapeHTML(item.photo_id)}">Tray ${item.tray_number} · ${format(item.depth_from_m)}–${format(item.depth_to_m)} m</option>`).join("") || '<option>No matching trays</option>';
    $("core-photo-select").disabled = !photo;
    $("core-photo-previous").disabled = !photo || position === 0;
    $("core-photo-next").disabled = !photo || position === photos.length - 1;
    $("core-photo-count").textContent = photo ? `${position + 1} / ${photos.length} trays` : "0 trays";
    const target = state.selectedHole && Number.isFinite(from) && Number.isFinite(to)
      ? `${run ? "Selected interval" : "Visible depth window"} · ${state.selectedHole} · [${format(from)}, ${format(to)}) m along hole.` : "Select a drillhole or matching interval.";
    $("core-photo-context").textContent = `${target}${photo ? " These trays have overlapping TSG scan depths. The whole tray is shown; pixels are not aligned to the query." : ""}`;
    if (!photo) {
      core.shown = null;
      $("core-photo-content").innerHTML = `<p class="subtle">${escapeHTML(!state.selectedHole ? "No drillhole selected." : holePhotos.length ? "No indexed tray overlaps this depth range." : `No verified local tray photos for ${state.selectedHole}.`)} Choose a matching interval to look for its source photographs.</p>`;
      return;
    }
    $("core-photo-select").value = photo.photo_id;
    if (core.shown === photo.photo_id) return;
    core.shown = photo.photo_id;
    const url = new URL(photo.url, location.origin);
    if (url.origin !== location.origin || !/^\/core-images\/[a-f0-9]{64}\.jpg$/.test(url.pathname)) {
      $("core-photo-content").textContent = "Photo reference is unavailable."; return;
    }
    const depth = `${format(photo.depth_from_m)}–${format(photo.depth_to_m)} m along hole`;
    $("core-photo-content").innerHTML = `<a href="${escapeHTML(url.pathname)}" target="_blank" rel="noopener"><img src="${escapeHTML(url.pathname)}" loading="lazy" alt="${escapeHTML(photo.hole_id)} original core tray ${photo.tray_number}. Observed scan extent ${escapeHTML(depth)}."></a><p><strong>${escapeHTML(photo.hole_id)} · Tray ${photo.tray_number}</strong> · Observed scan extent: ${escapeHTML(depth)}. <a href="${escapeHTML(url.pathname)}" target="_blank" rel="noopener">Open full size ↗</a></p><p class="subtle">Source: ${escapeHTML(photo.filename)} · ${escapeHTML(photo.source)}. Tray identity is checked against the JPEG metadata; depths come from ${escapeHTML(photo.depth_filename)}. Scan gaps may remain within this extent.</p><details class="photo-source-details"><summary>Photo and depth sources</summary><p>Photo SHA-256: <code>${escapeHTML(photo.sha256)}</code><br>TSG SHA-256: <code>${escapeHTML(photo.depth_sha256)}</code><br>${escapeHTML(photo.depth_source)}<br>Unrounded scan extent: ${photo.depth_from_m}–${photo.depth_to_m} m · ${photo.scan_count} scans.</p></details>`;
    $("core-photo-content").querySelector("img").addEventListener("error", event => {
      event.target.hidden = true;
      event.target.parentElement.insertAdjacentHTML("afterend", '<p class="inline-error">This local photo could not be loaded. Refresh the library to check its source.</p>');
    });
  }

  function changeDepthView() {
    if (!state.result) return;
    const from = Number($("view-from").value), to = Number($("view-to").value), query = state.result.query;
    if (!$("view-from").value.trim() || !$("view-to").value.trim() || !Number.isFinite(from) || !Number.isFinite(to) || from >= to || from < Number(query.depth_from_m) || to > Number(query.depth_to_m)) {
      showError("view-error", `Choose a display range inside [${query.depth_from_m}, ${query.depth_to_m}) m. The applied query is unchanged.`); return;
    }
    state.depthView = {from, to}; showError("view-error", ""); drawDepth(); renderCorePhoto();
  }

  function renderProvenance() {
    $("provenance-content").textContent = JSON.stringify({query_id:state.result?.query_id || null, applied_query:state.result?.query || null, versions:state.result?.versions || state.catalog?.versions, metric:state.result ? appliedMetric() : metricDetails(), audit:state.catalog?.audit, geographic_background:state.basemap?.metadata || {state:state.basemapError ? "fallback" : "loading"}, imagery_background:window.HyLoggerImagery.metadata(), regional_drill_area:"Rounded to 0.1 degrees, with overlapping areas grouped at the current zoom. Group centres are approximate, not source collar coordinates. Not for navigation or distance measurement.", local_collars:"Unrounded source GDA2020 coordinates. Landgate aerial imagery is requested in GDA2020. Transparent no-data areas reveal coarse Natural Earth geographic context. Surface context only; image resolution is not positional accuracy."}, null, 2);
  }

  function envelope() {
    return {schema_version:state.result.versions?.schema_version || "1.0", query:state.result.query, versions:state.result.versions, query_id:state.result.query_id};
  }

  function toast(message) {
    clearTimeout(state.toastTimer); $("toast").textContent = message; $("toast").hidden = false;
    state.toastTimer = setTimeout(() => { $("toast").hidden = true; }, 5000);
  }

  async function exportResult() {
    if (!state.result || isDirty() || state.busy) return;
    state.busy = true; updateControls(); showError("transfer-error", "");
    try {
      const blob = await api("/api/export", envelope(), true);
      const url = URL.createObjectURL(blob), link = document.createElement("a");
      link.href = url; link.download = `hylogger-${String(state.result.query_id).replace(/[^a-z0-9_-]/gi, "").slice(0, 16)}.zip`;
      document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
      toast("Result pack downloaded. Restore with query.json from the ZIP.");
    } catch (error) { showError("transfer-error", error.message); }
    finally { state.busy = false; updateControls(); }
  }

  async function restoreFile(file) {
    if (!file || state.busy) return;
    showError("transfer-error", "");
    if (file.size > 2 * 1024 * 1024) { showError("transfer-error", "Query JSON must be 2 MB or smaller."); return; }
    let payload;
    try { payload = JSON.parse(await file.text()); if (!payload || Array.isArray(payload) || typeof payload !== "object") throw new Error(); }
    catch { showError("transfer-error", "Choose a valid query.json object from an exported result pack."); return; }
    const sequence = ++state.requestSequence; state.busy = true; updateControls();
    try {
      const result = await api("/api/restore", payload);
      if (sequence === state.requestSequence) { commitResult(result, true); showError("request-error", ""); toast("Query restored and recomputed with matching versions."); }
    } catch (error) { if (sequence === state.requestSequence) showError("transfer-error", error.message); }
    finally { if (sequence === state.requestSequence) { state.busy = false; updateControls(); } }
  }

  function showTab(name) {
    for (const tab of ["holes", "runs"]) {
      const selected = tab === name;
      $(tab + "-tab").setAttribute("aria-selected", String(selected));
      $(tab + "-tab").tabIndex = selected ? 0 : -1;
      $(tab + "-panel").hidden = !selected;
    }
  }

  function notes(showTechnical = false) {
    renderProvenance();
    if (showTechnical) document.querySelector(".technical-details").open = true;
    $("notes-dialog").showModal();
  }

  function bindEvents() {
    $("query-form").addEventListener("submit", (event) => { event.preventDefault(); runQuery(); });
    $("query-form").addEventListener("input", () => { showError("form-error", ""); updateControls(); });
    $("filter-enabled").addEventListener("change", updateControls);
    document.querySelectorAll("[data-min-length]").forEach((button) => button.addEventListener("click", () => { $("min-length").value = button.dataset.minLength; updateControls(); }));
    $("metric").addEventListener("change", () => { updateMetric(true); updateControls(); });
    $("hole-group").addEventListener("change", chooseGroup);
    $("hole-options").addEventListener("change", event => {
      const input = event.target.closest('input[name="hole_id"]');
      if (!input) return;
      if (input.checked) picker.selected.add(input.value); else picker.selected.delete(input.value);
      updatePickerCount(); updateControls();
    });
    $("hole-search").addEventListener("input", () => { picker.search = $("hole-search").value; picker.page = 0; renderHolePicker(); });
    $("holes-previous").addEventListener("click", () => { picker.page = Math.max(0, picker.page - 1); renderHolePicker(); });
    $("holes-next").addEventListener("click", () => { picker.page++; renderHolePicker(); });
    $("holes-select-filtered").addEventListener("click", () => { filteredHoles().forEach(hole => picker.selected.add(hole.hole_id)); renderHolePicker(); updateControls(); });
    $("holes-clear").addEventListener("click", () => { picker.selected.clear(); renderHolePicker(); updateControls(); });
    $("holes-add").addEventListener("click", () => {
      const added = [...picker.selected].filter(id => !picker.list.has(id));
      picker.selected.forEach(id => picker.list.add(id));
      picker.selected.clear(); renderHolePicker(); renderAnalysisList(); updateControls();
      if (added.length) focusMapHole(added[added.length - 1], false);
      showError("form-error", "");
    });
    $("analysis-list").addEventListener("click", event => {
      const locate = event.target.closest("[data-locate-hole]");
      if (locate) { focusMapHole(locate.dataset.locateHole); return; }
      const button = event.target.closest("[data-remove-analysis-hole]");
      if (!button) return;
      picker.list.delete(button.dataset.removeAnalysisHole); renderAnalysisList(); updateControls();
    });
    $("analysis-list-clear").addEventListener("click", () => { picker.list.clear(); renderAnalysisList(); updateControls(); });
    $("depth-use-full").addEventListener("click", () => {
      const holes = listedDepthHoles().filter(hasDepthRange);
      if (holes.length) fillDepthRange(Math.min(...holes.map(hole => hole.depth_from_m)), Math.max(...holes.map(hole => hole.depth_to_m)));
    });
    $("depth-ranges").addEventListener("click", event => {
      const button = event.target.closest("button[data-depth-from]");
      if (button) fillDepthRange(Number(button.dataset.depthFrom), Number(button.dataset.depthTo));
    });
    $("selected-hole").addEventListener("change", (event) => selectHole(event.target.value));
    $("basemap-mode").addEventListener("change", () => {
      const mode = $("basemap-mode").value;
      window.HyLoggerImagery.setMode(mode);
      $("imagery-note").textContent = mode === "aerial" ? "Online aerial imagery · no account · personal / non-commercial use" : "No internet needed";
      drawMap(); drawRegionalMap(); renderProvenance();
    });
    $("export-button").addEventListener("click", exportResult);
    $("restore-button").addEventListener("click", () => $("restore-file").click());
    $("restore-file").addEventListener("change", (event) => { const file = event.target.files[0]; event.target.value = ""; restoreFile(file); });
    $("notes-button").addEventListener("click", () => notes());
    $("provenance-button").addEventListener("click", () => notes(true));
    $("close-notes").addEventListener("click", () => $("notes-dialog").close());
    $("notes-dialog").addEventListener("click", (event) => { if (event.target === $("notes-dialog")) { const rect = event.target.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close(); } });
    $("depth-zoom-in").addEventListener("click", () => zoomDepth(0.5));
    $("depth-zoom-out").addEventListener("click", () => zoomDepth(2));
    $("depth-selected").addEventListener("click", zoomSelectedInterval);
    $("depth-expand").addEventListener("click", () => {
      const expanded = document.querySelector(".visual-grid").classList.toggle("profile-expanded");
      $("depth-expand").setAttribute("aria-pressed", String(expanded));
      $("depth-expand").textContent = expanded ? "Compact profile" : "Expand profile";
      requestAnimationFrame(drawDepth);
    });
    $("core-photo-select").addEventListener("change", renderCorePhoto);
    for (const [id, step] of [["core-photo-previous", -1], ["core-photo-next", 1]]) {
      $(id).addEventListener("click", () => { $("core-photo-select").selectedIndex += step; renderCorePhoto(); });
    }
    $("refresh-library").addEventListener("click", refreshLibrary);
    $("view-from").addEventListener("change", changeDepthView); $("view-to").addEventListener("change", changeDepthView); $("depth-fit").addEventListener("click", fitDepth);
    ["holes", "runs"].forEach((tab) => {
      $(tab + "-tab").addEventListener("click", () => showTab(tab));
      $(tab + "-tab").addEventListener("keydown", (event) => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) { event.preventDefault(); const next = event.key === "Home" ? "holes" : event.key === "End" ? "runs" : tab === "holes" ? "runs" : "holes"; showTab(next); $(next + "-tab").focus(); } });
    });
    for (const id of ["holes-body", "runs-body", "depth-area", "map-area"]) {
      const activate = (event) => {
        if (event.target.closest("details")) return;
        const run = event.target.closest("[data-run]");
        if (run) { selectRun(run.dataset.run); return; }
        const hole = event.target.closest("[data-hole]");
        if (hole) { if (id === "map-area") focusMapHole(hole.dataset.hole); else selectHole(hole.dataset.hole); }
      };
      $(id).addEventListener("click", activate);
      $(id).addEventListener("keydown", (event) => { if ((event.key === "Enter" || event.key === " ") && event.target.closest("[data-run],[data-hole]")) { event.preventDefault(); activate(event); } });
    }
    $("map-fit").addEventListener("click", () => fitMap(true, state.localHoleIds));
    $("map-fit-list").addEventListener("click", () => fitMap(true, [...picker.list]));
    $("map-hole-select").addEventListener("change", event => focusMapHole(event.target.value));
    $("map-colour-by").addEventListener("change", drawMap);
    $("map-toggle-analysis").addEventListener("click", () => {
      const id = state.mapHole;
      if (!id || !state.catalog.holes.some(hole => hole.hole_id === id)) return;
      if (picker.list.has(id)) picker.list.delete(id); else picker.list.add(id);
      picker.selected.delete(id);
      renderHolePicker(); renderAnalysisList(); updateControls();
      showError("form-error", "");
    });
    $("map-inspect-current").addEventListener("click", () => {
      if (!state.result?.holes.some(hole => hole.hole_id === state.mapHole)) return;
      selectHole(state.mapHole);
      document.querySelector(".depth-card").scrollIntoView({behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block:"start"});
    });
    for (const [id, factor] of [["map-zoom-in", 0.7], ["map-zoom-out", 1 / 0.7]]) $(id).addEventListener("click", () => { if (!state.map) return; state.map.spanY = Math.max(0.00001, Math.min(30, state.map.spanY * factor)); state.map.spanX = state.map.spanY * 1.7; drawMap(); });
    let drag = null;
    $("map-area").addEventListener("pointerdown", (event) => { if (!state.map || event.target.closest("[data-hole]") || event.button !== 0) return; drag = {x:event.clientX, y:event.clientY, view:{...state.map}}; $("map-area").setPointerCapture(event.pointerId); $("map-area").classList.add("dragging"); });
    $("map-area").addEventListener("pointermove", (event) => { if (!drag) return; const bounds = $("map-area").getBoundingClientRect(); state.map.cx = drag.view.cx - (event.clientX - drag.x) / bounds.width * drag.view.spanX; state.map.cy = drag.view.cy + (event.clientY - drag.y) / bounds.height * drag.view.spanY; drawMap(); });
    const stopDrag = () => { drag = null; $("map-area").classList.remove("dragging"); };
    $("map-area").addEventListener("pointerup", stopDrag); $("map-area").addEventListener("pointercancel", stopDrag); $("map-area").addEventListener("lostpointercapture", stopDrag);
    $("regional-library").addEventListener("click", () => setRegionalPreset("library"));
    $("regional-region").addEventListener("click", () => setRegionalPreset("region"));
    $("regional-wa").addEventListener("click", () => setRegionalPreset("wa"));
    for (const [id, factor] of [["regional-zoom-in", 0.75], ["regional-zoom-out", 1 / 0.75]]) $(id).addEventListener("click", () => {
      if (!state.regionalView) return;
      state.regionalView.spanY = Math.max(6, Math.min(36, state.regionalView.spanY * factor));
      state.regionalView.spanX = state.regionalView.spanY * 1.8 / Math.cos(state.regionalView.cy * Math.PI / 180);
      state.regionalPreset = null;
      for (const preset of ["library", "region", "wa"]) $("regional-" + preset).setAttribute("aria-pressed", "false");
      drawRegionalMap();
    });
    const openLocalArea = (event) => {
      if (!event.target.closest("[data-drill-area]")) return;
      if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      const ids = event.target.closest("[data-drill-area]").dataset.drillArea.split(",");
      if (!ids.includes(state.mapHole)) state.mapHole = ids[0];
      fitMap(true, ids); drawRegionalMap();
      $("map-area").scrollIntoView({behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block:"center"});
      toast("Inspect the unrounded GDA2020 positions in the local collar view.");
    };
    $("regional-map-area").addEventListener("click", openLocalArea);
    $("regional-map-area").addEventListener("keydown", openLocalArea);
    let regionalDrag = null;
    $("regional-map-area").addEventListener("pointerdown", (event) => {
      if (!state.regionalView || event.target.closest("[data-drill-area]") || event.button !== 0) return;
      regionalDrag = {x:event.clientX, y:event.clientY, view:{...state.regionalView}};
      $("regional-map-area").setPointerCapture(event.pointerId); $("regional-map-area").classList.add("dragging");
    });
    $("regional-map-area").addEventListener("pointermove", (event) => {
      if (!regionalDrag) return;
      const bounds = $("regional-map-area").getBoundingClientRect();
      state.regionalView.cx = Math.max(100, Math.min(150, regionalDrag.view.cx - (event.clientX - regionalDrag.x) / bounds.width * regionalDrag.view.spanX));
      state.regionalView.cy = Math.max(-40, Math.min(-10, regionalDrag.view.cy + (event.clientY - regionalDrag.y) / bounds.height * regionalDrag.view.spanY));
      state.regionalPreset = null;
      for (const preset of ["library", "region", "wa"]) $("regional-" + preset).setAttribute("aria-pressed", "false");
      drawRegionalMap();
    });
    const stopRegionalDrag = () => { regionalDrag = null; $("regional-map-area").classList.remove("dragging"); };
    $("regional-map-area").addEventListener("pointerup", stopRegionalDrag);
    $("regional-map-area").addEventListener("pointercancel", stopRegionalDrag);
    $("regional-map-area").addEventListener("lostpointercapture", stopRegionalDrag);
    if (typeof ResizeObserver !== "undefined") {
      let profileWidth = 0;
      new ResizeObserver(entries => {
        const width = entries[0].contentRect.width;
        if (Math.abs(width - profileWidth) > 1) { profileWidth = width; if (state.result) drawDepth(); }
      }).observe($("depth-area"));
    }
  }

  function installCatalog(catalog, preferredQuery = null) {
    state.catalog = catalog;
    depthRangeKey = null;
    scalarPicker?.destroy();
    scalarPicker = window.HyLoggerScalarPicker.create($("scalar-picker"), {metrics:metrics(), onChange:() => { updateFilterOptions(); updateControls(); }});
    $("dataset-count").textContent = state.catalog.holes.length + " holes · " + metrics().length + " scalars";
    $("hole-group").innerHTML = '<option value="">All holes</option>' + groups().map((group) => '<option value="' + escapeHTML(group.id) + '">' + escapeHTML(group.label || group.id) + '</option>').join("");
    const metricGroups = new Map();
    for (const metric of metrics()) {
      const group = metric.group || metric.region || "Scalars";
      if (!metricGroups.has(group)) metricGroups.set(group, []);
      metricGroups.get(group).push(metric);
    }
    $("metric").innerHTML = [...metricGroups].map(([group, entries]) => '<optgroup label="' + escapeHTML(group) + '">' + entries.map((metric) => '<option value="' + escapeHTML(metric.metric_id || metric.id) + '">' + escapeHTML(metric.label || metric.source_field || metric.metric_id) + '</option>').join("") + '</optgroup>').join("");
    const notesList = state.catalog.notes;
    $("catalog-notes").innerHTML = Array.isArray(notesList) ? notesList.map((note) => `<p class="catalog-note">${escapeHTML(typeof note === "string" ? note : JSON.stringify(note))}</p>`).join("") : notesList ? `<p class="catalog-note">${escapeHTML(typeof notesList === "string" ? notesList : JSON.stringify(notesList))}</p>` : "";
    const initial = state.catalog.default_query || {metric_id:metricId(), hole_ids:state.catalog.holes.map((hole) => hole.hole_id), depth_from_m:0, depth_to_m:150};
    const examples = ["Kaolin_(System_SWIR)", "Other-MgOH_(System_SWIR)", "2200W_AlOH"].filter(id => metrics().some(metric => metric.metric_id === id));
    applyForm(preferredQuery || {...initial, display_metric_ids:examples.length ? examples : [initial.metric_id], operator:"none", threshold:null, min_run_m:null});
    if (!catalog.holes.some(hole => hole.hole_id === state.mapHole)) state.mapHole = [...picker.list][0] || catalog.holes[0]?.hole_id || null;
    const locatedList = collarPoints().filter(hole => picker.list.has(hole.hole_id)).map(hole => hole.hole_id);
    fitMap(false, locatedList.length ? locatedList : null);
    setRegionalPreset("library", false);
    drawMap(); drawRegionalMap();
    const library = catalog.library || {};
    $("library-status").textContent = `Put GSWA summary CSVs in data/inbox, then choose Refresh library. ${catalog.holes.length} holes available.`;
    const issues = library.issues || [];
    $("library-issues").hidden = !issues.length;
    $("library-issue-list").innerHTML = issues.map(item => `<p><strong>${escapeHTML(item.source_filename || item.hole_id || "File")}</strong><br>${escapeHTML(item.detail || item.reason || "Needs review")}</p>`).join("");
    core.context = ""; core.shown = null;
    renderCorePhoto();
  }

  async function refreshLibrary() {
    if (state.busy) return;
    let previous;
    try { previous = draftQuery(); } catch { previous = state.result ? {...state.result.query, hole_ids:[...picker.list]} : null; }
    state.busy = true; updateControls(); showError("request-error", "");
    let refreshed = false;
    try {
      const catalog = await api("/api/library/refresh", {});
      if (!Array.isArray(catalog.holes)) throw new Error("The server returned an incomplete library.");
      const available = new Set(catalog.holes.map(hole => hole.hole_id));
      const fields = new Set((catalog.metrics || []).map(metric => metric.metric_id || metric.id));
      const preferred = previous && fields.has(previous.metric_id)
        ? {...previous, hole_ids:previous.hole_ids.filter(id => available.has(id))} : null;
      state.result = null; state.records = new Map(); state.selectedRun = null; state.selectedHole = null;
      state.depthView = null; state.map = null; state.localHoleIds = null;
      changeViewer?.reset();
      for (const id of ["stat-runs", "stat-length", "stat-holes", "stat-coverage"]) $(id).textContent = "—";
      for (const id of ["holes-body", "runs-body"]) $(id).innerHTML = '<tr><td colspan="5" class="table-empty">Library refreshed. Preparing query…</td></tr>';
      $("depth-area").innerHTML = '<div class="chart-empty">Choose available holes and run a query.</div>';
      $("applied-summary").textContent = "Library refreshed. Previous results have been cleared.";
      $("selected-hole").innerHTML = '<option>No drillhole selected</option>'; $("selected-hole").disabled = true;
      $("depth-selected").disabled = true;
      installCatalog(catalog, preferred);
      drawMap(); drawRegionalMap(); renderEvidence(); renderProvenance();
      refreshed = true;
      toast(`${catalog.holes.length} holes available. New holes are listed in the library; choose them or a group to query.`);
    } catch (error) { showError("request-error", `Library refresh failed: ${error.message}`); }
    finally { state.busy = false; updateControls(); }
    if (refreshed && picker.list.size) await runQuery();
  }

  async function init() {
    changeViewer = window.HyLoggerChangeViewer.create($("change-card"), inspectMineralChange);
    bindEvents();
    setRegionalPreset("library", false); drawRegionalMap();
    loadBasemap();
    try {
      state.catalog = await api("/api/catalog");
      if (!Array.isArray(state.catalog.holes) || !state.catalog.holes.length) throw new Error("No local drillhole summaries are available.");
      installCatalog(state.catalog);
      updateControls(); renderProvenance(); await runQuery();
    } catch (error) {
      showError("request-error", `Unable to load the local workspace: ${error.message}`);
      $("query-status").textContent = "Unavailable";
      $("draft-status").textContent = "Check the local server and source files, then reload this page.";
    }
  }

  init();
})();
