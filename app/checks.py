"""Deterministic validation and value-fidelity checks for MT and MX messages.

Checks include message detection, XML parsing, IBAN checksums, BIC shape,
dates, amount/currency formatting, mandatory MT fields and selected payment
message invariants. No network calls are made. XML entity resolution, DTD
loading and network access are disabled. Full XSD validation is only available
when a matching XSD has been supplied locally in the schemas directory.
"""
from __future__ import annotations

import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree

from .formats import FORMATS, MT_MANDATORY

SCHEMA_DIR = Path(os.environ.get("XSD_DIR", Path(__file__).resolve().parent.parent / "schemas"))

def _new_parser() -> etree.XMLParser:
    """Create an isolated secure parser for each document."""
    return etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False,
        huge_tree=False, remove_comments=True, remove_pis=True,
    )

BIC_RE = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
MT_FIELD_RE = re.compile(r"(?m)^:(\d{2}[A-Z]?):")

IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AT": 20, "BE": 16, "BG": 22, "BH": 22, "CH": 21, "CY": 28, "CZ": 24,
    "DE": 22, "DK": 18, "EE": 20, "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GR": 27, "HR": 21,
    "HU": 28, "IE": 22, "IS": 26, "IT": 27, "KW": 30, "LI": 21, "LT": 20, "LU": 20, "LV": 21,
    "MC": 27, "MT": 31, "NL": 18, "NO": 15, "PL": 28, "PT": 25, "QA": 29, "RO": 24, "SA": 24,
    "SE": 24, "SI": 19, "SK": 24, "SM": 27, "TR": 26,
}
CCY_DECIMALS = {
    "AED": 2, "AUD": 2, "BHD": 3, "CAD": 2, "CHF": 2, "CNY": 2, "CZK": 2, "DKK": 2, "EUR": 2,
    "GBP": 2, "HKD": 2, "HUF": 2, "IDR": 2, "ILS": 2, "INR": 2, "JOD": 3, "JPY": 0, "KRW": 0,
    "KWD": 3, "MXN": 2, "MYR": 2, "NOK": 2, "NZD": 2, "OMR": 3, "PHP": 2, "PLN": 2, "QAR": 2,
    "RON": 2, "SAR": 2, "SEK": 2, "SGD": 2, "THB": 2, "TND": 3, "TRY": 2, "USD": 2, "ZAR": 2,
}
MX_NS_RE = re.compile(r"urn:iso:std:iso:20022:tech:xsd:([a-z]{4}\.\d{3})\.(\d{3})\.(\d{2})")


# ── helpers ─────────────────────────────────────────────────────────────────
def local(tag) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def path_of(el) -> str:
    parts = []
    while el is not None and isinstance(el.tag, str):
        parts.append(local(el.tag))
        el = el.getparent()
    parts.reverse()
    if parts and parts[0] == "Document":
        parts = parts[1:]
    return " › ".join(parts)


def norm_amount(raw: str) -> str | None:
    s = (raw or "").strip().replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    q = d.normalize()
    out = format(q, "f")
    return out


def iban_ok(iban: str) -> tuple[bool, str]:
    s = re.sub(r"\s+", "", iban or "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", s):
        return False, "is not in IBAN format"
    want = IBAN_LENGTHS.get(s[:2])
    if want and want != len(s):
        return False, f"has {len(s)} characters; {s[:2]} IBANs have {want}"
    rearranged = s[4:] + s[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    if int(digits) % 97 != 1:
        return False, "fails the mod-97 checksum"
    return True, ""


def real_date(s: str) -> bool:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s or "")
    if not m:
        return False
    try:
        date(int(m[1]), int(m[2]), int(m[3]))
        return True
    except ValueError:
        return False


def yymmdd_to_iso(s: str) -> str | None:
    if not re.fullmatch(r"\d{6}", s or ""):
        return None
    iso = f"20{s[0:2]}-{s[2:4]}-{s[4:6]}"
    return iso if real_date(iso) else None


# ── detection ───────────────────────────────────────────────────────────────
def detect(text: str) -> dict:
    """Return {"code": "pacs.008" | "MT103" | None, "std": "MX" | "MT" | None, "version": str | None}."""
    t = (text or "").strip()
    if not t:
        return {"code": None, "std": None, "version": None}
    if t.startswith("<"):
        for m in MX_NS_RE.finditer(t):
            if not m.group(1).startswith("head."):
                return {"code": m.group(1), "std": "MX", "version": f"{m.group(1)}.{m.group(2)}.{m.group(3)}"}
        return {"code": None, "std": "MX", "version": None}
    retn = bool(re.search(r":72:\s*/RETN/", t))
    b2 = re.search(r"\{2:[IO](\d{3})", t)
    if b2:
        n = b2.group(1)
        if n == "103":
            return {"code": "MT103 RETN" if retn else "MT103", "std": "MT", "version": None}
        if n in ("900", "910"):
            return {"code": "MT900 / MT910", "std": "MT", "version": None}
        return {"code": "MT" + n, "std": "MT", "version": None}
    tags = set(MT_FIELD_RE.findall(t))
    has = tags.__contains__
    if retn and has("32A"):
        return {"code": "MT103 RETN", "std": "MT", "version": None}
    if has("28D"):
        return {"code": "MT101", "std": "MT", "version": None}
    if (has("60F") or has("60M")) and (has("62F") or has("62M")):
        return {"code": "MT940", "std": "MT", "version": None}
    if has("11S"):
        return {"code": "MT192", "std": "MT", "version": None}
    if has("19") and has("30") and has("32B"):
        return {"code": "MT104", "std": "MT", "version": None}
    if has("23B") or (has("32A") and (tags & {"50K", "50A", "50F"}) and (tags & {"59", "59A", "59F"})):
        return {"code": "MT103", "std": "MT", "version": None}
    if has("21") and has("25") and has("32A"):
        return {"code": "MT900 / MT910", "std": "MT", "version": None}
    if has("79") and not has("32A"):
        return {"code": "MT199", "std": "MT", "version": None}
    if tags:
        return {"code": None, "std": "MT", "version": None}
    return {"code": None, "std": None, "version": None}


# ── MT parsing ──────────────────────────────────────────────────────────────
def mt_fields(text: str) -> list[tuple[str, str]]:
    """[(tag, value)] from block 4 (or the whole text when there are no blocks)."""
    t = text or ""
    b4 = re.search(r"\{4:\s*(.*?)-\}", t, re.S)
    body = b4.group(1) if b4 else t
    out = []
    matches = list(MT_FIELD_RE.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out.append((m.group(1), body[m.end():end].strip("\r\n")))
    return out


# ── validation ──────────────────────────────────────────────────────────────
def _f(sev, rule, where, value, msg):
    return {"severity": sev, "rule": rule, "where": where, "value": value, "message": msg}


_MT_MSG_RE = re.compile(r"(?:\{1:[^}]*\}(?:\{2:[^}]*\})?(?:\{3:(?:\{[^}]*\})+\})?)?\{4:.*?-\}", re.S)


def split_mt(text: str) -> list[str]:
    """Several MT messages one after another (e.g. one MT103 per transaction) → one string each."""
    found = _MT_MSG_RE.findall(text or "")
    return found if len(found) > 1 else [text]


def validate(text: str) -> dict:
    """Validate an ISO 20022 (XML) or SWIFT MT message (or several MT messages in a row).

    Returns {"valid": bool, "std", "code", "findings": [ {severity: error|warning, rule, where, value, message} ]}.
    """
    parts = split_mt(text) if not (text or "").lstrip().startswith("<") else [text]
    if len(parts) > 1:
        results = [validate(p) for p in parts]
        findings = [{**f, "where": f"Message {i + 1} {f.get('where', '')}".strip()} for i, r in enumerate(results) for f in r["findings"]]
        return {"valid": all(r["valid"] for r in results), "std": "MT", "code": results[0]["code"], "findings": findings}
    det = detect(text)
    if det["std"] == "MX":
        findings = _validate_mx(text, det)
    elif det["std"] == "MT":
        findings = _validate_mt(text, det)
    else:
        findings = [_f("error", "Unrecognised", "", "", "This is neither ISO 20022 XML nor a SWIFT MT message.")]
    return {"valid": not any(x["severity"] == "error" for x in findings), "std": det["std"], "code": det["code"], "findings": findings}


def _parse_xml(text: str):
    try:
        return etree.fromstring(text.strip().encode("utf-8"), _new_parser()), None
    except etree.XMLSyntaxError as e:
        return None, str(e)


def _xsd_for(version: str | None):
    if not version or not SCHEMA_DIR.is_dir():
        return None
    p = SCHEMA_DIR / f"{version}.xsd"
    if not p.is_file():
        return None
    try:
        return etree.XMLSchema(etree.parse(str(p), etree.XMLParser(no_network=True, resolve_entities=False)))
    except Exception:
        return None


def _validate_mx(text, det):
    out = []
    root, err = _parse_xml(text)
    if root is None:
        return [_f("error", "Malformed XML", "", "", f"The XML doesn't parse: {err}")]
    if not det["code"]:
        out.append(_f("error", "Namespace", "Document", "", "The <Document> has no ISO 20022 namespace, so the message type can't be known."))
    schema = _xsd_for(det["version"])
    if schema is not None and not schema.validate(root.getroottree()):
        for e in list(schema.error_log)[:10]:
            out.append(_f("error", "Schema", f"line {e.line}", "", e.message))

    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        name = local(el.tag)
        val = (el.text or "").strip()
        where = path_of(el)
        if name == "IBAN" and val:
            ok, why = iban_ok(val)
            if not ok:
                out.append(_f("error", "IBAN", where, val, f"{val} {why}."))
        elif name in ("BICFI", "AnyBIC", "BIC") and val:
            if not BIC_RE.fullmatch(val):
                out.append(_f("error", "BIC", where, val, f"\"{val}\" is not a valid BIC (8 or 11 characters: bank 4, country 2, location 2, branch 3)."))
        elif name == "UETR" and val and not UUID_RE.fullmatch(val):
            out.append(_f("error", "UETR", where, val, f"\"{val}\" is not a UUID v4 (lowercase, 8-4-4-4-12)."))
        elif name.endswith("Dt") and not name.endswith("DtTm") and val and len(val) <= 10:
            if not real_date(val):
                out.append(_f("error", "Date", where, val, f"\"{val}\" is not a valid date (YYYY-MM-DD)."))
        ccy = el.get("Ccy")
        if ccy is not None:
            if ccy not in CCY_DECIMALS and not re.fullmatch(r"[A-Z]{3}", ccy):
                out.append(_f("error", "Currency", where, ccy, f"\"{ccy}\" is not an ISO 4217 currency code."))
            amt = norm_amount(val)
            if amt is None or Decimal(amt) < 0:
                out.append(_f("error", "Amount", where, val, f"\"{val}\" is not a valid amount."))
            else:
                dec = len(val.split(".")[1]) if "." in val else 0
                allowed = CCY_DECIMALS.get(ccy)
                if allowed is not None and dec > allowed:
                    out.append(_f("error", "Amount precision", where, val, f"{val} {ccy} has {dec} decimals; {ccy} allows {allowed}."))

    txs = [e for e in root.iter() if isinstance(e.tag, str) and local(e.tag) in ("CdtTrfTxInf", "DrctDbtTxInf")]
    for grp in [e for e in root.iter() if isinstance(e.tag, str) and local(e.tag) in ("GrpHdr", "PmtInf")]:
        kids = {local(c.tag): c for c in grp if isinstance(c.tag, str)}
        scope = txs if local(grp.tag) == "GrpHdr" else [e for e in grp.iter() if isinstance(e.tag, str) and local(e.tag) in ("CdtTrfTxInf", "DrctDbtTxInf")]
        if "NbOfTxs" in kids and txs:
            n = (kids["NbOfTxs"].text or "").strip()
            if n.isdigit() and int(n) != len(scope):
                out.append(_f("error", "NbOfTxs", path_of(kids["NbOfTxs"]), n, f"NbOfTxs says {n} but the message carries {len(scope)}."))
        if "CtrlSum" in kids and scope:
            total = Decimal(0)
            for tx in scope:
                for a in tx.iter():
                    if isinstance(a.tag, str) and local(a.tag) in ("IntrBkSttlmAmt", "InstdAmt") and norm_amount(a.text or "") is not None:
                        total += Decimal(norm_amount(a.text))
                        break
            cs = norm_amount(kids["CtrlSum"].text or "")
            if cs is not None and Decimal(cs) != total:
                out.append(_f("error", "CtrlSum", path_of(kids["CtrlSum"]), kids["CtrlSum"].text.strip(), f"CtrlSum is {kids['CtrlSum'].text.strip()} but the amounts add up to {format(total.normalize(), 'f')}."))
    return out


def _validate_mt(text, det):
    out = []
    fields = mt_fields(text)
    if not fields:
        return [_f("error", "MT format", "", "", "No MT fields found (lines like :20:REFERENCE).")]
    tags = [t for t, _ in fields]
    need = MT_MANDATORY.get(det["code"] or "", [])
    for want in need:
        opts = want.split("|")
        if not any(any(t == o or (o.endswith("a") and t.startswith(o[:-1])) for t in tags) for o in opts):
            out.append(_f("error", "Mandatory field", f":{want.replace('|', '/')}:", "", f"Field :{want.replace('|', ' or :')}: is mandatory in {det['code']}."))
    for tag, val in fields:
        first = val.split("\n")[0].strip()
        where = f":{tag}:"
        if tag in ("20", "21") and (len(first) > 16 or first.startswith("/") or first.endswith("/") or "//" in first):
            out.append(_f("error", "Reference", where, first, "References are at most 16 characters and can't start or end with '/' or contain '//'."))
        elif tag == "32A":
            m = re.fullmatch(r"(\d{6})([A-Z]{3})(\d{1,12},\d{0,3})", first)
            if not m:
                out.append(_f("error", "Field 32A", where, first, "32A must be YYMMDD + currency + amount with a comma decimal, e.g. 260627USD400,00."))
            elif not yymmdd_to_iso(m[1]):
                out.append(_f("error", "Date", where, m[1], f"{m[1]} is not a valid YYMMDD date."))
            else:
                dec = len(m[3].split(",")[1])
                if CCY_DECIMALS.get(m[2]) is not None and dec > CCY_DECIMALS[m[2]]:
                    out.append(_f("error", "Amount precision", where, m[3], f"{m[2]} allows {CCY_DECIMALS[m[2]]} decimals."))
        elif tag in ("32B", "33B") and not re.fullmatch(r"[A-Z]{3}\d{1,12},\d{0,3}", first):
            out.append(_f("error", f"Field {tag}", where, first, f"{tag} must be currency + amount with a comma decimal, e.g. USD400,00."))
        elif tag == "71A" and first not in ("OUR", "BEN", "SHA"):
            out.append(_f("error", "Charges", where, first, "71A must be OUR, BEN or SHA."))
        elif tag == "23B" and first not in ("CRED", "CRTS", "SPAY", "SPRI", "SSTD"):
            out.append(_f("error", "Bank operation code", where, first, "23B must be CRED, CRTS, SPAY, SPRI or SSTD."))
        elif tag.endswith("A") and tag[:2] in ("50", "52", "53", "54", "56", "57", "58", "59"):
            lines = [x.strip() for x in val.split("\n") if x.strip()]
            bic = next((x for x in lines if not x.startswith("/")), "")
            if bic and not BIC_RE.fullmatch(bic):
                out.append(_f("error", "BIC", where, bic, f"\"{bic}\" is not a valid BIC."))
        elif tag == "30" and not yymmdd_to_iso(first):
            out.append(_f("error", "Date", where, first, f"{first} is not a valid YYMMDD date."))
        for ln in val.split("\n"):
            if len(ln) > 35 and tag not in ("79", "77E", "86", "61"):
                out.append(_f("warning", "Line length", where, ln[:40], "MT lines in this field are limited to 35 characters."))
                break
        for iban in IBAN_RE.findall(val.replace(" ", "")):
            if iban[:2] in IBAN_LENGTHS:
                ok, why = iban_ok(iban)
                if not ok:
                    out.append(_f("error", "IBAN", where, iban, f"{iban} {why}."))
    return out


# ── value extraction & fidelity ─────────────────────────────────────────────
def bic11(bic: str) -> str:
    """BICs compared at full length: an 8-character BIC means branch XXX."""
    b = (bic or "").strip().upper()
    return b + "XXX" if len(b) == 8 else b

GENERATED_MX = {"CreDtTm", "MsgId", "UETR", "BizMsgIdr", "CreDt"}


def extract_values(text: str) -> dict:
    """Money-critical values as normalized sets: amounts (amount+ccy), currencies, bics (BIC8), accounts, dates, refs."""
    parts = split_mt(text) if not (text or "").lstrip().startswith("<") else [text]
    if len(parts) > 1:
        merged = {}
        for p in parts:
            for k, vals in extract_values(p).items():
                merged.setdefault(k, set()).update(vals)
        return merged
    det = detect(text)
    v = {"amounts": set(), "currencies": set(), "bics": set(), "accounts": set(), "dates": set(), "refs": set(), "generated": set()}
    if det["std"] == "MX":
        root, _ = _parse_xml(text)
        if root is None:
            return v
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            name, val = local(el.tag), (el.text or "").strip()
            if not val:
                continue
            if el.get("Ccy") and norm_amount(val) is not None:
                v["amounts"].add(f"{norm_amount(val)} {el.get('Ccy')}")
                v["currencies"].add(el.get("Ccy"))
            elif name in ("BICFI", "AnyBIC", "BIC") and len(val) >= 8:
                v["bics"].add(bic11(val))
            elif name == "IBAN" or (name == "Id" and el.getparent() is not None and local(el.getparent().tag) == "Othr"
                                    and el.getparent().getparent() is not None and local(el.getparent().getparent().tag) == "Id"):
                v["accounts"].add(re.sub(r"\s+", "", val).upper())
            elif name in GENERATED_MX:
                v["generated"].add(val)
                if name == "UETR":
                    v["refs"].add(val.lower())
            elif name in ("InstrId", "EndToEndId", "TxId", "PmtInfId", "OrgnlMsgId", "OrgnlEndToEndId", "OrgnlInstrId", "OrgnlTxId",
                          "OrgnlUETR", "AcctSvcrRef", "RtrId", "CxlId", "MndtId", "OrgnlPmtInfId", "NtryRef"):
                v["refs"].add(val if name != "OrgnlUETR" else val.lower())
            elif name == "Id" and el.getparent() is not None and local(el.getparent().tag) in ("Stmt", "Ntfctn", "Rpt", "Assgnmt", "Case"):
                v["refs"].add(val)
            elif (name.endswith("Dt") or name.endswith("DtTm")) and name not in GENERATED_MX:
                d = val[:10]
                if real_date(d):
                    v["dates"].add(d)
    elif det["std"] == "MT":
        b3 = re.search(r"\{121:([0-9a-fA-F-]{36})\}", text or "")
        if b3:
            v["refs"].add(b3.group(1).lower())
        # Block 1/2 LT addresses: BIC8 + terminal letter + branch → the 11-character BIC.
        for b8, br in re.findall(r"\{[12]:(?:F01|[IO]\d{3})([A-Z]{6}[A-Z0-9]{2})[A-Z]([A-Z0-9]{3})", text or ""):
            v["bics"].add(b8 + br)
        for tag, val in mt_fields(text):
            first = val.split("\n")[0].strip()
            if tag == "32A":
                m = re.fullmatch(r"(\d{6})([A-Z]{3})(\d[\d,]*)", first)
                if m:
                    if yymmdd_to_iso(m[1]):
                        v["dates"].add(yymmdd_to_iso(m[1]))
                    v["currencies"].add(m[2])
                    if norm_amount(m[3]):
                        v["amounts"].add(f"{norm_amount(m[3])} {m[2]}")
            elif tag in ("32B", "33B", "34B"):
                m = re.fullmatch(r"([A-Z]{3})(\d[\d,]*)", first)
                if m and norm_amount(m[2]):
                    v["currencies"].add(m[1])
                    v["amounts"].add(f"{norm_amount(m[2])} {m[1]}")
            elif tag[:2] in ("60", "62", "64", "65"):
                m = re.fullmatch(r"([CD])(\d{6})([A-Z]{3})(\d[\d,]*)", first)
                if m:
                    if yymmdd_to_iso(m[2]):
                        v["dates"].add(yymmdd_to_iso(m[2]))
                    v["currencies"].add(m[3])
                    if norm_amount(m[4]):
                        v["amounts"].add(f"{norm_amount(m[4])} {m[3]}")
            elif tag in ("30", "31C", "11S"):
                for tok in re.findall(r"\d{6}", val if tag == "11S" else first)[:1]:
                    if yymmdd_to_iso(tok):
                        v["dates"].add(yymmdd_to_iso(tok))
            elif tag in ("20", "21", "21R", "21F", "21C"):
                v["refs"].add(first)
            elif tag == "61":
                m = re.match(r"\d{6}(?:\d{4})?R?[CD][A-Z]?\d[\d,]*[SNF][A-Z0-9]{3}([^/\n]*)(?://([^\n]+))?", first)
                if m:
                    v["refs"].update(x.strip() for x in m.groups() if x and x.strip() and x.strip() != "NONREF")
            if tag in ("70", "72", "79"):
                for m in re.finditer(r"/(?:ROC|MREF)/([^\s/]+)", val):
                    v["refs"].add(m.group(1))
            elif tag == "25":
                v["accounts"].add(re.sub(r"\s+", "", first.lstrip("/")).upper())
            if tag[:2] in ("50", "52", "53", "54", "56", "57", "58", "59"):
                for ln in [x.strip() for x in val.split("\n") if x.strip()]:
                    if ln.startswith("/"):
                        v["accounts"].add(re.sub(r"\s+", "", ln.lstrip("/")).upper())
                    elif BIC_RE.fullmatch(ln):
                        v["bics"].add(bic11(ln))
            for iban in IBAN_RE.findall(val.replace(" ", "")):
                if iban[:2] in IBAN_LENGTHS and iban_ok(iban)[0]:
                    v["accounts"].add(iban)
    return v


KIND_LABEL = {"amounts": "amount", "currencies": "currency", "bics": "BIC", "accounts": "account", "dates": "date", "refs": "reference"}


def compare_values(source: str, output: str, declared: list[str] | None = None) -> dict:
    """Check the output against the source.

    invented: values in the output that aren't in the source (red, unless the
              value is listed in `declared`, e.g. a field generated by the mapping rules).
    dropped:  money-critical source values missing from the output (amber).
    """
    s, o = extract_values(source), extract_values(output)
    declared_norm = {str(x).strip().upper() for x in (declared or [])}

    def declared_has(val: str) -> bool:
        u = val.upper()
        return any(u == d or u.split(" ")[0] == d or d.replace(",", ".") == u.split(" ")[0] for d in declared_norm) or any(u in d for d in declared_norm)

    invented, dropped, new_refs = [], [], []
    s_acc_text = " ".join(s["accounts"])
    for kind in ("amounts", "currencies", "bics", "accounts", "dates"):
        for val in sorted(o[kind] - s[kind]):
            if kind == "accounts" and (val in s_acc_text or any(val in a or a in val for a in s["accounts"])):
                continue
            if declared_has(val):
                continue
            invented.append({"kind": KIND_LABEL[kind], "value": val})
    truncated = []
    known_refs = s["refs"] | s["generated"]
    for val in sorted(o["refs"] - known_refs):
        if val in o["generated"] or val.lower() in {g.lower() for g in o["generated"]}:
            new_refs.append(val)
        elif len(val) >= 6 and any(src.startswith(val) for src in known_refs):
            # MT references are 16x: a cut-down copy of a longer source reference.
            truncated.append(val)
        elif not declared_has(val):
            invented.append({"kind": "reference", "value": val})
    for kind in ("amounts", "currencies", "bics", "accounts"):
        for val in sorted(s[kind] - o[kind]):
            if kind == "accounts" and any(val in a or a in val for a in o["accounts"]):
                continue
            if declared_has(val):
                continue
            dropped.append({"kind": KIND_LABEL[kind], "value": val})
    carried = [{"kind": KIND_LABEL.get(k, "reference"), "value": val}
               for k in ("amounts", "bics", "accounts", "dates", "refs")
               for val in sorted((known_refs if k == "refs" else s[k]) & o[k])]
    return {"ok": not invented, "invented": invented, "dropped": dropped, "new_references": new_refs, "truncated": truncated,
            "carried": carried}
