from pathlib import Path

from app import checks

PACS008 = (Path(__file__).parent / "pacs008.xml").read_text()

MT103 = """{1:F01TESTAEADAXXX0000000000}{2:I103DEMOINBBXXXXN}{3:{121:eb6305c9-1f7c-4a9b-9b1e-2c2f4e7a91d4}}{4:
:20:TESTAEAD-INSTR
:23B:CRED
:32A:260627USD400,00
:50K:Payer Example
:52A:TESTAEAD
:57A:DEMOINBB
:59:Payee Example
:70:Invoice 0042 - June freelance
:71A:SHA
-}"""


def test_detect():
    assert checks.detect(PACS008) == {"code": "pacs.008", "std": "MX", "version": "pacs.008.001.08"}
    assert checks.detect(MT103)["code"] == "MT103"
    assert checks.detect(":20:X\n:28D:1/1\n:30:261012")["code"] == "MT101"
    assert checks.detect("hello")["std"] is None


def test_valid_messages_pass():
    assert checks.validate(PACS008)["valid"], checks.validate(PACS008)
    assert checks.validate(MT103)["valid"], checks.validate(MT103)


def test_mx_rules():
    bad = PACS008.replace("<IntrBkSttlmDt>2026-06-27", "<IntrBkSttlmDt>2026-13-10").replace("DEMOINBB</BICFI></FinInstnId></CdtrAgt>", "HDFCIN</BICFI></FinInstnId></CdtrAgt>")
    rules = {f["rule"] for f in checks.validate(bad)["findings"]}
    assert {"Date", "BIC"} <= rules
    jpy = PACS008.replace('Ccy="USD">400.00', 'Ccy="JPY">400.00')
    assert any(f["rule"] == "Amount precision" for f in checks.validate(jpy)["findings"])
    two = PACS008.replace("<NbOfTxs>1</NbOfTxs>", "<NbOfTxs>2</NbOfTxs><CtrlSum>40.00</CtrlSum>")
    rules = {f["rule"] for f in checks.validate(two)["findings"]}
    assert {"NbOfTxs", "CtrlSum"} <= rules


def test_iban():
    assert checks.iban_ok("DE89370400440532013000")[0]
    assert not checks.iban_ok("DE89370400440532013001")[0]


def test_mt_rules():
    rules = {f["rule"] for f in checks.validate(MT103.replace(":71A:SHA\n", ""))["findings"]}
    assert "Mandatory field" in rules
    rules = {f["rule"] for f in checks.validate(MT103.replace("400,00", "400.00"))["findings"]}
    assert "Field 32A" in rules


def test_malformed_xml_and_xxe_are_safe():
    assert not checks.validate("<Document><a></Document>")["valid"]
    xxe = '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]><Document xmlns="urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08"><Nm>&x;</Nm></Document>'
    v = checks.extract_values(xxe)
    assert "root:" not in str(v)


def test_values_carried_over_is_clean():
    r = checks.compare_values(PACS008, MT103)
    assert r["ok"], r
    assert not [d for d in r["dropped"] if d["kind"] in ("amount", "currency", "BIC")]


def test_invented_values_are_caught():
    r = checks.compare_values(PACS008, MT103.replace("400,00", "4000,00").replace(":57A:DEMOINBB", ":57A:OTHRUS33"))
    kinds = {(x["kind"], x["value"]) for x in r["invented"]}
    assert ("amount", "4000 USD") in kinds
    assert ("BIC", "OTHRUS33XXX") in kinds
    assert not r["ok"]


def test_declared_changes_are_not_flagged():
    fixed = PACS008.replace("<IntrBkSttlmDt>2026-06-27", "<IntrBkSttlmDt>2026-06-28")
    assert not checks.compare_values(PACS008, fixed)["ok"]
    assert checks.compare_values(PACS008, fixed, declared=["2026-06-28"])["ok"]


def test_invented_branch_in_header_is_caught():
    bad = MT103.replace("{1:F01TESTAEADAXXX", "{1:F01TESTAEADAAAA")
    r = checks.compare_values(PACS008, bad)
    assert {"kind": "BIC", "value": "TESTAEADAAA"} in r["invented"]
