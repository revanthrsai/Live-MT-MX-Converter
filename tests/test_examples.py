"""Regression checks ensuring every selectable source has a working sample."""
from pathlib import Path

import pytest

from app import checks, engine

ROOT = Path(__file__).resolve().parents[1]

SOURCE_SAMPLES = [
    ("pacs.008", "MT103", "pacs.008.xml"),
    ("pacs.004", "MT103 RETN", "pacs.004.xml"),
    ("pacs.002", "MT199", "pacs.002.xml"),
    ("pain.001", "MT101", "pain.001.xml"),
    ("pain.002", "MT199", "pain.002.xml"),
    ("pain.008", "MT104", "pain.008.xml"),
    ("camt.053", "MT940", "camt.053.xml"),
    ("camt.054", "MT900 / MT910", "camt.054.xml"),
    ("camt.056", "MT192", "camt.056.xml"),
    ("MT103", "pacs.008", "MT103.txt"),
    ("MT103 RETN", "pacs.004", "MT103-RETN.txt"),
    ("MT101", "pain.001", "MT101.txt"),
    ("MT104", "pain.008", "MT104.txt"),
    ("MT940", "camt.053", "MT940.txt"),
    ("MT900 / MT910", "camt.054", "MT910.txt"),
    ("MT192", "camt.056", "MT192.txt"),
]


@pytest.mark.parametrize("source,target,filename", SOURCE_SAMPLES)
def test_source_sample_is_detected_validated_and_translatable(source, target, filename):
    sample_path = ROOT / "examples" / filename
    assert sample_path.is_file(), f"Missing sample file for {source}: {filename}"

    message = sample_path.read_text(encoding="utf-8")
    assert message.strip(), f"Sample file is empty for {source}: {filename}"

    detected = checks.detect(message)
    assert detected.get("code") == source

    errors = [
        finding for finding in checks.validate(message).get("findings", [])
        if finding.get("severity") == "error"
    ]
    assert not errors, f"Blocking validation findings for {source}: {errors}"

    result = engine.translate(message, source, target)
    assert result.message.strip(), f"Engine produced an empty result for {source} → {target}"


def test_example_manifest_or_catalog_covers_all_supported_sources():
    """Keep a human-readable catalog and check every registered source is documented."""
    catalog = (ROOT / "examples" / "README.md").read_text(encoding="utf-8")
    for source, _target, _filename in SOURCE_SAMPLES:
        assert f"`{source}`" in catalog
