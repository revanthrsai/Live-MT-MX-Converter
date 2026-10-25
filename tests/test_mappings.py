from app import mappings
from tests.test_checks import MT103, PACS008

GOOD = MT103.replace(":20:TESTAEAD-INSTR\n", ":20:TESTAEAD-INSTR-0\n").replace(":70:Invoice 0042 - June freelance", ":70:/ROC/BOB-INV0042\nInvoice 0042 - June freelance")


def test_good_mt103_passes_rules():
    assert mappings.pair_findings("pacs.008", "MT103", PACS008, GOOD) == []


def test_wrong_field_20_and_missing_roc_are_caught():
    bad = MT103.replace(":20:TESTAEAD-INSTR\n", ":20:BOB-INV0042\n")
    rules = {f["rule"] for f in mappings.pair_findings("pacs.008", "MT103", PACS008, bad)}
    assert {"Field 20", "Field 70"} <= rules


def test_bad_header_and_lost_uetr_are_caught():
    bad = GOOD.replace("{1:F01TESTAEADAXXX0000000000}", "{1:F01TESTAEADXXX}").replace("{3:{121:eb6305c9-1f7c-4a9b-9b1e-2c2f4e7a91d4}}", "")
    rules = {f["rule"] for f in mappings.pair_findings("pacs.008", "MT103", PACS008, bad)}
    assert {"Block 1", "UETR"} <= rules


def test_missing_52a_is_caught():
    bad = GOOD.replace(":52A:TESTAEAD\n", "")
    assert "Field 52A" in {f["rule"] for f in mappings.pair_findings("pacs.008", "MT103", PACS008, bad)}


# ── every pair, against the site's own samples (the golden pairs) ────────────
import json
from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
PAIRS = [("pacs.008", "MT103", "pacs.008", "MT103"), ("pacs.004", "MT103 RETN", "pacs.004", "MT103-RETN"),
         ("pain.001", "MT101", "pain.001", "MT101"), ("pain.008", "MT104", "pain.008", "MT104"),
         ("camt.053", "MT940", "camt.053", "MT940"), ("camt.054", "MT900 / MT910", "camt.054", "MT910"),
         ("camt.056", "MT192", "camt.056", "MT192"), ("pacs.002", "MT199", "pacs.002", "MT199"),
         ("MT101", "pain.001", "MT101", "pain.001"), ("MT104", "pain.008", "MT104", "pain.008"),
         ("MT940", "camt.053", "MT940", "camt.053"), ("MT900 / MT910", "camt.054", "MT910", "camt.054")]


def _sample(name):
    j = json.loads((SAMPLES / f"{name}.json").read_text())
    return j.get("xml") or j.get("message")


needs_samples = pytest.mark.skipif(not (SAMPLES / "MT103.json").exists(), reason="site samples not present")


@needs_samples
@pytest.mark.parametrize("src,tgt,fs,ft", PAIRS)
def test_golden_pairs_pass_their_rules(src, tgt, fs, ft):
    assert mappings.pair_findings(src, tgt, _sample(fs), _sample(ft)) == []


@needs_samples
def test_rule_checks_catch_real_mistakes():
    mt940 = _sample("MT940").replace(":60F:C260627USD0,00", ":60F:C260627USD400,00")
    assert "Field 60F" in {f["rule"] for f in mappings.pair_findings("camt.053", "MT940", _sample("camt.053"), mt940)}
    mt900 = _sample("MT910").replace("{2:I910", "{2:I900")
    assert "Message type" in {f["rule"] for f in mappings.pair_findings("camt.054", "MT900 / MT910", _sample("camt.054"), mt900)}
    mt192 = _sample("MT192").replace(":21:TESTAEAD-INSTR-0", ":21:BOB-INV0042")
    assert "Field 21" in {f["rule"] for f in mappings.pair_findings("camt.056", "MT192", _sample("camt.056"), mt192)}
    retn = _sample("MT103-RETN").replace("/AC04/", "/AC01/")
    assert "Field 72" in {f["rule"] for f in mappings.pair_findings("pacs.004", "MT103 RETN", _sample("pacs.004"), retn)}
