(() => {
  "use strict";

  const PYODIDE_VERSION = "v314.0.7";
  const PYODIDE_BASE = `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/`;
  const FILES = [
    "app/__init__.py",
    "app/checks.py",
    "app/formats.py",
    "app/mappings.py",
    "app/engine/__init__.py",
    "app/engine/io.py",
    "app/engine/mx_to_mt.py",
    "app/engine/mt_to_mx.py",
  ];
  const byId = (id) => document.getElementById(id);
  const banner = byId("runtimeBanner");
  const runtimeTitle = byId("runtimeTitle");
  const runtimeDetail = byId("runtimeDetail");
  const sourceSelect = byId("sourceFormat");
  const targetSelect = byId("targetFormat");
  const messageInput = byId("sourceMessage");
  const inputCounter = byId("inputCounter");
  const checkButton = byId("checkButton");
  const translateButton = byId("translateButton");
  const resultContainer = byId("resultContainer");
  const loadSampleButton = byId("loadSample");
  const clearButton = byId("clearInput");

  let pyodide = null;
  let pairMap = {};
  let pythonReady = false;
  let busy = false;

  const SAMPLE_FILES = {
    "pacs.008": "pacs.008.xml",
    "pain.001": "pain.001.xml",
    "camt.053": "camt.053.xml",
    "MT103": "MT103.txt",
    "MT101": "MT101.txt",
    "MT940": "MT940.txt",
  };

  function setBanner(state, title, detail) {
    banner.classList.remove("ready", "error");
    if (state) banner.classList.add(state);
    runtimeTitle.textContent = title;
    runtimeDetail.textContent = detail;
  }

  function asset(path) {
    return new URL(path, new URL(".", window.location.href)).toString();
  }

  async function getText(path) {
    const response = await fetch(asset(path), { cache: "no-cache", credentials: "same-origin" });
    if (!response.ok) throw new Error(`Could not load ${path} (HTTP ${response.status}).`);
    return response.text();
  }

  function setControlsEnabled(enabled) {
    sourceSelect.disabled = !enabled;
    targetSelect.disabled = !enabled || !(pairMap[sourceSelect.value] || []).length;
    messageInput.disabled = !enabled;
    checkButton.disabled = !enabled || busy;
    translateButton.disabled = !enabled || busy || !(pairMap[sourceSelect.value] || []).length;
    loadSampleButton.disabled = !enabled || busy;
    clearButton.disabled = !enabled || busy;
  }

  async function loadPyodideScript() {
    if (typeof window.loadPyodide === "function") return;
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = `${PYODIDE_BASE}pyodide.js`;
      script.async = true;
      script.onload = resolve;
      script.onerror = () => reject(new Error("The browser could not load the Python runtime from jsDelivr. Check your connection or browser network policy."));
      document.head.append(script);
    });
  }

  async function loadEngineFiles() {
    for (const relativePath of FILES) {
      const source = await getText(`python/${relativePath}`);
      const targetPath = `/home/pyodide/${relativePath}`;
      const parentPath = targetPath.slice(0, targetPath.lastIndexOf("/"));
      pyodide.FS.mkdirTree(parentPath);
      pyodide.FS.writeFile(targetPath, source, { encoding: "utf8" });
    }
    pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide')");
    const bridgeSource = await getText("bridge.py");
    await pyodide.runPythonAsync(bridgeSource);
  }

  function populateSources(sources) {
    sourceSelect.replaceChildren();
    for (const source of sources) {
      const option = document.createElement("option");
      option.value = source.value;
      option.textContent = source.label;
      sourceSelect.append(option);
    }
    if (sources.some((s) => s.value === "pacs.008")) sourceSelect.value = "pacs.008";
    else if (sources.length) sourceSelect.value = sources[0].value;
    populateTargets();
  }

  function populateTargets() {
    const source = sourceSelect.value;
    const targets = pairMap[source] || [];
    const previous = targetSelect.value;
    targetSelect.replaceChildren();

    if (!targets.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No registered destination";
      targetSelect.append(option);
      targetSelect.disabled = true;
      translateButton.disabled = true;
      byId("targetHint").textContent = "No deterministic conversion is registered for this source.";
      return;
    }

    targets.forEach((target) => {
      const option = document.createElement("option");
      option.value = target;
      option.textContent = target === "MT900 / MT910"
        ? "MT900 / MT910 — selected from debit/credit indicator"
        : target;
      targetSelect.append(option);
    });
    targetSelect.value = targets.includes(previous) ? previous : targets[0];
    targetSelect.disabled = !pythonReady || busy;
    translateButton.disabled = !pythonReady || busy;
    byId("targetHint").textContent = targetSelect.value === "MT900 / MT910"
      ? "The engine selects MT900 for debit entries and MT910 for credit entries."
      : "Only registered mappings are available.";
  }

  function create(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function renderFindingsSection(title, findings) {
    const section = create("section", "report-section");
    section.append(create("h4", "", title));
    if (!findings || findings.length === 0) {
      section.append(create("p", "empty-note", "None of the configured code checks found issues."));
      return section;
    }
    const list = create("div", "finding-list");
    findings.forEach((finding) => {
      const card = create("article", `finding ${finding.severity === "warning" ? "warning" : "error"}`);
      card.append(create("strong", "", `${finding.severity === "warning" ? "Warning" : "Error"} · ${finding.rule || "Check"}`));
      card.append(create("p", "", finding.message || "A check failed."));
      if (finding.value) card.append(create("p", "finding-value", `Value: ${finding.value}`));
      if (finding.where) card.append(create("p", "finding-where", finding.where));
      list.append(card);
    });
    section.append(list);
    return section;
  }

  function addDetailList(parent, title, entries, formatter) {
    if (!Array.isArray(entries) || entries.length === 0) return;
    const details = create("details", "details-list");
    details.append(create("summary", "", `${title} (${entries.length})`));
    const list = create("ul");
    entries.slice(0, 100).forEach((entry) => list.append(create("li", "", formatter(entry))));
    if (entries.length > 100) list.append(create("li", "", `And ${entries.length - 100} more…`));
    details.append(list);
    parent.append(details);
  }

  function renderOutput(data) {
    if (!data.outputMessage) return;
    const panel = create("section", "output-panel output-section");
    const header = create("div", "output-header");
    header.append(create("h4", "", "Generated destination message"));
    const actions = create("div", "output-actions");
    const copyButton = create("button", "small-button", "Copy output");
    copyButton.type = "button";
    copyButton.addEventListener("click", async () => {
      const output = byId("outputMessage");
      try {
        await navigator.clipboard.writeText(output.value);
        copyButton.textContent = "Copied";
      } catch (_error) {
        output.focus();
        output.select();
        copyButton.textContent = "Select and copy";
      }
    });
    const downloadButton = create("button", "small-button", "Download");
    downloadButton.type = "button";
    downloadButton.addEventListener("click", () => {
      const target = targetSelect.value;
      const extension = /^(pacs\.|pain\.|camt\.)/.test(target) ? "xml" : "txt";
      const blob = new Blob([byId("outputMessage").value], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = create("a");
      link.href = url;
      link.download = `converted-message.${extension}`;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    });
    actions.append(copyButton, downloadButton);
    header.append(actions);
    panel.append(header);

    const output = create("textarea", "output-textarea");
    output.id = "outputMessage";
    output.readOnly = true;
    output.spellcheck = false;
    output.setAttribute("aria-label", "Generated destination message");
    output.value = data.outputMessage;
    panel.append(output);

    const fidelity = data.fidelity || {};
    const meta = create("div", "output-meta");
    meta.append(create("span", "meta-pill", `Value fidelity: ${fidelity.ok ? "passed" : "review"}`));
    meta.append(create("span", "meta-pill", `${(data.filled || []).length} generated / filled values`));
    meta.append(create("span", "meta-pill", `${(data.dropped || []).length} explicitly dropped fields`));
    panel.append(meta);

    if (fidelity.invented && fidelity.invented.length) {
      const box = create("div", "report-box error");
      box.append(create("strong", "", "Unexpected output values detected"));
      const list = create("ul");
      fidelity.invented.slice(0, 20).forEach((item) => list.append(create("li", "", `${item.kind}: ${item.value}`)));
      box.append(list);
      panel.append(box);
    }
    if (fidelity.dropped && fidelity.dropped.length) {
      const box = create("div", "report-box warning");
      box.append(create("strong", "", "Source values not found in output"));
      const list = create("ul");
      fidelity.dropped.slice(0, 20).forEach((item) => list.append(create("li", "", `${item.kind}: ${item.value}`)));
      box.append(list);
      panel.append(box);
    }
    if (data.notes && data.notes.length) {
      const box = create("div", "report-box");
      box.append(create("strong", "", "Engine notes"));
      const list = create("ul", "notes-list");
      data.notes.forEach((note) => list.append(create("li", "", note)));
      box.append(list);
      panel.append(box);
    }
    addDetailList(panel, "Generated or filled fields", data.filled, (item) => `${item.field}: ${item.value}${item.reason ? ` — ${item.reason}` : ""}`);
    addDetailList(panel, "Fields explicitly dropped by mapping rules", data.dropped, (item) => `${item.field}: ${item.value}${item.reason ? ` — ${item.reason}` : ""}`);
    addDetailList(panel, "Values carried over", fidelity.carried, (item) => `${item.kind}: ${item.value}`);
    addDetailList(panel, "New references", fidelity.new_references, (item) => item);
    addDetailList(panel, "Truncated references", fidelity.truncated, (item) => item);
    return panel;
  }

  function renderReport(data) {
    resultContainer.replaceChildren();
    const sourceFindings = data.sourceFindings || [];
    const outputFindings = data.outputFindings;
    const allFindings = sourceFindings.concat(outputFindings || []);
    const errors = allFindings.filter((f) => f.severity === "error").length;
    const warnings = allFindings.filter((f) => f.severity === "warning").length;
    const state = errors ? "Review required" : warnings ? "Passed with warnings" : "Passed code checks";
    const stateClass = errors ? "error" : warnings ? "warning" : "success";

    const report = create("section", "result-panel");
    report.id = "resultPanel";
    const heading = create("div", "result-heading");
    const titleBlock = create("div");
    titleBlock.append(create("p", "eyebrow", "CHECK REPORT"));
    titleBlock.append(create("h3", "", data.title || "Result"));
    heading.append(titleBlock, create("span", `status-chip ${stateClass}`, state));
    report.append(heading);
    report.append(renderFindingsSection("Source message checks", sourceFindings));
    if (outputFindings !== null && outputFindings !== undefined) {
      report.append(renderFindingsSection("Destination message checks", outputFindings));
    }
    if (data.extra) {
      const extra = create("div", `report-box${errors ? " error" : warnings ? " warning" : ""}`, data.extra);
      report.append(extra);
    }
    resultContainer.append(report);
    const outputPanel = renderOutput(data);
    if (outputPanel) resultContainer.append(outputPanel);
    resultContainer.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function runAction(action) {
    if (!pythonReady || busy) return;
    const message = messageInput.value;
    if (message.length > 1_000_000) {
      renderReport({
        title: "Input too large",
        sourceFindings: [{ severity: "error", rule: "Message size", where: "Source message", value: String(message.length), message: "The maximum message size is 1,000,000 characters." }],
        outputFindings: null, outputMessage: "", notes: [], filled: [], dropped: [], fidelity: {}, extra: "",
      });
      return;
    }

    busy = true;
    setControlsEnabled(true);
    checkButton.disabled = true;
    translateButton.disabled = true;
    const oldText = action === "convert" ? "Translating…" : "Checking…";
    const targetButton = action === "convert" ? translateButton : checkButton;
    const previousText = targetButton.textContent;
    targetButton.textContent = oldText;
    setBanner("", action === "convert" ? "Running conversion rules…" : "Checking source message…", "The selected deterministic checks are running. No conversion service is involved.");

    try {
      pyodide.globals.set("browser_payload_json", JSON.stringify({
        action,
        source: sourceSelect.value,
        target: targetSelect.value,
        message,
      }));
      const rawResult = pyodide.runPython("process_payload_json(browser_payload_json)");
      pyodide.globals.delete("browser_payload_json");
      renderReport(JSON.parse(rawResult));
      setBanner("ready", "Local engine ready", "Mapping and validation completed. Your source message was not sent to a conversion service.");
    } catch (error) {
      console.error("Live MT-MX browser engine error", error);
      renderReport({
        title: "Local engine error",
        sourceFindings: [{ severity: "error", rule: "Browser runtime", where: "Local conversion", value: "", message: `The browser could not complete this action. ${String(error.message || error).slice(0, 350)}` }],
        outputFindings: null, outputMessage: "", notes: [], filled: [], dropped: [], fidelity: {}, extra: "",
      });
      setBanner("error", "Conversion error", "The local engine could not complete the request. Review the result panel or reload the page to initialize the runtime again.");
    } finally {
      busy = false;
      targetButton.textContent = previousText;
      setControlsEnabled(pythonReady);
      updateCounter();
    }
  }

  function updateCounter() {
    inputCounter.textContent = `${messageInput.value.length.toLocaleString()} characters`;
  }

  async function loadSample() {
    const filename = SAMPLE_FILES[sourceSelect.value];
    if (!filename) {
      setBanner("ready", "No bundled sample for this source", "Paste a synthetic message matching the selected format, or select pacs.008, pain.001, camt.053, MT103, MT101 or MT940.");
      return;
    }
    try {
      messageInput.value = await getText(`examples/${filename}`);
      updateCounter();
      resultContainer.replaceChildren();
      setBanner("ready", "Synthetic sample loaded", "The sample uses synthetic test data. Review it before translating.");
    } catch (error) {
      setBanner("error", "Could not load sample", error.message || String(error));
    }
  }

  sourceSelect.addEventListener("change", () => {
    populateTargets();
    resultContainer.replaceChildren();
  });
  targetSelect.addEventListener("change", () => {
    byId("targetHint").textContent = targetSelect.value === "MT900 / MT910"
      ? "The engine selects MT900 for debit entries and MT910 for credit entries."
      : "Only registered mappings are available.";
    resultContainer.replaceChildren();
  });
  messageInput.addEventListener("input", () => {
    updateCounter();
    resultContainer.replaceChildren();
  });
  checkButton.addEventListener("click", () => runAction("validate"));
  translateButton.addEventListener("click", () => runAction("convert"));
  loadSampleButton.addEventListener("click", loadSample);
  clearButton.addEventListener("click", () => {
    messageInput.value = "";
    updateCounter();
    messageInput.focus();
    resultContainer.replaceChildren();
  });

  async function initialize() {
    try {
      setBanner("", "Preparing the mapping engine…", "Loading the pinned Python runtime and XML support. First-time setup may take a little longer.");
      await loadPyodideScript();
      pyodide = await window.loadPyodide({ indexURL: PYODIDE_BASE });
      await pyodide.loadPackage("lxml");
      await loadEngineFiles();
      const metadataRaw = pyodide.runPython("get_metadata_json()");
      const metadata = JSON.parse(metadataRaw);
      pairMap = metadata.pairs || {};
      populateSources(metadata.sources || []);
      pythonReady = true;
      setControlsEnabled(true);
      updateCounter();
      setBanner("ready", "Mapping engine ready", "The existing Python mapping engine and code-based checks are ready. Your messages are processed locally.");
    } catch (error) {
      console.error("Live MT-MX runtime initialization failed", error);
      setBanner("error", "Could not initialize the mapping engine", `${String(error.message || error).slice(0, 400)} Check your internet connection and browser network policy, then reload. No conversion API is configured.`);
      setControlsEnabled(false);
    }
  }

  updateCounter();
  initialize();
})();
