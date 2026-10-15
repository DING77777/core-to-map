(function () {
  "use strict";

  let nextId = 0;
  const MAX_SELECTED = 6;

  function create(container, { metrics = [], onChange = () => {} } = {}) {
    if (!(container instanceof Element)) throw new TypeError("A scalar picker container is required.");

    const prefix = `scalar-picker-${++nextId}`;
    const catalog = new Map(metrics.map(metric => [metric.metric_id, metric]));
    const selected = new Set();
    const choices = new Map();
    const groups = new Map();
    let availability = new Map();
    let loading = true;
    let message = "";
    let searchText = "";

    const element = (tag, className, text) => {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    };

    const root = element("div", "scalar-picker");
    const details = element("details", "scalar-picker-menu");
    const summary = element("summary", "scalar-picker-summary");
    const summaryText = element("span", "", "Choose scalars");
    const count = element("span", "scalar-picker-count", "0 / 6");
    summary.append(summaryText, count);

    const panel = element("div", "scalar-picker-panel");
    const search = element("input", "scalar-picker-search");
    search.type = "search";
    search.placeholder = "Find a scalar";
    search.setAttribute("aria-label", "Find a scalar");
    search.autocomplete = "off";
    const list = element("div", "scalar-picker-options");
    const empty = element("p", "scalar-picker-empty", "No matching scalars.");
    empty.hidden = true;
    panel.append(search, list, empty);
    details.append(summary, panel);

    const chips = element("ul", "scalar-picker-chips");
    chips.setAttribute("aria-label", "Selected scalars");
    const status = element("p", "scalar-picker-status");
    status.id = `${prefix}-status`;
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.setAttribute("aria-atomic", "true");
    summary.setAttribute("aria-describedby", status.id);
    root.append(details, chips, status);
    container.replaceChildren(root);

    for (const [index, metric] of metrics.entries()) {
      const groupName = metric.group || "Scalars";
      if (!groups.has(groupName)) {
        const fieldset = element("fieldset", "scalar-picker-group");
        fieldset.append(element("legend", "", groupName));
        list.append(fieldset);
        groups.set(groupName, fieldset);
      }
      const label = element("label", "scalar-picker-choice");
      const input = element("input");
      input.type = "checkbox";
      input.id = `${prefix}-choice-${index}`;
      input.value = metric.metric_id;
      input.dataset.metricChoice = metric.metric_id;
      input.disabled = true;
      const text = element("span", "scalar-picker-choice-text");
      const name = element("span", "scalar-picker-choice-name", metric.label || metric.metric_id);
      const note = element("span", "scalar-picker-choice-note");
      note.id = `${input.id}-note`;
      input.setAttribute("aria-describedby", note.id);
      text.append(name, note);
      label.append(input, text);
      groups.get(groupName).append(label);
      choices.set(metric.metric_id, { input, label, note, metric, groupName });
    }

    function updateChoices() {
      const atLimit = selected.size >= MAX_SELECTED;
      for (const [id, choice] of choices) {
        const item = availability.get(id);
        const hasValues = item?.enabled === true;
        choice.input.checked = selected.has(id);
        choice.input.disabled = loading || !hasValues || (atLimit && !selected.has(id));
        choice.label.classList.toggle("is-unavailable", !loading && !hasValues);
        choice.label.classList.toggle("is-limited", !loading && hasValues && atLimit && !selected.has(id));
        choice.label.classList.toggle("is-selected", selected.has(id));
        if (loading) {
          choice.note.textContent = "Checking values…";
        } else if (!hasValues) {
          choice.note.textContent = "No numeric values in this window";
        } else {
          const populated = Number(item.holes_with_values);
          const total = Number(item.hole_count);
          choice.note.textContent = Number.isFinite(populated) && Number.isFinite(total)
            ? `${populated}/${total} holes with values`
            : `${Number(item.numeric_count) || 0} numeric values`;
        }
        choice.label.title = !loading && !hasValues && item?.reason
          ? item.reason : choice.note.textContent;
      }
      updateSearch();
    }

    function updateSearch() {
      let visibleCount = 0;
      const visibleGroups = new Set();
      for (const choice of choices.values()) {
        const haystack = `${choice.metric.label || ""} ${choice.metric.metric_id} ${choice.groupName}`.toLowerCase();
        const visible = !searchText || haystack.includes(searchText);
        choice.label.hidden = !visible;
        if (visible) {
          visibleCount += 1;
          visibleGroups.add(choice.groupName);
        }
      }
      for (const [name, fieldset] of groups) fieldset.hidden = !visibleGroups.has(name);
      empty.hidden = visibleCount !== 0;
    }

    function updateChips() {
      const focusedId = document.activeElement?.dataset.removeScalar;
      const nodes = [];
      for (const id of selected) {
        const metric = catalog.get(id);
        const unavailable = !loading && availability.get(id)?.enabled !== true;
        const chip = element("li", `scalar-picker-chip${unavailable ? " is-unavailable" : ""}`);
        const label = metric.label || id;
        chip.append(element("span", "", label));
        if (unavailable) chip.append(element("span", "scalar-picker-chip-note", "no values"));
        const remove = element("button", "scalar-picker-remove", "×");
        remove.type = "button";
        remove.dataset.removeScalar = id;
        remove.setAttribute("aria-label", `Remove ${label}`);
        chip.append(remove);
        nodes.push(chip);
      }
      chips.replaceChildren(...nodes);
      chips.hidden = selected.size === 0;
      if (focusedId && selected.has(focusedId)) {
        [...chips.querySelectorAll("button")].find(button => button.dataset.removeScalar === focusedId)?.focus();
      }
    }

    function update() {
      count.textContent = `${selected.size} / ${MAX_SELECTED}`;
      summaryText.textContent = selected.size ? "Compare scalars" : "Choose scalars";
      root.setAttribute("aria-busy", String(loading));
      updateChoices();
      updateChips();
      const availableCount = [...availability.values()].filter(item => item.enabled === true).length;
      status.textContent = loading ? (message || "Checking this depth window…")
        : selected.size >= MAX_SELECTED ? "6 selected · remove one to add another."
          : message || `${availableCount} scalars have values in this window.`;
    }

    function handleChange(event) {
      const input = event.target.closest("input[data-metric-choice]");
      if (!input || !root.contains(input)) return;
      const id = input.dataset.metricChoice;
      if (input.checked && !loading && availability.get(id)?.enabled === true && selected.size < MAX_SELECTED) {
        selected.add(id);
      } else if (!input.checked) {
        selected.delete(id);
      }
      update();
      onChange([...selected]);
    }

    function handleClick(event) {
      const button = event.target.closest("button[data-remove-scalar]");
      if (!button || !root.contains(button)) return;
      const oldButtons = [...chips.querySelectorAll("button")];
      const index = oldButtons.indexOf(button);
      selected.delete(button.dataset.removeScalar);
      update();
      const remaining = chips.querySelectorAll("button");
      (remaining[Math.min(index, remaining.length - 1)] || summary).focus();
      onChange([...selected]);
    }

    function handleSearch() {
      searchText = search.value.trim().toLowerCase();
      updateSearch();
    }

    function handleKeydown(event) {
      if (event.key === "Escape" && details.open) {
        event.preventDefault();
        event.stopPropagation();
        details.open = false;
        summary.focus();
      }
    }

    root.addEventListener("change", handleChange);
    root.addEventListener("click", handleClick);
    root.addEventListener("keydown", handleKeydown);
    search.addEventListener("input", handleSearch);
    update();

    return {
      setSelected(ids) {
        selected.clear();
        for (const id of ids || []) {
          if (catalog.has(id) && selected.size < MAX_SELECTED) selected.add(id);
        }
        update();
      },
      getSelected() {
        return [...selected];
      },
      setAvailability(items, options = {}) {
        availability = new Map((items || []).map(item => [item.metric_id, item]));
        loading = options.loading === true;
        message = options.message || "";
        update();
      },
      destroy() {
        root.removeEventListener("change", handleChange);
        root.removeEventListener("click", handleClick);
        root.removeEventListener("keydown", handleKeydown);
        search.removeEventListener("input", handleSearch);
        root.remove();
      },
    };
  }

  window.HyLoggerScalarPicker = { create };
})();
