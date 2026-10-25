# Architecture and update policy

## Conversion paths

The project has two user interfaces and one conversion engine:

- **Local mode:** `web/` submits to `server.py`, which calls the existing Python package in `app/`.
- **GitHub Pages mode:** `docs/app.js` loads Pyodide (Python compiled to WebAssembly) and the `lxml` package, writes the checked-in `app/` modules into the browser's Python virtual filesystem, and calls `docs/bridge.py`.
- **Shared engine:** `app/engine/`, `app/checks.py`, `app/formats.py`, and `app/mappings.py` remain the canonical rules-based implementation. The Pages build copies these exact source files into the static deployment folder; it does not maintain a separate JavaScript copy of mapping logic.

The GitHub Pages version has no conversion API, server-side conversion endpoint, AI fallback, or runtime schema downloader. Pyodide and `lxml` static assets are loaded from the pinned jsDelivr CDN; message contents are passed only from the page into the local browser runtime and are not included in CDN requests.

## GitHub Pages deployment

1. Commit the `.github/workflows/pages.yml` workflow and all changed project files to `main`.
2. Set **Repository Settings → Pages → Build and deployment → Source** to **GitHub Actions**.
3. The workflow runs `scripts/build_pages.py`. That script copies the static UI to `dist/`, copies the canonical `app/*.py` files to `dist/python/app/`, and copies synthetic XML/MT examples.
4. GitHub Actions deploys `dist/` as the Pages artifact. `dist/` is generated and should not be committed.

The deployed page URL for this repository is expected to be `https://revanthrsai.github.io/Live-MT-MX-Converter/` once Pages is enabled and a deployment succeeds.

## Source of truth

- `app/engine/__init__.py`: supported directional conversion pairs and orchestration.
- `app/engine/mx_to_mt.py`: ISO 20022 XML to MT field mapping.
- `app/engine/mt_to_mx.py`: MT to ISO 20022 XML field mapping.
- `app/engine/io.py`: MT/XML readers and writers and dropped-field tracking.
- `app/formats.py`: supported profiles, field information and `MESSAGE_VERSIONS`.
- `app/checks.py`: deterministic input/output validation and value-fidelity checks.
- `app/mappings.py`: pair-specific output checks.
- `docs/bridge.py`: marshals browser actions into the existing engine and returns a JSON-safe report.
- `docs/app.js`: browser UI, Pyodide bootstrapping and safe report rendering only; it does not duplicate the mapping rules.

When adding a Python module imported by `app/`, also add its path to the `FILES` list in `docs/app.js` so the browser loader copies it into the Pyodide filesystem.

## Adding a new conversion pair

1. Confirm the intended business-equivalent message pair; don't assume similarly named messages are interchangeable.
2. Add deterministic mapping functions for the new direction in the appropriate engine module.
3. Register the exact `(source, destination)` pair in `TRANSLATORS`.
4. Add `SPLIT_ON` behavior only when one source message must become multiple target messages.
5. Add pair-specific checks for critical mapping invariants.
6. Add synthetic fixtures and tests for normal, invalid, missing-field and data-loss cases.
7. Update the supported-pairs table and README after tests pass.

No separate dropdown list is maintained. The browser asks the Python engine for its registered source/target pairs.

## Supporting a new ISO 20022 version

`MESSAGE_VERSIONS` centralizes configured message-version identifiers. A version change can alter required fields, cardinality, ordering or semantics; enabling a new version is not just a string change.

1. Review the relevant locally obtained official schema/specification and usage guideline.
2. Compare the old and new structures and identify mapping impacts.
3. Update `MESSAGE_VERSIONS` and mapping rules only as required.
4. Add a synthetic fixture and regression tests against expected output.
5. Add a local XSD only after checking redistribution terms; no XSD is fetched at runtime.
6. Release the updated profile with supported versions and limitations clearly stated.

The hosted page currently loads Pyodide and `lxml` static runtime assets from the pinned jsDelivr CDN. It does not send message content to that CDN and does not call a conversion API. A no-third-party-CDN build would need those runtime assets to be vendored and served from the repository's Pages origin.
