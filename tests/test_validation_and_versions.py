from pathlib import Path

from app import checks, engine, formats
from server import PAIR_MAP, selected_source_findings


SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def sample(name: str) -> str:
    import json
    item = json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))
    return item.get("xml") or item.get("message") or ""


def test_registry_is_the_ui_source_of_truth():
    assert len(engine.TRANSLATORS) == 16
    assert PAIR_MAP["pacs.008"] == ["MT103"]
    assert PAIR_MAP["pacs.002"] == ["MT199"]
    assert "MT202" not in PAIR_MAP.get("pacs.009", [])
    assert "MT199" not in PAIR_MAP


def test_invalid_iban_in_mx_is_reported_before_translation():
    xml = sample("pacs.008")
    good = "AE070331234567890123456"
    assert good in xml
    bad = xml.replace(good, "not-an-iban")
    _result, findings = selected_source_findings("pacs.008", bad)
    assert any(f["rule"] == "IBAN" and "not in IBAN format" in f["message"] for f in findings)


def test_mismatched_source_selection_is_flagged():
    message = sample("MT103")
    _result, findings = selected_source_findings("MT101", message)
    assert any(f["rule"] == "Source format mismatch" for f in findings)


def test_newer_unconfigured_mx_version_is_blocked_by_local_policy():
    xml = sample("pacs.008").replace("pacs.008.001.08", "pacs.008.001.99")
    _result, findings = selected_source_findings("pacs.008", xml)
    assert any(f["rule"] == "Unsupported message version" for f in findings)


def test_registered_sources_and_targets_are_known_profiles():
    for source, target in engine.TRANSLATORS:
        assert source in formats.FORMATS
        assert target in formats.FORMATS
        assert formats.FORMATS[target]["std"] in ("MT", "MX")


def test_plain_string_in_iban_element_fails_iban_check():
    xml = sample("pacs.008")
    xml = xml.replace("<IBAN>AE070331234567890123456</IBAN>", "<IBAN>ordinary-string</IBAN>")
    findings = checks.validate(xml)["findings"]
    assert any(f["rule"] == "IBAN" and "not in IBAN format" in f["message"] for f in findings)
