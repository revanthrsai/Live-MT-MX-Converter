"""ISO 20022 → SWIFT MT, by rule. One function per direction; each returns an Out."""
from __future__ import annotations

from decimal import Decimal

from .io import (Decline, M, Out, Party, X, mt_amount, mt_message, wrap, yymmdd)

CHRG_TO_MT = {"SHAR": "SHA", "DEBT": "OUR", "CRED": "BEN", "SLEV": "SHA"}
# /RETN/ line 1 names the field of the original message the return is about.
RETN_FIELD = {"AC": "59", "BE": "59", "MD": "59", "RR": "59", "AM": "32A", "AG": "57A", "RC": "57A"}
CXL_TEXT = {"DUPL": "Duplicate payment", "FRAD": "Fraudulent origin", "TECH": "Technical problem",
            "CUST": "Requested by customer", "AGNT": "Incorrect agent", "CURR": "Incorrect currency",
            "UPAY": "Undue payment", "AM09": "Wrong amount", "AC03": "Wrong creditor account"}
STATUS_TEXT = {"ACSC": "settled and credited", "ACCC": "credited to the creditor's account", "ACCP": "accepted",
               "ACSP": "accepted, settlement in progress", "ACTC": "accepted after technical checks",
               "ACWC": "accepted with changes", "RJCT": "rejected", "PDNG": "pending", "PART": "partly accepted",
               "RCVD": "received"}


def _one(x: X, path: str, what: str) -> X:
    items = x.all(path)
    if not items:
        raise Decline(f"The message has no {what}.")
    if len(items) > 1:
        raise Decline(f"The message carries {len(items)} {what}s; the MT format takes one per message.")
    return items[0]


def _party_field(out: Out, tag: str, p: Party, who: str) -> list[str]:
    lines, cut = p.mt_lines(4)
    if cut:
        out.note(f"The {who}'s name and address were longer than :{tag}: allows (4 lines of 35); the rest was cut.")
    return lines


def _amount32(x: X, out: Out, amt_path: str, date_path: str, tag: str = "32A") -> str:
    amt, ccy = x.amount(amt_path)
    dt = yymmdd(x.get(date_path))
    if not (amt and ccy and dt):
        raise Decline(f"The amount, currency or date for :{tag}: is missing.")
    return f"{dt}{ccy}{mt_amount(amt)}"


def _ustrd(x: X) -> str:
    parts = [n.text() for n in x.all("RmtInf/Ustrd")]
    for n in x.all("RmtInf/Ustrd"):
        x.used.add(n.el)
    return " ".join(p for p in parts if p)


# ── pacs.008 → MT103 ────────────────────────────────────────────────────────
def pacs008_mt103(src: str) -> Out:
    doc, out = X.parse(src), Out()
    tx = _one(doc, "CdtTrfTxInf", "transaction")
    doc.touch("GrpHdr/NbOfTxs")
    instr, e2e, uetr = tx.get("PmtId/InstrId"), tx.get("PmtId/EndToEndId"), tx.get("PmtId/UETR")
    sender = doc.get("GrpHdr/InstgAgt/FinInstnId/BICFI") or tx.get("DbtrAgt/FinInstnId/BICFI")
    receiver = doc.get("GrpHdr/InstdAgt/FinInstnId/BICFI") or tx.get("CdtrAgt/FinInstnId/BICFI")
    ref = (instr or e2e)[:16]
    if len(instr or e2e) > 16:
        out.note(f"The reference {(instr or e2e)} is longer than :20: allows, so it was cut to {ref}.")
    inst_amt, inst_ccy = tx.amount("InstdAmt")

    rmt = []
    if e2e and e2e != "NOTPROVIDED" and instr:
        rmt.append(f"/ROC/{e2e}"[:35])
    ustrd = _ustrd(tx)
    lines, cut = wrap(ustrd, 35)
    room = 4 - len(rmt)
    if len(lines) > room:
        out.note(f"The remittance information didn't fit in :70: (4 lines of 35); the rest was cut.")
        out.drop("RmtInf/Ustrd", " ".join(lines[room:]), "Beyond the 4 lines :70: allows.")
    rmt += lines[:room]

    dbtr = Party.from_mx(tx, "Dbtr", "DbtrAcct")
    cdtr = Party.from_mx(tx, "Cdtr", "CdtrAcct")
    fields = [
        ("20", ref),
        ("23B", "CRED"),
        ("32A", _amount32(tx, out, "IntrBkSttlmAmt", "IntrBkSttlmDt")),
        ("33B", f"{inst_ccy}{mt_amount(inst_amt)}" if inst_amt else ""),
        ("50A" if (dbtr.bic and not dbtr.name) else "50K",
         ([f"/{dbtr.account}"] if dbtr.account else []) + [dbtr.bic] if (dbtr.bic and not dbtr.name) else _party_field(out, "50K", dbtr, "debtor")),
        ("52A", tx.get("DbtrAgt/FinInstnId/BICFI")),
        ("56A", tx.get("IntrmyAgt1/FinInstnId/BICFI")),
        ("57A", tx.get("CdtrAgt/FinInstnId/BICFI")),
        ("59A" if (cdtr.bic and not cdtr.name) else "59",
         ([f"/{cdtr.account}"] if cdtr.account else []) + [cdtr.bic] if (cdtr.bic and not cdtr.name) else _party_field(out, "59", cdtr, "creditor")),
        ("70", rmt),
        ("71A", CHRG_TO_MT.get(tx.get("ChrgBr"), "SHA")),
    ]
    if not tx.get("ChrgBr"):
        out.fill(":71A:", "SHA", "The pacs.008 has no ChrgBr; SHA is the usual default.")
    if not dbtr.name and not dbtr.bic:
        raise Decline("The debtor has no name or BIC, and :50a: is mandatory.")
    out.message = mt_message("103", sender, receiver, fields, uetr)
    if not uetr:
        out.note("The pacs.008 has no UETR, so block 3 has no {121:}.")
    out.drop("GrpHdr/MsgId", doc.get("GrpHdr/MsgId"), "MT103 has no message-level identifier.")
    out.drop("GrpHdr/CreDtTm", doc.get("GrpHdr/CreDtTm"), "MT103 has no creation time; the network adds its own.")
    out.drop("SttlmInf/SttlmMtd", doc.get("GrpHdr/SttlmInf/SttlmMtd"), "Settlement method is implied by the MT103 route.")
    if instr and e2e:
        doc.touch("PmtId/EndToEndId")
    doc.touch("CdtTrfTxInf/DbtrAgt/FinInstnId/BICFI", "CdtTrfTxInf/CdtrAgt/FinInstnId/BICFI")
    out.leftovers(doc, "MT103")
    return out


# ── pacs.004 → MT103 RETN ───────────────────────────────────────────────────
def pacs004_mt103retn(src: str) -> Out:
    doc, out = X.parse(src), Out()
    tx = _one(doc, "TxInf", "returned transaction")
    doc.touch("GrpHdr/NbOfTxs")
    sender = doc.get("GrpHdr/InstgAgt/FinInstnId/BICFI")
    receiver = doc.get("GrpHdr/InstdAgt/FinInstnId/BICFI")
    code = tx.get("RtrRsnInf/Rsn/Cd")
    info = tx.get("RtrRsnInf/AddtlInf")
    mref = tx.get("OrgnlInstrId", "OrgnlEndToEndId")[:16]
    l72 = [f"/RETN/{RETN_FIELD.get(code[:2], '99')}"]
    if code:
        l72.append(f"/{code}/{info}"[:35])
    if mref:
        l72.append(f"/MREF/{mref}")
    if not code:
        out.note("The pacs.004 has no return reason code, so :72: carries only /RETN/ and /MREF/.")
    # In a return the parties swap: the original creditor now pays the original debtor.
    orig_cdtr = Party.from_mx(tx, "RtrChain/Cdtr", "RtrChain/CdtrAcct")
    if not (orig_cdtr.name or orig_cdtr.bic):
        orig_cdtr = Party.from_mx(tx, "OrgnlTxRef/Cdtr", "OrgnlTxRef/CdtrAcct")
    orig_dbtr = Party.from_mx(tx, "RtrChain/Dbtr", "RtrChain/DbtrAcct")
    if not (orig_dbtr.name or orig_dbtr.bic):
        orig_dbtr = Party.from_mx(tx, "OrgnlTxRef/Dbtr", "OrgnlTxRef/DbtrAcct")
    l50, l59 = _party_field(out, "50K", orig_cdtr, "original creditor"), _party_field(out, "59", orig_dbtr, "original debtor")
    if not l50:
        l50 = ["NOTPROVIDED"]
        out.fill(":50K:", "NOTPROVIDED", "The pacs.004 doesn't name the original creditor; :50a: is mandatory.")
    if not l59:
        l59 = ["NOTPROVIDED"]
        out.fill(":59:", "NOTPROVIDED", "The pacs.004 doesn't name the original debtor; :59a: is mandatory.")
    fields = [
        ("20", tx.get("RtrId")[:16]),
        ("23B", "CRED"),
        ("32A", _amount32(tx, out, "RtrdIntrBkSttlmAmt", "IntrBkSttlmDt")),
        ("50K", l50),
        ("59", l59),
        ("71A", CHRG_TO_MT.get(tx.get("ChrgBr"), "SHA")),
        ("72", l72),
    ]
    if not tx.get("RtrId"):
        raise Decline("The pacs.004 has no RtrId for :20:.")
    out.message = mt_message("103", sender, receiver, fields, tx.get("OrgnlUETR").lower())
    out.drop("GrpHdr/MsgId", doc.get("GrpHdr/MsgId"), "MT103 has no message-level identifier.")
    out.drop("GrpHdr/CreDtTm", doc.get("GrpHdr/CreDtTm"), "MT103 has no creation time.")
    out.leftovers(doc, "MT103 RETN")
    return out


# ── pain.001 → MT101 ────────────────────────────────────────────────────────
def pain001_mt101(src: str) -> Out:
    doc, out = X.parse(src), Out()
    pmt = _one(doc, "PmtInf", "payment information block")
    txs = pmt.all("CdtTrfTxInf")
    if not txs:
        raise Decline("The pain.001 has no CdtTrfTxInf.")
    doc.touch("GrpHdr/NbOfTxs", "GrpHdr/CtrlSum", "PmtInf/NbOfTxs", "PmtInf/CtrlSum", "PmtInf/PmtMtd")
    dbtr = Party.from_mx(pmt, "Dbtr", "DbtrAcct")
    dbtr_agt = pmt.get("DbtrAgt/FinInstnId/BICFI")
    sender = doc.get("GrpHdr/InitgPty/Id/OrgId/AnyBIC") or dbtr_agt
    msg_id = doc.get("GrpHdr/MsgId")
    fields = [
        ("20", msg_id[:16]),
        ("28D", "1/1"),
        ("50H", _party_field(out, "50H", dbtr, "debtor")),
        ("52A", dbtr_agt),
        ("30", yymmdd(pmt.get("ReqdExctnDt/Dt", "ReqdExctnDt"))),
    ]
    if not fields[4][1]:
        raise Decline("The pain.001 has no valid ReqdExctnDt for :30:.")
    chrg_all = ""  # set below when ChrgBr sits on PmtInf
    for tx in txs:
        amt, ccy = tx.amount("Amt/InstdAmt")
        if not amt:
            raise Decline("A transaction has no InstdAmt (the engine doesn't convert EqvtAmt).")
        cdtr = Party.from_mx(tx, "Cdtr", "CdtrAcct")
        lines, _ = wrap(_ustrd(tx), 35, 4)
        chrg = tx.get("ChrgBr") or chrg_all
        fields += [
            ("21", tx.get("PmtId/EndToEndId")[:16]),
            ("32B", f"{ccy}{mt_amount(amt)}"),
            ("57A", tx.get("CdtrAgt/FinInstnId/BICFI")),
            ("59", _party_field(out, "59", cdtr, "creditor")),
            ("70", lines),
            ("71A", CHRG_TO_MT.get(chrg) if chrg else None),
        ]
    # ChrgBr can sit on PmtInf instead of each transaction.
    pm_chrg = [c for c in pmt.el if isinstance(c.tag, str) and c.tag.endswith("ChrgBr")]
    if pm_chrg:
        pmt.used.add(pm_chrg[0])
        code = CHRG_TO_MT.get((pm_chrg[0].text or "").strip(), "SHA")
        fields = [(t, v if not (t == "71A" and not v) else code) for t, v in fields]
    if any(t == "71A" and not v for t, v in fields):
        fields = [(t, v or "SHA") if t == "71A" else (t, v) for t, v in fields]
        out.fill(":71A:", "SHA", "No ChrgBr in the pain.001; SHA is the usual default.")
    if len(msg_id) > 16:
        out.note(f"The MsgId {msg_id} is longer than :20: allows, so it was cut to {msg_id[:16]}.")
    out.message = mt_message("101", sender, dbtr_agt, fields)
    out.drop("GrpHdr/CreDtTm", doc.get("GrpHdr/CreDtTm"), "MT101 has no creation time.")
    out.drop("PmtInf/PmtInfId", pmt.get("PmtInfId"), "MT101 has no payment-information reference.")
    out.leftovers(doc, "MT101")
    return out


# ── pain.008 → MT104 ────────────────────────────────────────────────────────
def pain008_mt104(src: str) -> Out:
    doc, out = X.parse(src), Out()
    pmt = _one(doc, "PmtInf", "payment information block")
    txs = pmt.all("DrctDbtTxInf")
    if not txs:
        raise Decline("The pain.008 has no DrctDbtTxInf.")
    doc.touch("GrpHdr/NbOfTxs", "GrpHdr/CtrlSum", "PmtInf/NbOfTxs", "PmtInf/CtrlSum", "PmtInf/PmtMtd")
    cdtr = Party.from_mx(pmt, "Cdtr", "CdtrAcct")
    cdtr_agt = pmt.get("CdtrAgt/FinInstnId/BICFI")
    fields = [("20", doc.get("GrpHdr/MsgId")[:16]), ("30", yymmdd(pmt.get("ReqdColltnDt")))]
    if not fields[1][1]:
        raise Decline("The pain.008 has no valid ReqdColltnDt for :30:.")
    total, ccys, receiver = Decimal(0), set(), ""
    cdtr_lines = _party_field(out, "50K", cdtr, "creditor")
    for tx in txs:
        amt, ccy = tx.amount("InstdAmt")
        total += Decimal(amt)
        ccys.add(ccy)
        dbtr = Party.from_mx(tx, "Dbtr", "DbtrAcct")
        dbtr_agt = tx.get("DbtrAgt/FinInstnId/BICFI")
        receiver = receiver or dbtr_agt
        lines, _ = wrap(_ustrd(tx), 35, 4)
        fields += [
            ("21", tx.get("PmtId/EndToEndId")[:16]),
            ("21C", tx.get("MndtRltdInf/MndtId")[:35]),
            ("32B", f"{ccy}{mt_amount(amt)}"),
            ("50K", cdtr_lines),
            ("57A", dbtr_agt),
            ("59", _party_field(out, "59", dbtr, "debtor")),
            ("70", lines),
            ("71A", "SHA"),
        ]
    if len(ccys) != 1:
        raise Decline("The collections are in different currencies; one MT104 carries one currency.")
    ccy = ccys.pop()
    places = len(txs[0].amount("InstdAmt")[0].split(".")[1]) if "." in txs[0].amount("InstdAmt")[0] else 0
    total_s = f"{total:.{places}f}"
    fields.append(("32B", f"{ccy}{mt_amount(total_s)}"))
    if len(txs) > 1:
        fields.append(("19", mt_amount(total_s)))
    out.message = mt_message("104", cdtr_agt, receiver, fields)
    out.drop("GrpHdr/CreDtTm", doc.get("GrpHdr/CreDtTm"), "MT104 has no creation time.")
    out.drop("PmtInf/PmtInfId", pmt.get("PmtInfId"), "MT104 has no payment-information reference.")
    out.drop("MndtRltdInf/DtOfSgntr", "".join(t.get("MndtRltdInf/DtOfSgntr") for t in txs[:1]), "MT104 carries the mandate reference only.")
    out.leftovers(doc, "MT104")
    return out


# ── camt.053 → MT940 ────────────────────────────────────────────────────────
def _bal(stmt: X, codes: tuple[str, ...]) -> str:
    for bal in stmt.all("Bal"):
        if bal.get("Tp/CdOrPrtry/Cd") in codes:
            amt, ccy = bal.amount("Amt")
            ind = "C" if bal.get("CdtDbtInd") == "CRDT" else "D"
            dt = yymmdd(bal.get("Dt/Dt", "Dt/DtTm"))
            return f"{ind}{dt}{ccy}{mt_amount(amt)}"
    return ""


def _counterparty(ntry: X, credit: bool) -> str:
    return ntry.get("RltdPties/Dbtr/Pty/Nm", "RltdPties/Dbtr/Nm") if credit else ntry.get("RltdPties/Cdtr/Pty/Nm", "RltdPties/Cdtr/Nm")


def camt053_mt940(src: str) -> Out:
    doc, out = X.parse(src), Out()
    stmt = _one(doc, "Stmt", "statement")
    acct = stmt.get("Acct/Id/IBAN", "Acct/Id/Othr/Id")
    seq = stmt.get("LglSeqNb", "ElctrncSeqNb") or "1"
    opening, closing = _bal(stmt, ("OPBD", "PRCD")), _bal(stmt, ("CLBD",))
    if not (opening and closing):
        raise Decline("The statement needs an opening (OPBD) and a closing (CLBD) balance for :60F: and :62F:.")
    fields = [("20", (stmt.get("Id") or doc.get("GrpHdr/MsgId"))[:16]), ("25", acct), ("28C", f"{seq}/1"), ("60F", opening)]
    for n in stmt.all("Ntry"):
        amt, ccy = n.amount("Amt")
        credit = n.get("CdtDbtInd") == "CRDT"
        rev = n.get("RvslInd") in ("true", "1")
        # A reversal is booked opposite to the original: RC reverses a credit, RD a debit.
        mark = ("RD" if credit else "RC") if rev else ("C" if credit else "D")
        val = yymmdd(n.get("ValDt/Dt", "ValDt/DtTm"))
        book = yymmdd(n.get("BookgDt/Dt", "BookgDt/DtTm"))
        code = n.get("BkTxCd/Prtry/Cd")
        tt = code if (len(code) == 4 and code[0] in "NSF") else "NTRF"
        e2e, svcr = n.get("Refs/EndToEndId"), n.get("AcctSvcrRef")
        own = (e2e if e2e and e2e != "NOTPROVIDED" else svcr or "NONREF")[:16]
        line = f"{val or book}{book[2:] if book else ''}{mark}{mt_amount(amt)}{tt}{own}"
        if svcr and own != svcr[:16]:
            line += f"//{svcr[:16]}"
        n.touch("Sts/Cd", "Refs/UETR")
        fields.append(("61", line))
        info = " / ".join(v for v in (_counterparty(n, credit), _ustrd(n), n.get("AddtlNtryInf")) if v)
        if info:
            fields.append(("86", wrap(info, 65, 6)[0]))
    fields.append(("62F", closing))
    fields.append(("64", _bal(stmt, ("CLAV",))))
    fwav = _bal(stmt, ("FWAV",))
    if fwav:
        fields.append(("65", fwav))
    stmt.touch("Acct/Ccy")
    sender = stmt.get("Acct/Svcr/FinInstnId/BICFI")
    receiver = doc.get("GrpHdr/MsgRcpt/Id/OrgId/AnyBIC") or stmt.get("Acct/Ownr/Id/OrgId/AnyBIC")
    out.message = mt_message("940", sender, receiver, fields)
    if not out.message.startswith("{1:"):
        out.note("The camt.053 doesn't give the account servicer's and owner's BICs, so blocks 1 and 2 are left for you to add.")
    out.drop("GrpHdr/MsgId", doc.get("GrpHdr/MsgId") if stmt.get("Id") else "", "MT940 has one reference, :20:, which takes Stmt/Id.")
    out.drop("GrpHdr/CreDtTm", doc.get("GrpHdr/CreDtTm"), "MT940 has no creation time.")
    out.leftovers(doc, "MT940")
    return out


# ── camt.054 → MT900 / MT910 ────────────────────────────────────────────────
def camt054_mt9x0(src: str) -> Out:
    doc, out = X.parse(src), Out()
    ntf = _one(doc, "Ntfctn", "notification")
    n = _one(ntf, "Ntry", "entry")
    credit = n.get("CdtDbtInd") == "CRDT"
    amt, ccy = n.amount("Amt")
    val = yymmdd(n.get("ValDt/Dt", "ValDt/DtTm", "BookgDt/Dt", "BookgDt/DtTm"))
    if not (amt and val):
        raise Decline("The entry has no amount or value date for :32A:.")
    rel = (n.get("Refs/EndToEndId") or n.get("Refs/InstrId") or "NONREF")[:16]
    if rel == "NOTPROVIDED":
        rel = (n.get("Refs/InstrId") or "NONREF")[:16]
    fields = [("20", (ntf.get("Id") or doc.get("GrpHdr/MsgId"))[:16]), ("21", rel),
              ("25", ntf.get("Acct/Id/IBAN", "Acct/Id/Othr/Id")), ("32A", f"{val}{ccy}{mt_amount(amt)}")]
    if credit:
        # MT910: either :50a: (ordering customer) or :52a: (ordering institution), not both.
        name = n.get("RltdPties/Dbtr/Pty/Nm", "RltdPties/Dbtr/Nm")
        if name:
            fields.append(("50K", wrap(name, 35, 4)[0]))
        else:
            fields.append(("52A", n.get("RltdAgts/DbtrAgt/FinInstnId/BICFI")))
    else:
        fields.append(("52A", n.get("RltdAgts/CdtrAgt/FinInstnId/BICFI")))
    n.touch("Sts/Cd", "Refs/UETR", "Acct/Ccy")
    ntf.touch("Acct/Ccy")
    sender = ntf.get("Acct/Svcr/FinInstnId/BICFI")
    receiver = doc.get("GrpHdr/MsgRcpt/Id/OrgId/AnyBIC") or ntf.get("Acct/Ownr/Id/OrgId/AnyBIC")
    out.message = mt_message("910" if credit else "900", sender, receiver, fields)
    if not out.message.startswith("{1:"):
        out.note(f"The camt.054 doesn't give the account servicer's and owner's BICs, so blocks 1 and 2 of the MT{'910' if credit else '900'} are left for you to add.")
    out.drop("GrpHdr/MsgId", doc.get("GrpHdr/MsgId") if ntf.get("Id") else "", "The MT has one reference, :20:, which takes Ntfctn/Id.")
    out.drop("GrpHdr/CreDtTm", doc.get("GrpHdr/CreDtTm"), "The MT has no creation time.")
    out.leftovers(doc, "MT910" if credit else "MT900")
    return out


# ── camt.056 → MT192 ────────────────────────────────────────────────────────
def camt056_mt192(src: str) -> Out:
    doc, out = X.parse(src), Out()
    tx = _one(doc, "Undrlyg/TxInf", "underlying transaction")
    nm = tx.get("OrgnlGrpInf/OrgnlMsgNmId")
    orig_mt = "202" if nm.startswith("pacs.009") else "103"
    date = yymmdd(tx.get("OrgnlIntrBkSttlmDt") or doc.get("Assgnmt/CreDtTm"))
    code = tx.get("CxlRsnInf/Rsn/Cd")
    text = " ".join(t.text() for t in tx.all("CxlRsnInf/AddtlInf")) or CXL_TEXT.get(code, "")
    for t in tx.all("CxlRsnInf/AddtlInf"):
        tx.used.add(t.el)
    amt, ccy = tx.amount("OrgnlIntrBkSttlmAmt")
    narrative = (f"/{code}/" if code else "") + text + (". " if text else "") + (f"Original amount {ccy} {mt_amount(amt)}." if amt else "")
    fields = [
        ("20", doc.get("Assgnmt/Id")[:16]),
        ("21", tx.get("OrgnlInstrId", "OrgnlEndToEndId")[:16]),
        ("11S", [orig_mt, date]),
        ("79", wrap(narrative.strip(), 50, 35)[0]),
        # A copy of the original's mandatory field :32A: lets the receiver match the payment.
        ("32A", f"{yymmdd(tx.get('OrgnlIntrBkSttlmDt'))}{ccy}{mt_amount(amt)}" if (amt and tx.get("OrgnlIntrBkSttlmDt")) else ""),
    ]
    if not fields[0][1]:
        raise Decline("The camt.056 has no Assgnmt/Id for :20:.")
    if not date:
        raise Decline("No original settlement date or creation date for :11S:.")
    tx.touch("OrgnlEndToEndId", "OrgnlGrpInf/OrgnlMsgNmId")
    out.message = mt_message("192", doc.get("Assgnmt/Assgnr/Agt/FinInstnId/BICFI"),
                             doc.get("Assgnmt/Assgne/Agt/FinInstnId/BICFI"), fields, tx.get("OrgnlUETR").lower())
    out.drop("Assgnmt/CreDtTm", doc.get("Assgnmt/CreDtTm"), "MT192 has no creation time.")
    out.drop("OrgnlGrpInf/OrgnlMsgId", tx.get("OrgnlGrpInf/OrgnlMsgId"), "MT192 refers to the original by its :20: (field 21).")
    out.drop("CxlId", tx.get("CxlId"), "MT192 has one reference, :20:, which takes Assgnmt/Id.")
    out.leftovers(doc, "MT192")
    return out


# ── pacs.002 / pain.002 → MT199 ─────────────────────────────────────────────
def _status_mt199(src: str, kind: str) -> Out:
    doc, out = X.parse(src), Out()
    txs = doc.all("TxInfAndSts")
    grp = doc.get("OrgnlGrpInfAndSts/GrpSts", "GrpSts")
    lines = []
    if kind == "pain.002":
        ref = doc.get("OrgnlPmtInfAndSts/OrgnlPmtInfId", "OrgnlEndToEndId")
        if grp:
            lines.append(f"Your instruction {doc.get('OrgnlGrpInfAndSts/OrgnlMsgId')}: {grp} ({STATUS_TEXT.get(grp, 'see code')}).")
    else:
        ref = doc.get("OrgnlInstrId", "OrgnlEndToEndId")
        if grp:
            lines.append(f"Message {doc.get('OrgnlGrpInfAndSts/OrgnlMsgId')}: {grp} ({STATUS_TEXT.get(grp, 'see code')}).")
    for t in txs:
        sts = t.get("TxSts")
        who = t.get("OrgnlInstrId") or t.get("OrgnlEndToEndId")
        t.touch("OrgnlInstrId", "OrgnlEndToEndId")
        s = f"Payment {who}: {sts} ({STATUS_TEXT.get(sts, 'see code')})."
        rsn, info = t.get("StsRsnInf/Rsn/Cd"), " ".join(i.text() for i in t.all("StsRsnInf/AddtlInf"))
        for i in t.all("StsRsnInf/AddtlInf"):
            t.used.add(i.el)
        if rsn:
            s += f" Reason {rsn}" + (f": {info}" if info else "") + "."
        uetr = t.get("OrgnlUETR")
        if uetr:
            s += f" UETR {uetr}."
        amt, ccy = t.amount("OrgnlTxRef/IntrBkSttlmAmt") if t.node("OrgnlTxRef/IntrBkSttlmAmt") else ("", "")
        if amt:
            s += f" Amount {ccy} {mt_amount(amt)}."
        when = t.get("AccptncDtTm")
        if when:
            s += f" Accepted {when[:10]}."
        lines.append(s)
    if not lines:
        raise Decline("The status report has no group or transaction status.")
    narrative = []
    for s in lines:
        narrative += wrap(s, 50)[0]
    fields = [("20", doc.get("GrpHdr/MsgId")[:16]), ("21", ref[:16]), ("79", narrative[:35])]
    sender = doc.get("GrpHdr/InstgAgt/FinInstnId/BICFI") or doc.get("GrpHdr/InitgPty/Id/OrgId/AnyBIC")
    receiver = doc.get("GrpHdr/InstdAgt/FinInstnId/BICFI")
    doc.touch("OrgnlGrpInfAndSts/OrgnlMsgNmId", "OrgnlPmtInfAndSts/OrgnlPmtInfId")
    out.message = mt_message("199", sender, receiver, fields)
    out.note("MT199 is free text: the status is written out in :79: for a person to read; a system can't act on it.")
    if not out.message.startswith("{1:"):
        out.note("The report doesn't give both banks' BICs, so blocks 1 and 2 are left for you to add.")
    out.drop("GrpHdr/CreDtTm", doc.get("GrpHdr/CreDtTm"), "MT199 has no creation time.")
    out.leftovers(doc, "MT199")
    return out


def pacs002_mt199(src: str) -> Out:
    return _status_mt199(src, "pacs.002")


def pain002_mt199(src: str) -> Out:
    return _status_mt199(src, "pain.002")
