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
  });
  targetSelect.addEventListener("change", () => {
    preferredTarget = targetSelect.value;
    targetHint.textContent = targetSelect.value === "MT900 / MT910"
      ? "The engine selects MT900 for debit entries and MT910 for credit entries."
      : "Only registered mappings are available.";
  });
  messageInput.addEventListener("input", updateCounter);

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
      messageInput.focus();
    });
  }

  populateTargets(true);
  updateCounter();
})();
