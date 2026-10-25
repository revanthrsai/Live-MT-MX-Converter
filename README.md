# Live MT-MX Converter

A small SWIFT MT ↔ ISO 20022 message converter built from the deterministic mapping engine in ISO 20022 Academy. It supports both a local Python runner and a GitHub Pages version that executes the same checked-in Python engine inside the browser using Pyodide/WebAssembly.

**This first release is intentionally rules-only.** It has no AI, no external conversion API, no cloud processing of message content, no runtime schema downloading, no auto-repair, and no analytics or database. In GitHub Pages mode, the Python runtime and the `lxml` XML package are loaded as static software assets from the pinned jsDelivr CDN. The converter runs in the browser; the pasted payment message is not sent to jsDelivr or a conversion service. The existing local mode still binds a Python server to `127.0.0.1` and performs conversion in that local process.

> **Important:** This is a development/learning tool, not a certified banking gateway or a production payment-processing system. Always review mapped fields, warnings, missing values and the relevant scheme/bank usage guidelines before using output in a real workflow.

## Features

- Simple source and destination dropdowns, populated from the engine's actual conversion registry.
- Paste an MT message or ISO 20022 XML into the browser page.
- Run code-based input checks before translating.
- Refuse unsupported source/destination combinations.
- Check output structure, field-level mapping rules and value fidelity after translation.
- Show the engine's notes, generated values and explicitly dropped fields.
- Copy or download the generated message.
- Process message content locally; no remote conversion service is called. The local runner suppresses request logging.

## Requirements

- Python 3.10 or newer (the code uses standard-library features and Python type syntax).
- `lxml` for safe XML parsing and writing.
- A modern browser.

## Run it locally

From the repository directory:

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

Then open the local URL printed by the program (by default `http://127.0.0.1:8765`). Stop the process with `Ctrl+C`.

A different local port can be selected with `python run.py 8766`.

## Host the converter on GitHub Pages

This repository includes a GitHub Actions workflow at `.github/workflows/pages.yml`. It builds a static website from `docs/` and copies the canonical Python engine from `app/` into the generated site. The mapping engine is not duplicated or separately rewritten for the hosted version.

1. Push the workflow and the modified project files to the `main` branch.
2. On GitHub, open **Settings → Pages** for the repository.
3. Under **Build and deployment**, set **Source** to **GitHub Actions**.
4. Push a new commit or manually run **Deploy Live MT-MX Converter to GitHub Pages** from the **Actions** tab.
5. Open `https://revanthrsai.github.io/Live-MT-MX-Converter/` after the deployment workflow succeeds.

The workflow runs `python scripts/build_pages.py`, which creates the `dist/` folder used by the Pages deployment. You do not need to commit `dist/`. The page reads the actual converter registry from `app/engine/__init__.py`, so the source and destination dropdowns stay aligned with the engine rules.

**Runtime/network note:** Pyodide and `lxml` are pinned and downloaded from jsDelivr on first use (then typically cached by the browser). This is not a conversion API: the message itself is processed in the browser. The current Pages version needs a network connection to load those runtime assets. If you require all runtime assets to be hosted only from your own repository, the Pyodide distribution and compatible `lxml` package can be vendored in a separate packaging step.

For local Python mode, the only third-party dependency to install is `lxml`; local runtime conversion makes no outbound network calls. Installing Python packages may require internet access unless they are already available in your environment.

## Supported conversion pairs in this release

The target dropdown offers only pairs registered in `app/engine/__init__.py`.

| Source | Destination | Notes |
|---|---|---|
| `pacs.008` | `MT103` | Credit transfer |
| `pacs.004` | `MT103 RETN` | Payment return |
| `pacs.002` | `MT199` | Status to free-format text |
| `pain.001` | `MT101` | Payment initiation |
| `pain.002` | `MT199` | Status to free-format text |
| `pain.008` | `MT104` | Direct debit |
| `camt.053` | `MT940` | Statement |
| `camt.054` | `MT900 / MT910` | Engine selects debit/credit type from `CdtDbtInd` |
| `camt.056` | `MT192` | Cancellation request |
| `MT103` | `pacs.008` | Credit transfer |
| `MT103 RETN` | `pacs.004` | Payment return |
| `MT101` | `pain.001` | Payment initiation |
| `MT104` | `pain.008` | Direct debit |
| `MT940` | `camt.053` | Statement |
| `MT900 / MT910` | `camt.054` | Debit/credit notification |
| `MT192` | `camt.056` | Cancellation request |

Notably, `MT199` is a supported destination for `pacs.002` and `pain.002`, but there is no registered general `MT199` source mapping. Pairs such as `pacs.009 → MT202` are not implemented in this release and are intentionally unavailable.

## What the checks cover

The deterministic checks currently include:

- XML parsing with entity resolution, DTD loading and network access disabled.
- Message family/type detection from XML namespaces or MT tags/blocks.
- IBAN formatting, country lengths for the countries in the built-in table, and mod-97 checksum.
- BIC shape, UETR UUID form, date parsing, MT references, key MT mandatory fields, selected amount/currency rules, line-length warnings and transaction count/control-sum consistency.
- Pair-specific rules for important fields such as amount, currency, dates, references, charges, account fields, UETR and statement balances.
- Comparison of money-critical values between source and destination, including values that were not carried over or appear unexpectedly.

This is **not full official XSD validation** in the current archive: no ISO 20022 XSD files were included. The validator can use matching XSD files supplied locally in `schemas/`, but it never downloads them. Without those files, validation is limited to the rules implemented in this codebase. The IBAN country-length table is also a finite built-in list, not a live official registry.

## Message versions and future updates

This release does not try to auto-follow annual ISO 20022 changes. Each XML message profile has an explicit version in `app/formats.py`, under `MESSAGE_VERSIONS`. Generated MX documents use that shared version profile. The converter blocks an MX input whose namespace version differs from the configured version for that message family, because compatible structure must not be assumed without testing.

When a new message version is to be supported:

1. Review the new local schema/specification and applicable usage guideline.
2. Add the version to `MESSAGE_VERSIONS` only after review.
3. Update mapping code only where structure or semantics changed.
4. Add or update synthetic fixtures and regression tests.
5. Release a versioned update with the supported version and limitations documented.

This centralizes the version points to review, but it does not make future versions automatically compatible. Automatic schema discovery/AI assistance is explicitly out of scope for this repository's first phase.

## Repository layout

```text
app/
  checks.py             deterministic input/output validation and value comparison
  formats.py            format profiles and centralized ISO message versions
  mappings.py           deterministic source/destination field-level checks
  engine/
    io.py               safe MT/XML readers and writers
    mx_to_mt.py         ISO 20022 → MT mapping functions
    mt_to_mx.py         MT → ISO 20022 mapping functions
    __init__.py         supported pairs, splitting and translation orchestration
web/
  index.html            plain HTML interface for the local Python runner
  app.js                local dropdown and button behavior
  styles.css            responsive presentation
docs/
  index.html            static GitHub Pages interface
  app.js                loads Pyodide and calls the checked-in engine locally
  bridge.py             JSON bridge from the page into the Python engine
scripts/build_pages.py  copies the canonical engine into dist/ for deployment
.github/workflows/pages.yml  builds and deploys the static Pages site
server.py               loopback-only local form handler
examples/               synthetic sample messages
tests/                  deterministic tests
```

## Tests

Install development test tools with `python -m pip install -r requirements-dev.txt`, then run:

```bash
python -m pytest -q
```

The tests use synthetic examples and verify conversion pairs, validation behavior, mapping checks, and value fidelity. They do not call external services.

## Privacy and safety

- In local mode, the Python server binds only to `127.0.0.1`, not your LAN address or a public interface.
- In GitHub Pages mode, conversion runs in the visitor's browser. The pasted message is not sent to jsDelivr or a conversion service; only the runtime/package assets and checked-in engine source are downloaded.
- The app does not log or persist pasted source messages.
- Do not paste production customer messages into public issue trackers or commit them as fixtures.
- Conversion can be lossy. The app lists known dropped fields and value-fidelity findings, but its checks cannot prove universal compliance with every bank or scheme rule.

## Push changes to the existing GitHub repository

For the existing `revanthrsai/Live-MT-MX-Converter` repository, extract this archive into your already-cloned local repository folder and allow the files to merge/overwrite the earlier version. Keep the existing `.git/` folder. Then run:

```bash
git status
git add .
git commit -m "Add browser-based GitHub Pages converter"
git push origin main
```

After the push, verify that **Settings → Pages → Build and deployment → Source** is set to **GitHub Actions**. The workflow in `.github/workflows/pages.yml` builds and deploys the site. Choose a license before making the repository public if you want others to reuse or redistribute the code.

## License

Choose and add a license before publishing this repository publicly. The source code is prepared for a separate repository, but this archive intentionally does not select a license on the owner's behalf.
