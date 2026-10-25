"""The rules engine: every pair on the site's samples, round trips, edge cases, and safe repairs."""
import json
from pathlib import Path

import pytest

from app import checks, engine, formats, mappings

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
FILES = {"pacs.008": "pacs.008", "pacs.004": "pacs.004", "pain.001": "pain.001", "pain.008": "pain.008",
         "camt.053": "camt.053", "camt.054": "camt.054", "camt.056": "camt.056", "pacs.002": "pacs.002",
         "pain.002": "pain.002", "MT103": "MT103", "MT103 RETN": "MT103-RETN", "MT101": "MT101", "MT104": "MT104",
         "MT940": "MT940", "MT900 / MT910": "MT910", "MT192": "MT192"}


def sample(name):
    j = json.loads((SAMPLES / f"{name}.json").read_text())
    return j.get("xml") or j.get("message")


def run(src, text):
    tgt = formats.FORMATS[src]["equivalent"]
    out = engine.translate(text, src, tgt)
    v = checks.validate(out.message)
    errors = [f for f in v["findings"] if f["severity"] == "error"] + mappings.pair_findings(src, tgt, text, out.message)
    fid = checks.compare_values(text, out.message, declared=[f["value"] for f in out.filled])
    return out, errors, fid


@pytest.mark.skipif(not SAMPLES.exists(), reason="samples folder not next to ai-api")
@pytest.mark.parametrize("src", list(FILES))
def test_every_pair_passes_every_check(src):
    out, errors, fid = run(src, sample(FILES[src]))
    assert errors == [], errors
    assert fid["ok"], fid["invented"]
    assert checks.detect(out.message)["code"] == formats.FORMATS[src]["equivalent"]


@pytest.mark.skipif(not SAMPLES.exists(), reason="samples folder not next to ai-api")
def test_round_trip_keeps_the_money_values():
    mx = sample("pacs.008")
    mt = engine.translate(mx, "pacs.008", "MT103").message
    back = engine.translate(mt, "MT103", "pacs.008").message
    a, b = checks.extract_values(mx), checks.extract_values(back)
    for k in ("amounts", "bics", "accounts"):
        assert a[k] == b[k], k
    assert "eb6305c9-1f7c-4a9b-9b1e-2c2f4e7a91d4" in b["refs"]


def test_mt103_options_f_and_a():
    mt = """{1:F01TESTAEADAXXX0000000000}{2:I103DEMOINBBXXXXN}{4:
:20:REF1
:23B:CRED
:32A:260627EUR1000,
:50F:/DE89370400440532013000
1/ACME TRADING GMBH
2/HAUPTSTRASSE 1
3/DE/BERLIN
:57A:DEMOINBB
:59A:/1234567890123456
DEMOINBBXXX
:71A:OUR
-}"""
    out, errors, fid = run("MT103", mt)
    assert errors == [] and fid["ok"]
    x = out.message
    assert "<Nm>ACME TRADING GMBH</Nm>" in x and "<Ctry>DE</Ctry>" in x and "<TwnNm>BERLIN</TwnNm>" in x
    assert "<IBAN>DE89370400440532013000</IBAN>" in x and "<AnyBIC>DEMOINBBXXX</AnyBIC>" in x
    assert '<IntrBkSttlmAmt Ccy="EUR">1000.00</IntrBkSttlmAmt>' in x and "<ChrgBr>DEBT</ChrgBr>" in x
    assert any(f["field"] == "PmtId/UETR" for f in out.filled)  # no {121:} in the source, so one was generated
    assert any(f["field"] == "PmtId/EndToEndId" for f in out.filled)


def test_long_remittance_is_cut_and_reported():
    mx = sample("pacs.008").replace("Invoice 0042 - June freelance", "word " * 40) if SAMPLES.exists() else None
    if mx is None:
        pytest.skip("no samples")
    out, errors, _ = run("pacs.008", mx)
    assert errors == []
    f70 = [v for t, v in checks.mt_fields(out.message) if t == "70"][0].split("\n")
    assert len(f70) == 4 and all(len(l) <= 35 for l in f70)
    assert any("RmtInf" in d["field"] for d in out.dropped)


def _double(xml, tag, a="BOB-INV0042", b="BOB-INV0043"):
    i, j = xml.index(f"<{tag}>"), xml.index(f"</{tag}>") + len(f"</{tag}>")
    one = xml[i:j]
    return xml.replace(one, one + one.replace(a, b).replace("400.00", "250.00"))


@pytest.mark.skipif(not SAMPLES.exists(), reason="samples folder not next to ai-api")
@pytest.mark.parametrize("src,tag,mt", [("pacs.008", "CdtTrfTxInf", "{2:I103"), ("pain.001", "PmtInf", "{2:I101"),
                                        ("camt.054", "Ntry", ":32A:"), ("camt.056", "TxInf", "{2:I192")])
def test_several_items_become_one_mt_each(src, tag, mt):
    two = _double(sample(FILES[src]), tag)
    if src == "pacs.008":
        two = two.replace("<NbOfTxs>1</NbOfTxs>", "<NbOfTxs>2</NbOfTxs>")
    out = engine.translate(two, src, formats.FORMATS[src]["equivalent"])
    assert len(out.parts) == 2 and out.message.count(mt) == 2, out.message
    assert "2 " in out.notes[0]
    for piece, msg in out.parts:  # each MT is right for its own piece of the source
        assert mappings.pair_findings(src, formats.FORMATS[src]["equivalent"], piece, msg) == []
        assert checks.validate(msg)["valid"]
    v = checks.validate(out.message)
    assert v["valid"], v["findings"]
    fid = checks.compare_values(two, out.message, declared=[f["value"] for f in out.filled])
    assert fid["ok"] and not [d for d in fid["dropped"] if d["kind"] == "amount"], fid


@pytest.mark.skipif(not SAMPLES.exists(), reason="samples folder not next to ai-api")
def test_mt101_with_two_transactions():
    mt = sample("MT101").replace(":71A:SHA\n-}", ":71A:SHA\n:21:BOB-INV0043\n:32B:USD50,25\n:57A:DEMOINBB\n:59:/1234567890123456\nPayee Example\n:71A:OUR\n-}")
    out, errors, fid = run("MT101", mt)
    assert errors == [] and fid["ok"]
    assert out.message.count("<CdtTrfTxInf>") == 2 and "<CtrlSum>450.25</CtrlSum>" in out.message


def test_garbage_declines():
    with pytest.raises(engine.Decline):
        engine.translate("<Document><broken", "pacs.008", "MT103")
    with pytest.raises(engine.Decline):
        engine.translate(":20:X\n:23B:CRED", "MT103", "pacs.008")
