"""Deterministic, pair-specific checks for generated MT/MX output.

These checks are ordinary code. They never call an AI model or external service.
"""
from __future__ import annotations

import re

from . import checks


def _f(rule, where, value, msg):
    return {"severity": "error", "rule": rule, "where": where, "value": value, "message": msg}


def header_findings(mt: str) -> list[dict]:
    """Block 1 and 2 addresses must be well formed."""
    out = []
    b1 = re.search(r"\{1:([^}]*)\}", mt or "")
    if b1 and not re.fullmatch(r"F01[A-Z]{6}[A-Z0-9]{2}[A-Z][A-Z0-9]{3}\d{10}", b1.group(1)):
        out.append(_f("Block 1", "{1:}", b1.group(1), "Block 1 must be F01 + a 12-character LT address (BIC8 + terminal letter + branch) + 10 digits."))
    b2 = re.search(r"\{2:([^}]*)\}", mt or "")
    if b2 and not re.fullmatch(r"I\d{3}[A-Z]{6}[A-Z0-9]{2}[A-Z][A-Z0-9]{3}[NUS]?(\d{1,3})?", b2.group(1)):
        out.append(_f("Block 2", "{2:}", b2.group(1), "Block 2 must be I + the MT number + a 12-character receiver address (BIC8 + X + branch) + priority."))
    return out


# ── precise per-pair checks ─────────────────────────────────────────────────
class _MX:
    """Path lookups on an ISO 20022 message: "TxInf/RtrId" matches by ancestor chain."""
    def __init__(self, xml: str):
        self.root, _ = checks._parse_xml(xml or "")

    def _matches(self, path: str):
        if self.root is None:
            return []
        parts = path.split("/")
        out = []
        for el in self.root.iter():
            if not isinstance(el.tag, str) or checks.local(el.tag) != parts[-1]:
                continue
            node, ok = el, True
            for want in reversed(parts[:-1]):
                node = node.getparent()
                while node is not None and checks.local(node.tag) != want:
                    node = node.getparent()
                if node is None:
                    ok = False
                    break
            if ok:
                out.append(el)
        return out

    def get(self, *paths: str) -> str:
        for p in paths:
            for el in self._matches(p):
                if (el.text or "").strip():
                    return el.text.strip()
        return ""

    def attr(self, path: str, name: str) -> str:
        els = self._matches(path)
        return (els[0].get(name) or "") if els else ""

    def count(self, path: str) -> int:
        return len(self._matches(path))

    def balance(self, code: str) -> dict:
        for bal in self._matches("Bal"):
            tp = "".join(x.text or "" for x in bal.iter() if isinstance(x.tag, str) and checks.local(x.tag) == "Cd")
            if code in tp:
                get = lambda n: next(((x.text or "").strip() for x in bal.iter() if isinstance(x.tag, str) and checks.local(x.tag) == n and (x.text or "").strip()), "")
                amt = next((x for x in bal.iter() if isinstance(x.tag, str) and checks.local(x.tag) == "Amt"), None)
                return {"amt": get("Amt"), "ccy": amt.get("Ccy") if amt is not None else "", "ind": get("CdtDbtInd"), "dt": get("Dt")[:10]}
        return {}


class _MT:
    def __init__(self, text: str):
        self.text = text or ""
        self.fields = checks.mt_fields(self.text)

    def get(self, *tags: str) -> str:
        for tag in tags:
            for t, v in self.fields:
                if t == tag:
                    return v.split("\n")[0].strip()
        return ""

    def full(self, tag: str) -> str:
        return next((v for t, v in self.fields if t == tag), "")

    def all(self, tag: str) -> list[str]:
        return [v.split("\n")[0].strip() for t, v in self.fields if t == tag]

    def lines(self, tag: str) -> list[str]:
        return [x.strip() for x in self.full(tag).split("\n") if x.strip()]

    def mt_type(self) -> str:
        m = re.search(r"\{2:[IO](\d{3})", self.text)
        return m.group(1) if m else ""


_CHRG_TO_MT = {"SHAR": "SHA", "DEBT": "OUR", "CRED": "BEN", "SLEV": "SHA"}
_CHRG_TO_MX = {"SHA": "SHAR", "OUR": "DEBT", "BEN": "CRED"}


def _amt(x: str) -> str:
    return checks.norm_amount(x) or ""


def _yymmdd(iso: str) -> str:
    return iso[2:4] + iso[5:7] + iso[8:10] if len(iso) >= 10 else ""


def _iso(yymmdd: str) -> str:
    return checks.yymmdd_to_iso(yymmdd) or ""


def _split_32(v: str) -> dict:
    m = re.fullmatch(r"(\d{6})?([A-Z]{3})(\d[\d,]*)", v or "")
    return {"date": m.group(1) or "", "ccy": m.group(2), "amt": _amt(m.group(3))} if m else {}


def _bal_line(v: str) -> dict:
    m = re.fullmatch(r"([CD])(\d{6})([A-Z]{3})(\d[\d,]*)", v or "")
    return {"ind": m.group(1), "date": m.group(2), "ccy": m.group(3), "amt": _amt(m.group(4))} if m else {}


def _bic_eq(a: str, b: str) -> bool:
    return checks.bic11(a) == checks.bic11(b)


class _Checker:
    def __init__(self):
        self.out: list[dict] = []

    def need(self, ok: bool, rule: str, where: str, got: str, msg: str):
        if not ok:
            self.out.append(_f(rule, where, got, msg))

    def eq(self, rule: str, where: str, got: str, want: str, what: str = ""):
        if want and got != want:
            self.out.append(_f(rule, where, got, f"{where} must be {want}{(' (' + what + ')') if what else ''}."))


def _mx_to_mt_amount_date(c, S, O, amt_path, date_path, tag="32A"):
    want = {"date": _yymmdd(S.get(date_path)), "ccy": S.attr(amt_path, "Ccy"), "amt": _amt(S.get(amt_path))}
    got = _split_32(O.get(tag))
    c.need(bool(got) and all(got.get(k) == v for k, v in want.items() if v), f"Field {tag}", f":{tag}:", O.get(tag),
           f":{tag}: must be {want['date']}{want['ccy']}{want['amt'].replace('.', ',')} (date YYMMDD, currency, amount with a comma).")


def _mt_to_mx_amount_date(c, S, O, amt_path, date_path, tag="32A"):
    src = _split_32(S.get(tag))
    if not src:
        return
    c.eq("Amount", amt_path, _amt(O.get(amt_path)), src["amt"], f"from :{tag}:")
    c.eq("Currency", amt_path + "@Ccy", O.attr(amt_path, "Ccy"), src["ccy"], f"from :{tag}:")
    if src["date"] and date_path:
        c.eq("Date", date_path, O.get(date_path)[:10], _iso(src["date"]), f"from :{tag}:")


def _check_pacs008_mt103(c, S, O):
    instr, e2e = S.get("PmtId/InstrId"), S.get("PmtId/EndToEndId")
    c.eq("Field 20", ":20:", O.get("20"), (instr or e2e)[:16], "the InstrId cut to 16 characters")
    c.eq("Field 23B", ":23B:", O.get("23B"), "CRED")
    _mx_to_mt_amount_date(c, S, O, "IntrBkSttlmAmt", "IntrBkSttlmDt")
    if instr and e2e and e2e != "NOTPROVIDED":
        c.need(f"/ROC/{e2e}"[:35] in "".join(O.lines("70")), "Field 70", ":70:", O.get("70"), f"The EndToEndId must be carried in :70: as /ROC/{e2e}.")
    for path, tag in (("DbtrAgt/FinInstnId/BICFI", "52A"), ("CdtrAgt/FinInstnId/BICFI", "57A"), ("IntrmyAgt1/FinInstnId/BICFI", "56A")):
        want = S.get(path)
        if want:
            c.need(_bic_eq(O.get(tag), want), f"Field {tag}", f":{tag}:", O.get(tag), f":{tag}: must be {want}.")
    chrg = _CHRG_TO_MT.get(S.get("ChrgBr"))
    c.eq("Field 71A", ":71A:", O.get("71A"), chrg or "", "from ChrgBr")
    for path, tag in (("Dbtr/Nm", "50"), ("Cdtr/Nm", "59")):
        name = S.get(path)
        val = " ".join(O.lines(tag + "K") or O.lines(tag + "F") or O.lines(tag) or O.lines(tag + "A"))
        if name:
            c.need(name[:35].upper() in val.upper(), f"Field {tag}", f":{tag}a:", val[:40], f"The {'debtor' if tag == '50' else 'creditor'} name {name} must be in :{tag}a:.")
    for path, tag, who in (("DbtrAcct/Id", "50", "debtor"), ("CdtrAcct/Id", "59", "creditor")):
        acct = S.get(path + "/IBAN", path + "/Othr/Id")
        val = "".join(O.lines(tag + "K") or O.lines(tag + "F") or O.lines(tag) or O.lines(tag + "A"))
        if acct:
            c.need(("/" + acct) in val, f"Field {tag}", f":{tag}a:", val[:40], f"The {who} account /{acct} must be the first line of :{tag}a:.")


def _check_mt103_pacs008(c, S, O):
    c.eq("InstrId", "PmtId/InstrId", O.get("PmtId/InstrId"), S.get("20"), "from :20:")
    roc = re.search(r"/ROC/([^\s/]+)", S.full("70") or "")
    c.eq("EndToEndId", "PmtId/EndToEndId", O.get("PmtId/EndToEndId"), roc.group(1) if roc else "NOTPROVIDED", "from /ROC/ in :70:")
    _mt_to_mx_amount_date(c, S, O, "IntrBkSttlmAmt", "IntrBkSttlmDt")
    c.eq("ChrgBr", "ChrgBr", O.get("ChrgBr"), _CHRG_TO_MX.get(S.get("71A"), ""), "from :71A:")
    for tag, path in (("52A", "DbtrAgt/FinInstnId/BICFI"), ("57A", "CdtrAgt/FinInstnId/BICFI")):
        bic = next((x for x in S.lines(tag) if not x.startswith("/")), "")
        if bic:
            c.need(_bic_eq(O.get(path), bic), "Agent BIC", path, O.get(path), f"{path} must be {bic} (from :{tag}:).")


def _check_pacs004_mt103retn(c, S, O):
    c.eq("Field 20", ":20:", O.get("20"), S.get("TxInf/RtrId")[:16], "the RtrId cut to 16 characters")
    _mx_to_mt_amount_date(c, S, O, "RtrdIntrBkSttlmAmt", "IntrBkSttlmDt")
    l72 = O.lines("72")
    c.need(bool(l72) and l72[0].startswith("/RETN/"), "Field 72", ":72:", l72[0] if l72 else "", ":72: must start with /RETN/.")
    code = S.get("RtrRsnInf/Rsn/Cd")
    if code:
        c.need(any(f"/{code}/" in x for x in l72), "Field 72", ":72:", " ".join(l72)[:40], f"The return reason /{code}/ must be in :72:.")
    ref = S.get("OrgnlInstrId", "OrgnlEndToEndId")[:16]
    if ref:
        c.need(any(x.startswith("/MREF/" + ref) for x in l72), "Field 72", ":72:", " ".join(l72)[:40], f":72: must carry /MREF/{ref}.")


def _check_mt103retn_pacs004(c, S, O):
    c.eq("RtrId", "TxInf/RtrId", O.get("TxInf/RtrId"), S.get("20"), "from :20:")
    _mt_to_mx_amount_date(c, S, O, "RtrdIntrBkSttlmAmt", "IntrBkSttlmDt")
    code = next((m.group(1) for x in S.lines("72")[1:] for m in [re.match(r"/([A-Z0-9]{4})/", x)] if m), "")
    c.eq("Return reason", "RtrRsnInf/Rsn/Cd", O.get("RtrRsnInf/Rsn/Cd"), code, "from :72:")


def _check_pain001_mt101(c, S, O):
    c.eq("Field 20", ":20:", O.get("20"), S.get("GrpHdr/MsgId")[:16], "the MsgId cut to 16 characters")
    c.eq("Field 28D", ":28D:", O.get("28D"), "1/1")
    c.eq("Field 30", ":30:", O.get("30"), _yymmdd(S.get("ReqdExctnDt/Dt", "ReqdExctnDt")), "ReqdExctnDt as YYMMDD")
    e2es = [e.text.strip() for e in S._matches("CdtTrfTxInf/PmtId/EndToEndId") if e.text]
    c.need([x[:16] for x in e2es] == O.all("21"), "Field 21", ":21:", ", ".join(O.all("21")), "Each :21: must be the EndToEndId of its transaction (16 characters), in order.")
    want = {"ccy": S.attr("InstdAmt", "Ccy"), "amt": _amt(S.get("InstdAmt"))}
    got = _split_32(O.get("32B"))
    c.need(got.get("ccy") == want["ccy"] and got.get("amt") == want["amt"], "Field 32B", ":32B:", O.get("32B"), f":32B: must be {want['ccy']}{want['amt'].replace('.', ',')}.")
    acct = S.get("DbtrAcct/Id/IBAN", "DbtrAcct/Id/Othr/Id")
    if acct:
        c.need(("/" + acct) in "".join(O.lines("50H")), "Field 50H", ":50H:", O.get("50H"), f":50H: must start with /{acct}.")


def _check_mt101_pain001(c, S, O):
    c.eq("MsgId", "GrpHdr/MsgId", O.get("GrpHdr/MsgId"), S.get("20"), "from :20:")
    c.eq("Execution date", "ReqdExctnDt", O.get("ReqdExctnDt/Dt", "ReqdExctnDt"), _iso(S.get("30")), "from :30:")
    c.eq("NbOfTxs", "GrpHdr/NbOfTxs", O.get("GrpHdr/NbOfTxs"), str(len(S.all("21"))), "one per :21:")
    c.need(O.get("CdtTrfTxInf/PmtId/EndToEndId") == S.get("21"), "EndToEndId", "PmtId/EndToEndId", O.get("CdtTrfTxInf/PmtId/EndToEndId"), f"EndToEndId must be {S.get('21')} (from :21:).")
    src = _split_32(S.get("32B"))
    if src:
        c.eq("Amount", "InstdAmt", _amt(O.get("InstdAmt")), src["amt"], "from :32B:")


def _check_pain008_mt104(c, S, O):
    c.eq("Field 20", ":20:", O.get("20"), S.get("GrpHdr/MsgId")[:16], "the MsgId cut to 16 characters")
    c.eq("Field 30", ":30:", O.get("30"), _yymmdd(S.get("ReqdColltnDt")), "ReqdColltnDt as YYMMDD")
    c.eq("Field 21", ":21:", O.get("21"), S.get("DrctDbtTxInf/PmtId/EndToEndId")[:16], "the EndToEndId")
    got = _split_32(O.get("32B"))
    c.need(got.get("amt") == _amt(S.get("DrctDbtTxInf/InstdAmt")) and got.get("ccy") == S.attr("DrctDbtTxInf/InstdAmt", "Ccy"),
           "Field 32B", ":32B:", O.get("32B"), ":32B: must be the InstdAmt currency and amount.")


def _check_mt104_pain008(c, S, O):
    c.eq("MsgId", "GrpHdr/MsgId", O.get("GrpHdr/MsgId"), S.get("20"), "from :20:")
    c.eq("Collection date", "ReqdColltnDt", O.get("ReqdColltnDt")[:10], _iso(S.get("30")), "from :30:")
    c.eq("EndToEndId", "PmtId/EndToEndId", O.get("DrctDbtTxInf/PmtId/EndToEndId"), S.get("21"), "from :21:")
    src = _split_32(S.get("32B"))
    if src:
        c.eq("Amount", "InstdAmt", _amt(O.get("DrctDbtTxInf/InstdAmt")), src["amt"], "from :32B:")


def _check_camt053_mt940(c, S, O):
    c.eq("Field 20", ":20:", O.get("20"), (S.get("Stmt/Id") or S.get("GrpHdr/MsgId"))[:16], "the statement Id cut to 16 characters")
    c.eq("Field 25", ":25:", O.get("25"), S.get("Stmt/Acct/Id/IBAN", "Stmt/Acct/Id/Othr/Id"), "the account")
    for code, tag in (("OPBD", "60F"), ("CLBD", "62F")):
        b = S.balance(code)
        if b:
            want = ("C" if b["ind"] == "CRDT" else "D") + _yymmdd(b["dt"]) + b["ccy"]
            got = _bal_line(O.get(tag))
            c.need(bool(got) and got["ind"] + got["date"] + got["ccy"] == want and got["amt"] == _amt(b["amt"]),
                   f"Field {tag}", f":{tag}:", O.get(tag), f":{tag}: must be {want}{_amt(b['amt']).replace('.', ',')} (the {code} balance).")
    c.eq("Entries", ":61:", str(len(O.all("61"))), str(S.count("Stmt/Ntry")), "one :61: per entry")


def _check_mt940_camt053(c, S, O):
    c.eq("Statement Id", "Stmt/Id", O.get("Stmt/Id"), S.get("20"), "from :20:")
    c.eq("Account", "Stmt/Acct/Id", O.get("Stmt/Acct/Id/IBAN", "Stmt/Acct/Id/Othr/Id"), S.get("25"), "from :25:")
    for tag, code in (("60F", "OPBD"), ("62F", "CLBD")):
        src = _bal_line(S.get(tag))
        b = O.balance(code)
        if src:
            c.need(bool(b) and _amt(b.get("amt")) == src["amt"] and b.get("ccy") == src["ccy"] and b.get("ind") == ("CRDT" if src["ind"] == "C" else "DBIT"),
                   f"Balance {code}", f"Bal {code}", b.get("amt", ""), f"The {code} balance must be {src['ind']} {src['ccy']} {src['amt']} (from :{tag}:).")
    c.eq("Entries", "Ntry", str(O.count("Stmt/Ntry")), str(len(S.all("61"))), "one entry per :61:")


def _check_camt054_mt9x0(c, S, O):
    ind = S.get("Ntry/CdtDbtInd")
    want_type = "900" if ind == "DBIT" else "910" if ind == "CRDT" else ""
    if want_type and O.mt_type():
        c.eq("Message type", "{2:}", O.mt_type(), want_type, "DBIT gives MT900, CRDT gives MT910")
    c.eq("Field 20", ":20:", O.get("20"), (S.get("Ntfctn/Id") or S.get("GrpHdr/MsgId"))[:16], "the notification Id cut to 16 characters")
    c.eq("Field 25", ":25:", O.get("25"), S.get("Ntfctn/Acct/Id/IBAN", "Ntfctn/Acct/Id/Othr/Id"), "the account")
    _mx_to_mt_amount_date(c, S, O, "Ntry/Amt", "Ntry/ValDt/Dt")


def _check_mt9x0_camt054(c, S, O):
    c.eq("Notification Id", "Ntfctn/Id", O.get("Ntfctn/Id"), S.get("20"), "from :20:")
    c.eq("Account", "Ntfctn/Acct/Id", O.get("Ntfctn/Acct/Id/IBAN", "Ntfctn/Acct/Id/Othr/Id"), S.get("25"), "from :25:")
    _mt_to_mx_amount_date(c, S, O, "Ntry/Amt", "Ntry/ValDt/Dt")
    t = S.mt_type()
    if t in ("900", "910"):
        c.eq("CdtDbtInd", "Ntry/CdtDbtInd", O.get("Ntry/CdtDbtInd"), "DBIT" if t == "900" else "CRDT", f"MT{t}")


def _check_camt056_mt192(c, S, O):
    c.eq("Field 20", ":20:", O.get("20"), S.get("Assgnmt/Id")[:16], "the assignment Id cut to 16 characters")
    c.eq("Field 21", ":21:", O.get("21"), S.get("OrgnlInstrId", "OrgnlEndToEndId")[:16], "the original :20:, i.e. OrgnlInstrId")
    c.eq("Field 11S", ":11S:", O.get("11S"), "103", "the original was a pacs.008, so MT103")
    code = S.get("CxlRsnInf/Rsn/Cd")
    if code:
        c.need(f"/{code}/" in O.full("79"), "Field 79", ":79:", O.get("79"), f":79: must start with the reason /{code}/.")


def _check_mt192_camt056(c, S, O):
    c.eq("Assignment Id", "Assgnmt/Id", O.get("Assgnmt/Id"), S.get("20"), "from :20:")
    c.eq("OrgnlInstrId", "OrgnlInstrId", O.get("OrgnlInstrId"), S.get("21"), "from :21:")
    code = re.search(r"/([A-Z0-9]{4})/", S.full("79") or "")
    if code:
        c.eq("Reason", "CxlRsnInf/Rsn/Cd", O.get("CxlRsnInf/Rsn/Cd"), code.group(1), "from :79:")


def _check_status_mt199(c, S, O, ref_paths):
    c.eq("Field 20", ":20:", O.get("20"), S.get("GrpHdr/MsgId")[:16], "the MsgId cut to 16 characters")
    ref = S.get(*ref_paths)[:16]
    if ref:
        c.eq("Field 21", ":21:", O.get("21"), ref, "the original reference")
    sts = S.get("TxSts", "GrpSts")
    if sts:
        c.need(sts in O.full("79"), "Field 79", ":79:", O.get("79"), f":79: must state the status {sts}.")


PAIR_CHECKS = {
    ("pacs.008", "MT103"): _check_pacs008_mt103,
    ("MT103", "pacs.008"): _check_mt103_pacs008,
    ("pacs.004", "MT103 RETN"): _check_pacs004_mt103retn,
    ("MT103 RETN", "pacs.004"): _check_mt103retn_pacs004,
    ("pain.001", "MT101"): _check_pain001_mt101,
    ("MT101", "pain.001"): _check_mt101_pain001,
    ("pain.008", "MT104"): _check_pain008_mt104,
    ("MT104", "pain.008"): _check_mt104_pain008,
    ("camt.053", "MT940"): _check_camt053_mt940,
    ("MT940", "camt.053"): _check_mt940_camt053,
    ("camt.054", "MT900 / MT910"): _check_camt054_mt9x0,
    ("MT900 / MT910", "camt.054"): _check_mt9x0_camt054,
    ("camt.056", "MT192"): _check_camt056_mt192,
    ("MT192", "camt.056"): _check_mt192_camt056,
    ("pacs.002", "MT199"): lambda c, S, O: _check_status_mt199(c, S, O, ("OrgnlInstrId", "OrgnlEndToEndId")),
    ("pain.002", "MT199"): lambda c, S, O: _check_status_mt199(c, S, O, ("OrgnlPmtInfId", "OrgnlEndToEndId")),
}


def pair_findings(src_type: str | None, tgt_type: str, source: str, output: str) -> list[dict]:
    """Every rule for this pair that can be checked by code. Each finding is an error."""
    c = _Checker()
    src_std = checks.FORMATS.get(src_type or "", {}).get("std")
    tgt_std = checks.FORMATS.get(tgt_type, {}).get("std")
    if tgt_std == "MT":
        c.out += header_findings(output)
    # UETR survives every pair.
    S = _MX(source) if src_std == "MX" else _MT(source)
    O = _MX(output) if tgt_std == "MX" else _MT(output)
    if src_std == "MX":
        uetr = S.get("UETR", "OrgnlUETR").lower()
    else:
        m = re.search(r"\{121:([0-9a-fA-F-]{36})\}", source or "")
        uetr = m.group(1).lower() if m else ""
    if uetr and tgt_std == "MX":
        got = O.get("UETR", "OrgnlUETR").lower()
        c.need(got == uetr, "UETR", "UETR", got, f"The UETR must be carried over exactly ({uetr}).")
    elif uetr and tgt_std == "MT" and tgt_type not in ("MT940", "MT900 / MT910", "MT199"):
        m = re.search(r"\{121:([0-9a-fA-F-]{36})\}", output or "")
        got = m.group(1).lower() if m else ""
        c.need(got == uetr, "UETR", "{121:}", got, f"Block 3 must carry the UETR exactly: {{121:{uetr}}}.")
    fn = PAIR_CHECKS.get((src_type, tgt_type))
    if fn:
        try:
            fn(c, S, O)
        except Exception as e:  # a malformed output is reported rather than crashing the conversion
            c.out.append(_f("Rule check", "", "", f"The result couldn't be checked against the {src_type} → {tgt_type} rules ({type(e).__name__})."))
    return c.out


