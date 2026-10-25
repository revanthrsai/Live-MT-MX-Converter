(() => {
  const sourceSelect = document.getElementById("sourceFormat");
  const targetSelect = document.getElementById("targetFormat");
  const targetHint = document.getElementById("targetHint");
  const translateButton = document.getElementById("translateButton");
  const messageInput = document.getElementById("sourceMessage");
  const counter = document.getElementById("inputCounter");
  let pairs = {};
  try {
    pairs = JSON.parse(document.body.dataset.pairs || "{}");
  } catch (_error) {
    pairs = {};
  }

  let preferredTarget = document.body.dataset.selectedTarget || "";

  const sampleFiles = {
    "pacs.008": "pacs.008.xml",
    "pacs.004": "pacs.004.xml",
    "pacs.002": "pacs.002.xml",
    "pain.001": "pain.001.xml",
    "pain.002": "pain.002.xml",
    "pain.008": "pain.008.xml",
    "camt.053": "camt.053.xml",
    "camt.054": "camt.054.xml",
    "camt.056": "camt.056.xml",
    "MT103": "MT103.txt",
    "MT103 RETN": "MT103-RETN.txt",
    "MT101": "MT101.txt",
    "MT104": "MT104.txt",
    "MT940": "MT940.txt",
    "MT900 / MT910": "MT910.txt",
    "MT192": "MT192.txt",
  };

  function clearRenderedResults() {
    document.querySelectorAll("#resultPanel, #outputPanel").forEach((node) => node.remove());
  }

  function populateTargets(preserveChoice = true) {
    const source = sourceSelect.value;
    const available = pairs[source] || [];
    const previous = preserveChoice ? (targetSelect.value || preferredTarget) : "";
    targetSelect.replaceChildren();

    if (available.length === 0) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No registered destination";
      targetSelect.append(option);
      targetSelect.disabled = true;
      translateButton.disabled = true;
      targetHint.textContent = "No deterministic conversion is registered for this source.";
      return;
    }

    for (const target of available) {
      const option = document.createElement("option");
      option.value = target;
      option.textContent = target === "MT900 / MT910" ? "MT900 / MT910 — selected from debit/credit indicator" : target;
      targetSelect.append(option);
    }

    targetSelect.disabled = false;
    translateButton.disabled = false;
    targetSelect.value = available.includes(previous) ? previous : available[0];
    preferredTarget = targetSelect.value;
    targetHint.textContent = targetSelect.value === "MT900 / MT910"
      ? "The engine selects MT900 for debit entries and MT910 for credit entries."
      : "Only registered mappings are available.";
  }

  function updateCounter() {
    counter.textContent = `${messageInput.value.length.toLocaleString()} characters`;
  }

  sourceSelect.addEventListener("change", () => {
    preferredTarget = "";
    populateTargets(false);
    clearRenderedResults();
  });
  targetSelect.addEventListener("change", () => {
    preferredTarget = targetSelect.value;
    targetHint.textContent = targetSelect.value === "MT900 / MT910"
      ? "The engine selects MT900 for debit entries and MT910 for credit entries."
      : "Only registered mappings are available.";
  });
  messageInput.addEventListener("input", () => {
    updateCounter();
    clearRenderedResults();
  });

  const copyButton = document.getElementById("copyOutput");
  if (copyButton) {
    copyButton.addEventListener("click", async () => {
      const output = document.getElementById("outputMessage");
      try {
        await navigator.clipboard.writeText(output.value);
        copyButton.textContent = "Copied";
      } catch (_error) {
        output.focus();
        output.select();
        copyButton.textContent = "Select and copy";
      }
    });
  }

  const downloadButton = document.getElementById("downloadOutput");
  if (downloadButton) {
    downloadButton.addEventListener("click", () => {
      const output = document.getElementById("outputMessage");
      const target = document.getElementById("targetFormat").value;
      const extension = target.startsWith("pacs.") || target.startsWith("pain.") || target.startsWith("camt.") ? "xml" : "txt";
      const blob = new Blob([output.value], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `converted-message.${extension}`;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    });
  }

  const clearButton = document.getElementById("clearInput");
  if (clearButton) {
    clearButton.addEventListener("click", () => {
      messageInput.value = "";
      updateCounter();
      clearRenderedResults();
      messageInput.focus();
    });
  }

  const loadSampleButton = document.getElementById("loadSample");
  if (loadSampleButton) {
    loadSampleButton.addEventListener("click", async () => {
      const filename = sampleFiles[sourceSelect.value];
      if (!filename) return;
      loadSampleButton.disabled = true;
      const previousText = loadSampleButton.innerHTML;
      loadSampleButton.textContent = "Loading…";
      try {
        const url = new URL(`examples/${filename}`, window.location.href);
        const response = await fetch(url, { cache: "no-cache", credentials: "same-origin" });
        if (!response.ok) throw new Error(`Could not load sample (HTTP ${response.status}).`);
        messageInput.value = await response.text();
        updateCounter();
        clearRenderedResults();
      } catch (error) {
        window.alert(error.message || "Unable to load the sample message.");
      } finally {
        loadSampleButton.innerHTML = previousText;
        loadSampleButton.disabled = false;
      }
    });
  }

  populateTargets(true);
  updateCounter();
})();
