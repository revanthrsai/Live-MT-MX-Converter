"""Small browser bridge around the existing deterministic Python engine.

This file runs inside Pyodide in the user's browser. It does not perform any
network requests; it only calls the checked-in app package.
"""
from __future__ import annotations

import json
from app import checks, engine, formats, mappings

MAX_MESSAGE_CHARS = 1_000_000


def _pair_map():
    pairs = {}
    for source, target in engine.TRANSLATORS:
        pairs.setdefault(source, []).append(target)
    return pairs


def get_metadata_json():
    pairs = _pair_map()
    sources = []
    for code, profile in formats.FORMATS.items():
        if code in pairs:
            sources.append({
                "value": code,
                "label": f"{code} — {profile.get('name', code)}",
                "name": profile.get("name", code),
                "std": profile.get("std", ""),
                "version": profile.get("version", ""),
            })
    return json.dumps({"pairs": pairs, "sources": sources}, separators=(",", ":"))


def _input_findings(source_format, message):
    detected = checks.detect(message)
    validation = checks.validate(message)
    findings = list(validation.get("findings", []))

    if not (message or "").strip():
        findings.append({
            "severity": "error", "rule": "Missing input", "where": "Source message", "value": "",
            "message": "Paste a message before checking or translating it.",
        })

    if detected.get("code") and detected["code"] != source_format:
        findings.append({
            "severity": "error", "rule": "Source format mismatch", "where": "Source message",
            "value": detected["code"],
            "message": f"The selected source is {source_format}, but the message looks like {detected['code']}. Select the actual source format.",
        })

    profile = formats.FORMATS.get(source_format, {})
    expected_version = profile.get("version")
    if (detected.get("std") == "MX" and detected.get("code") == source_format
            and detected.get("version") and expected_version
            and detected["version"] != expected_version):
        findings.append({
            "severity": "error", "rule": "Unsupported message version", "where": "XML namespace",
            "value": detected["version"],
            "message": (f"This release is configured and tested for {expected_version}. The input uses "
                        f"{detected['version']}. No version or schema is downloaded automatically; "
                        "add and test that version before translating it."),
        })
    return validation, findings


def process_payload_json(payload_json):
    """Validate or translate one payload and return a JSON-safe report."""
    try:
        payload = json.loads(payload_json)
        action = payload.get("action", "validate")
        source_format = str(payload.get("source", ""))
        target_format = str(payload.get("target", ""))
        message = str(payload.get("message", ""))

        if len(message) > MAX_MESSAGE_CHARS:
            return json.dumps({
                "title": "Input too large", "sourceFindings": [{
                    "severity": "error", "rule": "Message size", "where": "Source message",
                    "value": str(len(message)), "message": "The maximum message size is 1,000,000 characters.",
                }], "outputFindings": None, "outputMessage": "", "notes": [], "filled": [],
                "dropped": [], "fidelity": {}, "extra": "", "action": action,
            })

        _validation, source_findings = _input_findings(source_format, message)
        if action != "convert":
            return json.dumps({
                "title": "Input validation", "sourceFindings": source_findings,
                "outputFindings": None, "outputMessage": "", "notes": [], "filled": [],
                "dropped": [], "fidelity": {}, "extra": "", "action": action,
            }, ensure_ascii=False)

        if not engine.supports(source_format, target_format):
            source_findings.append({
                "severity": "error", "rule": "Unsupported conversion pair", "where": "Destination format",
                "value": f"{source_format} → {target_format}",
                "message": "This source/destination pair is not registered in the deterministic conversion engine.",
            })
            return json.dumps({
                "title": "Translation stopped", "sourceFindings": source_findings,
                "outputFindings": None, "outputMessage": "", "notes": [], "filled": [],
                "dropped": [], "fidelity": {}, "extra": "", "action": action,
            }, ensure_ascii=False)

        if any(f.get("severity") == "error" for f in source_findings):
            return json.dumps({
                "title": "Translation stopped — fix source errors first", "sourceFindings": source_findings,
                "outputFindings": None, "outputMessage": "", "notes": [], "filled": [],
                "dropped": [], "fidelity": {}, "extra": "", "action": action,
            }, ensure_ascii=False)

        try:
            result = engine.translate(message, source_format, target_format)
        except engine.Decline as exc:
            source_findings.append({
                "severity": "error", "rule": "Mapping engine declined", "where": "Conversion rules",
                "value": "", "message": str(exc),
            })
            return json.dumps({
                "title": "Translation stopped", "sourceFindings": source_findings,
                "outputFindings": None, "outputMessage": "", "notes": [], "filled": [],
                "dropped": [], "fidelity": {}, "extra": "", "action": action,
            }, ensure_ascii=False)

        output_validation = checks.validate(result.message)
        output_findings = list(output_validation.get("findings", []))
        output_findings.extend(mappings.pair_findings(source_format, target_format, message, result.message))
        declared_values = [item.get("value", "") for item in result.filled]
        fidelity = checks.compare_values(message, result.message, declared=declared_values)

        if not fidelity.get("ok"):
            examples = ", ".join(f"{x.get('kind')}: {x.get('value')}" for x in fidelity.get("invented", [])[:3])
            output_findings.append({
                "severity": "error", "rule": "Value fidelity", "where": "Source → destination comparison",
                "value": examples,
                "message": "The output contains money-critical values not accounted for by the source or declared generated fields. Review before using the output.",
            })
        if fidelity.get("dropped"):
            output_findings.append({
                "severity": "warning", "rule": "Values not carried over", "where": "Source → destination comparison",
                "value": ", ".join(x.get("value", "") for x in fidelity["dropped"][:3]),
                "message": (f"{len(fidelity['dropped'])} money-critical source value(s) were not found in the output. "
                            "Inspect the fidelity details and the mapping's dropped-field list."),
            })

        output_errors = any(f.get("severity") == "error" for f in output_findings)
        if output_errors:
            extra = "Output generated for inspection only. One or more code checks failed. Do not use this message until the findings are understood."
        elif any(f.get("severity") == "warning" for f in output_findings) or result.dropped:
            extra = "Review before use. The mapping reports warnings or explicitly dropped data. A syntactically generated message is not automatically lossless or production-ready."
        else:
            extra = "Code checks passed. Still review the conversion notes and dropped-field report before using the message in any real workflow."

        return json.dumps({
            "title": "Translation report", "sourceFindings": source_findings,
            "outputFindings": output_findings, "outputMessage": result.message,
            "notes": result.notes, "filled": result.filled, "dropped": result.dropped,
            "fidelity": fidelity, "extra": extra, "action": action,
        }, ensure_ascii=False, default=str)
    except Exception as exc:  # Surface unexpected failures as a local, readable report.
        return json.dumps({
            "title": "Local engine error", "sourceFindings": [{
                "severity": "error", "rule": "Engine exception", "where": "Browser runtime",
                "value": type(exc).__name__,
                "message": "The local conversion engine hit an unexpected error. Please check the message and try again. Technical detail: " + str(exc)[:400],
            }], "outputFindings": None, "outputMessage": "", "notes": [], "filled": [],
            "dropped": [], "fidelity": {}, "extra": "", "action": "error",
        }, ensure_ascii=False)
