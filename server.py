"""Local-only web runner for Live MT-MX Converter.

This is a standard-library HTTP server used only to serve the local HTML form
and run the Python mapping engine in the same local process. It binds to
127.0.0.1 and makes no outbound network requests.
"""
from __future__ import annotations

import html
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote

from app import checks, engine, formats, mappings

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
EXAMPLES_DIR = ROOT / "examples"
MAX_MESSAGE_CHARS = 1_000_000
MAX_BODY_BYTES = 2_200_000
HOST = "127.0.0.1"
DEFAULT_PORT = 8765

SUPPORTED_PAIRS = list(engine.TRANSLATORS.keys())
PAIR_MAP: dict[str, list[str]] = {}
for source, target in SUPPORTED_PAIRS:
    PAIR_MAP.setdefault(source, []).append(target)

SUPPORTED_SOURCES = [name for name in formats.FORMATS if name in PAIR_MAP]


def e(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _findings_section(title: str, findings: list[dict]) -> str:
    errors = sum(1 for f in findings if f.get("severity") == "error")
    warnings = sum(1 for f in findings if f.get("severity") == "warning")
    if errors:
        chip_class, chip_label = "error", f"{errors} error{'s' if errors != 1 else ''}"
    elif warnings:
        chip_class, chip_label = "warning", f"{warnings} warning{'s' if warnings != 1 else ''}"
    else:
        chip_class, chip_label = "success", "No issues found"

    if not findings:
        body = '<p class="empty-note">None of the configured code checks found issues.</p>'
    else:
        cards = []
        for finding in findings:
            severity = finding.get("severity", "error")
            severity_label = "Warning" if severity == "warning" else "Error"
            rule = e(finding.get("rule", "Check"))
            message = e(finding.get("message", "A check failed."))
            where = e(finding.get("where", ""))
            value = e(finding.get("value", ""))
            value_html = f'<p><strong>Value:</strong> {value}</p>' if value else ""
            where_html = f'<p class="finding-where">{where}</p>' if where else ""
            cards.append(
                f'<article class="finding {e(severity)}">'
                f'<strong>{severity_label} · {rule}</strong>'
                f'<p>{message}</p>{value_html}{where_html}</article>'
            )
        body = '<div class="finding-list">' + "".join(cards) + "</div>"

    return (
        '<div class="report-section">'
        f'<div class="result-heading"><h3>{e(title)}</h3>'
        f'<span class="status-chip {chip_class}">{e(chip_label)}</span></div>'
        f'{body}</div>'
    )


def _render_entries(title: str, entries: list[dict], empty_label: str) -> str:
    if not entries:
        return ""
    rows = []
    for entry in entries[:100]:
        field = e(entry.get("field", "Field"))
        value = e(entry.get("value", ""))
        reason = e(entry.get("reason", ""))
        rows.append(f'<li><strong>{field}</strong>: {value}' + (f' <span>— {reason}</span>' if reason else "") + "</li>")
    more = f"<li>And {len(entries) - 100} more…</li>" if len(entries) > 100 else ""
    return (
        '<details class="report-box"><summary>' + e(title) + f' ({len(entries)})</summary>'
        '<ul class="notes-list">' + "".join(rows) + more + "</ul></details>"
    )


def _render_output(output: str, source: str, target: str, notes: list[str], filled: list[dict], dropped: list[dict], fidelity: dict) -> str:
    if not output:
        return ""
    note_html = ""
    if notes:
        note_html = '<div class="report-box"><strong>Engine notes</strong><ul class="notes-list">' + "".join(
            f"<li>{e(note)}</li>" for note in notes
        ) + "</ul></div>"
    fidelity_html = (
        '<div class="output-meta">'
        f'<span class="meta-pill">Value fidelity: {"passed" if fidelity.get("ok") else "review"}</span>'
        f'<span class="meta-pill">{len(filled)} generated / filled values</span>'
        f'<span class="meta-pill">{len(dropped)} explicitly dropped fields</span>'
        '</div>'
    )
    invented = fidelity.get("invented", [])
    if invented:
        fidelity_html += '<div class="report-box error"><strong>Unexpected output values detected</strong><ul class="notes-list">' + "".join(
            f"<li>{e(item.get('kind'))}: {e(item.get('value'))}</li>" for item in invented[:20]
        ) + "</ul></div>"
    lost = fidelity.get("dropped", [])
    if lost:
        fidelity_html += '<div class="report-box warning"><strong>Source values not found in output</strong><ul class="notes-list">' + "".join(
            f"<li>{e(item.get('kind'))}: {e(item.get('value'))}</li>" for item in lost[:20]
        ) + "</ul></div>"
    return (
        '<section class="report-section output-section" id="outputPanel">'
        '<div class="output-header"><h4>Generated destination message</h4>'
        '<div class="output-actions">'
        '<button class="small-button" type="button" id="copyOutput">Copy output</button>'
        '<button class="small-button" type="button" id="downloadOutput">Download</button>'
        '</div></div>'
        f'<textarea class="output-textarea" id="outputMessage" readonly spellcheck="false" aria-label="Generated destination message">{e(output)}</textarea>'
        f'{fidelity_html}{note_html}'
        + _render_entries("Generated or filled fields", filled, "No fields were generated")
        + _render_entries("Fields explicitly dropped by mapping rules", dropped, "No fields were dropped")
        + '</section>'
    )


def render_page(
    source: str = "pacs.008",
    target: str = "MT103",
    message: str = "",
    report_html: str = "",
    output: str = "",
    notes: list[str] | None = None,
    filled: list[dict] | None = None,
    dropped: list[dict] | None = None,
    fidelity: dict | None = None,
) -> bytes:
    template = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    source_options = []
    for code in SUPPORTED_SOURCES:
        profile = formats.FORMATS[code]
        label = f"{code} — {profile.get('name', code)}"
        selected = " selected" if code == source else ""
        source_options.append(f'<option value="{e(code)}"{selected}>{e(label)}</option>')
    pairs_json = json.dumps(PAIR_MAP, ensure_ascii=False, separators=(",", ":"))
    template = template.replace("__PAIR_MAP__", e(pairs_json))
    template = template.replace("__SELECTED_TARGET__", e(target))
    template = template.replace("<!-- SOURCE_OPTIONS -->", "\n              ".join(source_options))
    template = template.replace("__MESSAGE_VALUE__", e(message))
    # The output panel is generated only after translation; all dynamic data is escaped.
    panel = _render_output(output, source, target, notes or [], filled or [], dropped or [], fidelity or {}) if output else ""
    template = template.replace("<!-- RESULT_PANEL -->", report_html + panel)
    return template.encode("utf-8")


def selected_source_findings(source: str, message: str) -> tuple[dict, list[dict]]:
    detected = checks.detect(message)
    result = checks.validate(message)
    findings = list(result.get("findings", []))
    if not (message or "").strip():
        findings.append({
            "severity": "error", "rule": "Missing input", "where": "Source message", "value": "",
            "message": "Paste a message before checking or translating it.",
        })
    if detected.get("code") and detected["code"] != source:
        findings.append({
            "severity": "error", "rule": "Source format mismatch", "where": "Source message",
            "value": detected["code"],
            "message": f"The selected source is {source}, but the message looks like {detected['code']}. Select the actual source format.",
        })
    profile = formats.FORMATS.get(source, {})
    expected_version = profile.get("version")
    if detected.get("std") == "MX" and detected.get("code") == source and detected.get("version") and expected_version:
        if detected["version"] != expected_version:
            findings.append({
                "severity": "error", "rule": "Unsupported message version", "where": "XML namespace",
                "value": detected["version"],
                "message": f"This release is configured and tested for {expected_version}. The input uses {detected['version']}. No version or schema is downloaded automatically; add and test that version before translating it.",
            })
    return result, findings


def report_for(action_title: str, input_findings: list[dict], output_findings: list[dict] | None = None, extra: str = "") -> str:
    all_findings = list(input_findings) + list(output_findings or [])
    errors = sum(1 for f in all_findings if f.get("severity") == "error")
    warnings = sum(1 for f in all_findings if f.get("severity") == "warning")
    if errors:
        state, state_class = "Review required", "error"
    elif warnings:
        state, state_class = "Passed with warnings", "warning"
    else:
        state, state_class = "Passed code checks", "success"
    sections = [
        '<section class="result-panel" id="resultPanel">'
        '<div class="result-heading"><div><p class="eyebrow">CHECK REPORT</p>'
        f'<h3>{e(action_title)}</h3></div>'
        f'<span class="status-chip {state_class}">{e(state)}</span></div>'
    ]
    sections.append(_findings_section("Source message checks", input_findings))
    if output_findings is not None:
        sections.append(_findings_section("Destination message checks", output_findings))
    if extra:
        sections.append(f'<div class="report-box">{extra}</div>')
    sections.append("</section>")
    return "".join(sections)


class ConverterHandler(BaseHTTPRequestHandler):
    server_version = "LiveMTMXLocal/0.1"

    def log_message(self, _format: str, *args) -> None:
        # Intentionally suppress request logging so pasted message contents are never logged.
        return

    def _send(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'none'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(self.path.split("?", 1)[0])
        if path in ("/", "/index.html"):
            self._send(200, render_page())
            return
        if path in ("/styles.css", "/app.js"):
            file_path = WEB_DIR / path.lstrip("/")
            if not file_path.is_file():
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            mime = "text/css; charset=utf-8" if path.endswith(".css") else "text/javascript; charset=utf-8"
            self._send(200, file_path.read_bytes(), mime)
            return
        if path.startswith("/examples/"):
            name = path.rsplit("/", 1)[-1]
            candidate = (EXAMPLES_DIR / name).resolve()
            if candidate.parent != EXAMPLES_DIR.resolve() or not candidate.is_file():
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            mime = "application/xml; charset=utf-8" if candidate.suffix == ".xml" else "text/plain; charset=utf-8"
            self._send(200, candidate.read_bytes(), mime)
            return
        self._send(404, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/":
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        # Reject browser cross-site form submissions to this local-only tool.
        # Direct form submissions without an Origin header remain supported.
        origin = self.headers.get("Origin")
        port = self.server.server_port
        allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        if origin and origin not in allowed_origins:
            self._send(403, b"Cross-origin form submissions are not accepted.", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            report = report_for("Input not processed", [{
                "severity": "error", "rule": "Input size", "where": "Request",
                "value": str(length), "message": "The submitted form is empty or too large. The maximum message size is 1,000,000 characters.",
            }])
            self._send(413 if length > MAX_BODY_BYTES else 400, render_page(report_html=report))
            return
        raw = self.rfile.read(length)
        try:
            form = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=20)
        except (UnicodeDecodeError, ValueError):
            report = report_for("Input not processed", [{
                "severity": "error", "rule": "Form data", "where": "Request", "value": "",
                "message": "The form could not be read as UTF-8. Please paste the message again.",
            }])
            self._send(400, render_page(report_html=report))
            return

        action = form.get("action", ["validate"])[0]
        source = form.get("source", [SUPPORTED_SOURCES[0]])[0]
        target = form.get("target", [""])[0]
        message = form.get("message", [""])[0]
        if len(message) > MAX_MESSAGE_CHARS:
            report = report_for("Input too large", [{
                "severity": "error", "rule": "Message size", "where": "Source message",
                "value": str(len(message)), "message": "The maximum message size is 1,000,000 characters.",
            }])
            self._send(413, render_page(source, target, message[:MAX_MESSAGE_CHARS], report))
            return

        _validation, input_findings = selected_source_findings(source, message)
        has_input_errors = any(f.get("severity") == "error" for f in input_findings)

        if action != "convert":
            report = report_for("Input validation", input_findings)
            self._send(200, render_page(source, target, message, report))
            return

        if not engine.supports(source, target):
            pair_error = {
                "severity": "error", "rule": "Unsupported conversion pair", "where": "Destination format",
                "value": f"{source} → {target}",
                "message": "This source/destination pair is not registered in the deterministic conversion engine.",
            }
            report = report_for("Translation stopped", input_findings + [pair_error])
            self._send(200, render_page(source, target, message, report))
            return

        if has_input_errors:
            report = report_for("Translation stopped — fix source errors first", input_findings)
            self._send(200, render_page(source, target, message, report))
            return

        try:
            result = engine.translate(message, source, target)
        except engine.Decline as exc:
            decline = {
                "severity": "error", "rule": "Mapping engine declined", "where": "Conversion rules",
                "value": "", "message": str(exc),
            }
            report = report_for("Translation stopped", input_findings + [decline])
            self._send(200, render_page(source, target, message, report))
            return

        output_validation = checks.validate(result.message)
        output_findings = list(output_validation.get("findings", []))
        output_findings.extend(mappings.pair_findings(source, target, message, result.message))
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
                "message": f"{len(fidelity['dropped'])} money-critical source value(s) were not found in the output. Inspect the fidelity details and the mapping's dropped-field list.",
            })

        output_errors = any(f.get("severity") == "error" for f in output_findings)
        extra = ""
        if output_errors:
            extra = '<strong>Output generated for inspection only.</strong> One or more code checks failed. Do not use this message until the findings are understood.'
        elif any(f.get("severity") == "warning" for f in output_findings) or result.dropped:
            extra = '<strong>Review before use.</strong> The mapping reports warnings or explicitly dropped data. A syntactically generated message is not automatically lossless or production-ready.'
        else:
            extra = '<strong>Code checks passed.</strong> Still review the conversion notes and dropped-field report before using the message in any real workflow.'
        report = report_for("Translation report", input_findings, output_findings, extra)
        self._send(200, render_page(source, target, message, report, result.message, result.notes, result.filled, result.dropped, fidelity))


def main() -> int:
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
            if not (1024 <= port <= 65535):
                raise ValueError
        except ValueError:
            print(f"Usage: python run.py [port between 1024 and 65535]", file=sys.stderr)
            return 2
    server = ThreadingHTTPServer((HOST, port), ConverterHandler)
    print("Live MT-MX Converter is running locally.")
    print(f"Open http://{HOST}:{port} in your browser.")
    print("No source message content is logged. Stop with Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping local converter.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
