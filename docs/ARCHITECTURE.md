# Architecture and update policy

## Local conversion path

1. The browser submits a regular HTML form to the local server.
2. The server checks the selected source against detected message type and the configured MX version profile.
3. The deterministic validator checks the source before the mapping engine is called.
4. The engine selects a function from the explicit `TRANSLATORS` registry. Unknown pairs are declined.
5. Output validation, pair-specific checks and value-fidelity comparison run after conversion.
6. The page displays the output alongside warnings, generated fields, dropped fields and notes.

The browser does not call a hosted service. The application has no outbound network code and binds only to `127.0.0.1`.

## Source of truth

- `app/engine/__init__.py`: supported directional conversion pairs and orchestration.
- `app/engine/mx_to_mt.py`: ISO 20022 XML to MT field mapping.
- `app/engine/mt_to_mx.py`: MT to ISO 20022 XML field mapping.
- `app/formats.py`: supported profiles, field information and `MESSAGE_VERSIONS`.
- `app/checks.py`: common deterministic validation and value-fidelity checks.
- `app/mappings.py`: pair-specific output checks.

The browser destination list is built directly from the engine's registered pairs when the local page is rendered. Avoid maintaining a second independent list in JavaScript.

## Adding a new conversion pair

1. Confirm the desired business-equivalent message pair; don't assume similarly named messages are interchangeable.
2. Add deterministic mapping functions for the new direction in the appropriate engine module.
3. Register the exact `(source, destination)` pair in `TRANSLATORS`.
4. Add `SPLIT_ON` behavior only when one source message must become multiple target messages.
5. Add pair-specific checks if the mapping has critical invariants.
6. Add synthetic sample fixtures and tests for normal, invalid, missing-field and data-loss cases.
7. Update the supported-pairs table and README after the tests pass.

## Supporting a new ISO 20022 version

`MESSAGE_VERSIONS` centralizes the configured message-version identifiers. A version change can still alter required fields, cardinality, ordering or semantics. Therefore, a new version must not be enabled by changing a string alone:

1. Review its locally obtained official schema/specification and applicable usage guidelines.
2. Compare the old and new structures and identify any mapping impact.
3. Update `MESSAGE_VERSIONS` and mapping rules only as required.
4. Add a fixture for the new version and regression tests against known-good expected output.
5. Add a local XSD only after checking redistribution terms; no XSD is fetched at runtime.
6. Release the updated profile with the supported versions stated clearly.

No automatic schema discovery, AI-assisted repair, auto-fix or external API integration is implemented in this first release.
