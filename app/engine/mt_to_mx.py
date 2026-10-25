"""SWIFT MT → ISO 20022, by rule. Element order follows the CBPR+ schemas."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal

from ..formats import MESSAGE_VERSIONS
from .io import Decline, M, MXWriter, Out, Party, iso_date, mx_amount, new_uetr, now_iso, wrap

CHRG_TO_MX = {"SHA": "SHAR", "OUR": "DEBT", "BEN": "CRED"}


def _msg_id(out: Out, ref: str, field: str = "GrpHdr/MsgId") -> str:
    v = f"{ref[:20]}-{datetime.now(timezone.utc):%y%m%d%H%M%S}"[:35]
    out.fill(field, v, "Generated: the MT has no message-level identifier.")
    return v


def _created(out: Out, field: str = "GrpHdr/CreDtTm") -> str:
    v = now_iso()
    out.fill(field, v, "Generated: the time of this translation.")
    return v


def _amt32(m: M, tag: str) -> tuple[str, str, str]:
    """(iso date, currency, amount) from :32A: (or ccy+amount from :32B:)."""
    v = m.get(tag)
    mm = re.fullmatch(r"(\d{6})?([A-Z]{3})(\d[\d,]*)", v or "")
    if not mm:
        raise Decline(f":{tag}: is missing or not in the YYMMDD + currency + amount form.")
    d = iso_date(mm.group(1)) if mm.group(1) else ""
    if mm.group(1) and not d:
        raise Decline(f"The date in :{tag}: is not a real date.")
    return d, mm.group(2), mx_amount(mm.group(3), mm.group(2))


def _remit(lines: list[str]) -> str:
    return " ".join(l.strip() for l in lines if l.strip())[:140]


def _party(m: M, num: str) -> Party:
    opt, lines = m.option(num)
    return Party.from_mt(opt, lines) if lines else Party()


def _sender_receiver(m: M) -> tuple[str, str]:
    return m.sender(), m.receiver()


# ── MT103 → pacs.008 ────────────────────────────────────────────────────────
def mt103_pacs008(src: str) -> Out:
    m, out, w = M(src), Out(), MXWriter(MESSAGE_VERSIONS["pacs.008"])
    ref = m.get("20")
    if not ref:
        raise Decline("The MT103 has no :20:.")
    dt, ccy, amt = _amt32(m, "32A")
    sender, receiver = _sender_receiver(m)
    lines70 = m.lines("70")
    roc = re.match(r"/ROC/([^/\s]+)", lines70[0]) if lines70 else None
    e2e = roc.group(1) if roc else "NOTPROVIDED"
    if not roc:
        out.fill("PmtId/EndToEndId", "NOTPROVIDED", "The MT103 has no /ROC/ in :70:, so there's no end-to-end reference.")
    rmt = _remit(lines70[1:] if roc else lines70)
    uetr = m.uetr()
    if not uetr:
        uetr = new_uetr()
        out.fill("PmtId/UETR", uetr, "Generated: the MT103 has no {121:} in block 3.")
    i_amt = ""
    if m.has("33B"):
        _, i_ccy, i_amt = _amt32(m, "33B")
    dbtr, cdtr = _party(m, "50"), _party(m, "59")
    if not (dbtr.name or dbtr.bic):
        raise Decline("The MT103 has no ordering customer in :50a:.")
    dbtr_agt = (m.lines("52A") or [""])[-1] or sender
    cdtr_agt = (m.lines("57A") or [""])[-1] or receiver
    if not m.has("52A"):
        out.fill("DbtrAgt", sender, "No :52A:, so the debtor agent is the sender (block 1).")
    if not m.has("57A"):
        out.fill("CdtrAgt", receiver, "No :57A:, so the creditor agent is the receiver (block 2).")
    if not (dbtr_agt and cdtr_agt):
        raise Decline("The debtor or creditor agent BIC can't be found (no :52A:/:57A: and no header blocks).")
    chrg = CHRG_TO_MX.get(m.get("71A"))
    m.touch("23B")
    tx = w.E("CdtTrfTxInf",
             w.E("PmtId", w.T("InstrId", ref), w.T("EndToEndId", e2e), w.T("UETR", uetr)),
             w.amt("IntrBkSttlmAmt", amt, ccy),
             w.T("IntrBkSttlmDt", dt),
             w.amt("InstdAmt", i_amt, i_ccy) if i_amt else None,
             w.T("ChrgBr", chrg),
             w.bic_agent("IntrmyAgt1", (m.lines("56A") or [""])[-1]),
             w.party("Dbtr", dbtr),
             w.account("DbtrAcct", dbtr.account),
             w.bic_agent("DbtrAgt", dbtr_agt),
             w.bic_agent("CdtrAgt", cdtr_agt),
             w.party("Cdtr", cdtr),
             w.account("CdtrAcct", cdtr.account),
             w.E("RmtInf", w.T("Ustrd", rmt)) if rmt else None)
    grp = w.E("GrpHdr",
              w.T("MsgId", _msg_id(out, ref)), w.T("CreDtTm", _created(out)), w.T("NbOfTxs", "1"),
              w.E("SttlmInf", w.T("SttlmMtd", "INDA")),
              w.bic_agent("InstgAgt", sender), w.bic_agent("InstdAgt", receiver))
    out.fill("SttlmInf/SttlmMtd", "INDA", "The MT103 doesn't say; INDA (settled over accounts) is the usual case.")
    out.message = w.document("FIToFICstmrCdtTrf", grp, tx)
    out.leftovers(m, "pacs.008")
    return out


# ── MT103 RETN → pacs.004 ───────────────────────────────────────────────────
def mt103retn_pacs004(src: str) -> Out:
    m, out, w = M(src), Out(), MXWriter(MESSAGE_VERSIONS["pacs.004"])
    ref = m.get("20")
    dt, ccy, amt = _amt32(m, "32A")
    sender, receiver = _sender_receiver(m)
    l72 = m.lines("72")
    code = next((mm.group(1) for x in l72[1:] for mm in [re.match(r"/([A-Z0-9]{4})/(.*)", x)] if mm), "")
    info = next((mm.group(2).strip() for x in l72[1:] for mm in [re.match(r"/([A-Z0-9]{4})/(.*)", x)] if mm), "")
    mref = next((x[6:].strip() for x in l72 if x.startswith("/MREF/")), "")
    if not code:
        raise Decline("The :72: of the return has no /reason code/ on its second line.")
    uetr = m.uetr()
    if not uetr:
        uetr = new_uetr()
        out.fill("OrgnlUETR", uetr, "Generated: the return has no {121:}. Replace it with the original payment's UETR.")
    # Parties swap back: :50K: of the return is the original creditor, :59: the original debtor.
    orig_cdtr, orig_dbtr = _party(m, "50"), _party(m, "59")
    m.touch("23B")
    out.fill("OrgnlGrpInf/OrgnlMsgId", "NOTPROVIDED", "An MT103 return doesn't carry the original message's MsgId.")
    out.fill("OrgnlGrpInf/OrgnlMsgNmId", MESSAGE_VERSIONS["pacs.008"], "The returned payment was a customer credit transfer.")
    out.fill("OrgnlEndToEndId", "NOTPROVIDED", "An MT103 return doesn't carry the original end-to-end reference.")
    chain = w.E("RtrChain",
                w.party("Dbtr", orig_dbtr, wrap_pty=True), w.account("DbtrAcct", orig_dbtr.account),
                w.party("Cdtr", orig_cdtr, wrap_pty=True), w.account("CdtrAcct", orig_cdtr.account))
    tx = w.E("TxInf",
             w.T("RtrId", ref),
             w.E("OrgnlGrpInf", w.T("OrgnlMsgId", "NOTPROVIDED"), w.T("OrgnlMsgNmId", MESSAGE_VERSIONS["pacs.008"])),
             w.T("OrgnlInstrId", mref),
             w.T("OrgnlEndToEndId", "NOTPROVIDED"),
             w.T("OrgnlUETR", uetr),
             w.amt("RtrdIntrBkSttlmAmt", amt, ccy),
             w.T("IntrBkSttlmDt", dt),
             w.T("ChrgBr", CHRG_TO_MX.get(m.get("71A"))),
             chain,
             w.E("RtrRsnInf", w.E("Rsn", w.T("Cd", code)), w.T("AddtlInf", info[:105])))
    grp = w.E("GrpHdr",
              w.T("MsgId", _msg_id(out, ref)), w.T("CreDtTm", _created(out)), w.T("NbOfTxs", "1"),
              w.E("SttlmInf", w.T("SttlmMtd", "INDA")),
              w.bic_agent("InstgAgt", sender), w.bic_agent("InstdAgt", receiver))
    out.message = w.document("PmtRtr", grp, tx)
    out.leftovers(m, "pacs.004")
    return out


# ── MT101 → pain.001 ────────────────────────────────────────────────────────
def mt101_pain001(src: str) -> Out:
    m, out, w = M(src), Out(), MXWriter(MESSAGE_VERSIONS["pain.001"])
    seq_a, seqs = m.split_on("21")
    if not seqs:
        raise Decline("The MT101 has no transactions (no :21:).")
    ref = seq_a.get("20")
    exec_dt = iso_date(seq_a.get("30"))
    if not exec_dt:
        raise Decline("The MT101 has no valid :30: execution date.")
    seq_a.touch("28D")
    dbtr = _party(seq_a, "50")
    if not dbtr.name and not dbtr.account:
        raise Decline("The ordering customer (:50H:/:50F: in sequence A) is missing; the engine needs it in sequence A.")
    dbtr_agt = (seq_a.lines("52A") or [""])[-1] or m.receiver()
    txs, total = [], Decimal(0)
    for s in seqs:
        _, ccy, amt = _amt32(s, "32B")
        total += Decimal(amt)
        cdtr = _party(s, "59")
        lines70 = s.lines("70")
        txs.append(w.E("CdtTrfTxInf",
                       w.E("PmtId", w.T("EndToEndId", s.get("21"))),
                       w.E("Amt", w.amt("InstdAmt", amt, ccy)),
                       w.T("ChrgBr", CHRG_TO_MX.get(s.get("71A"))),
                       w.bic_agent("CdtrAgt", (s.lines("57A") or [""])[-1]),
                       w.party("Cdtr", cdtr),
                       w.account("CdtrAcct", cdtr.account),
                       w.E("RmtInf", w.T("Ustrd", _remit(lines70))) if lines70 else None))
    n, ctrl = str(len(seqs)), format(total, "f")
    pmt = w.E("PmtInf",
              w.T("PmtInfId", ref), w.T("PmtMtd", "TRF"), w.T("NbOfTxs", n), w.T("CtrlSum", ctrl),
              w.E("ReqdExctnDt", w.T("Dt", exec_dt)),
              w.party("Dbtr", dbtr), w.account("DbtrAcct", dbtr.account), w.bic_agent("DbtrAgt", dbtr_agt),
              *txs)
    grp = w.E("GrpHdr", w.T("MsgId", ref), w.T("CreDtTm", _created(out)), w.T("NbOfTxs", n), w.T("CtrlSum", ctrl),
              w.E("InitgPty", w.T("Nm", dbtr.name or "NOTPROVIDED")))
    out.fill("PmtInf/PmtInfId", ref, "MT101 has no separate payment-information reference, so :20: is used.")
    if not dbtr.name:
        out.fill("InitgPty/Nm", "NOTPROVIDED", "The ordering customer has no name in the MT101.")
    out.message = w.document("CstmrCdtTrfInitn", grp, pmt)
    out.leftovers(m, "pain.001")
    return out


# ── MT104 → pain.008 ────────────────────────────────────────────────────────
def mt104_pain008(src: str) -> Out:
    m, out, w = M(src), Out(), MXWriter(MESSAGE_VERSIONS["pain.008"])
    seq_a, seqs = m.split_on("21")
    if not seqs:
        raise Decline("The MT104 has no transactions (no :21:).")
    ref = seq_a.get("20")
    coll_dt = iso_date(seq_a.get("30"))
    if not coll_dt:
        raise Decline("The MT104 has no valid :30: collection date.")
    cdtr = _party(seq_a, "50")
    first_b = True
    txs, total = [], Decimal(0)
    for s in seqs:
        # Sequence C (totals) trails the last transaction: its :32B: and :19: are not a new transaction.
        amts = s.all("32B")
        _, ccy, amt = _amt32(M(s.text, [("32B", amts[0])]), "32B")
        s.touch("19")
        total += Decimal(amt)
        if not (cdtr.name or cdtr.account):
            cdtr = _party(s, "50")
        else:
            s.option("50")
        dbtr = _party(s, "59")
        mndt = s.get("21C")
        if not mndt:
            mndt = "NOTPROVIDED"
            if first_b:
                out.fill("MndtRltdInf/MndtId", "NOTPROVIDED", "The MT104 has no :21C: mandate reference.")
        first_b = False
        lines70 = s.lines("70")
        s.touch("71A")
        txs.append(w.E("DrctDbtTxInf",
                       w.E("PmtId", w.T("EndToEndId", s.get("21"))),
                       w.amt("InstdAmt", amt, ccy),
                       w.E("DrctDbtTx", w.E("MndtRltdInf", w.T("MndtId", mndt))),
                       w.bic_agent("DbtrAgt", (s.lines("57A") or [""])[-1]),
                       w.party("Dbtr", dbtr),
                       w.account("DbtrAcct", dbtr.account),
                       w.E("RmtInf", w.T("Ustrd", _remit(lines70))) if lines70 else None))
    if not (cdtr.name or cdtr.account):
        raise Decline("The creditor (:50K:) is missing.")
    n, ctrl = str(len(seqs)), format(total, "f")
    cdtr_agt = (seq_a.lines("52A") or [""])[-1] or m.sender()
    pmt = w.E("PmtInf",
              w.T("PmtInfId", ref), w.T("PmtMtd", "DD"), w.T("NbOfTxs", n), w.T("CtrlSum", ctrl),
              w.T("ReqdColltnDt", coll_dt),
              w.party("Cdtr", cdtr), w.account("CdtrAcct", cdtr.account), w.bic_agent("CdtrAgt", cdtr_agt),
              *txs)
    grp = w.E("GrpHdr", w.T("MsgId", ref), w.T("CreDtTm", _created(out)), w.T("NbOfTxs", n), w.T("CtrlSum", ctrl),
              w.E("InitgPty", w.T("Nm", cdtr.name or "NOTPROVIDED")))
    out.fill("PmtInf/PmtInfId", ref, "MT104 has no separate payment-information reference, so :20: is used.")
    out.message = w.document("CstmrDrctDbtInitn", grp, pmt)
    out.leftovers(m, "pain.008")
    return out


# ── MT940 → camt.053 ────────────────────────────────────────────────────────
_L61 = re.compile(r"(\d{6})(\d{4})?(R?[CD])([A-Z]?)(\d[\d,]*)([SNF][A-Z0-9]{3})([^/\n]*?)(?://([^\n]{1,16}))?(?:\n(.*))?$", re.S)
_BAL = re.compile(r"([CD])(\d{6})([A-Z]{3})(\d[\d,]*)")


def _balance(w: MXWriter, code: str, v: str):
    mm = _BAL.fullmatch(v or "")
    if not mm:
        return None, ""
    ccy = mm.group(3)
    return w.E("Bal",
               w.E("Tp", w.E("CdOrPrtry", w.T("Cd", code))),
               w.amt("Amt", mx_amount(mm.group(4), ccy), ccy),
               w.T("CdtDbtInd", "CRDT" if mm.group(1) == "C" else "DBIT"),
               w.E("Dt", w.T("Dt", iso_date(mm.group(2))))), ccy


def mt940_camt053(src: str) -> Out:
    m, out, w = M(src), Out(), MXWriter(MESSAGE_VERSIONS["camt.053"])
    ref, acct = m.get("20"), m.get("25", "25P")
    seq = (m.get("28C") or "1").split("/")[0]
    opening, ccy = _balance(w, "OPBD", m.get("60F", "60M"))
    closing, _ = _balance(w, "CLBD", m.get("62F", "62M"))
    if opening is None or closing is None:
        raise Decline("The MT940 needs valid :60F: and :62F: balances.")
    avail, _ = _balance(w, "CLAV", m.get("64"))
    fwd, _ = _balance(w, "FWAV", m.get("65"))
    entries = []
    for i, (t, v) in enumerate(m.fields):
        if t != "61":
            continue
        m.used.add(i)
        mm = _L61.match(v.strip())
        if not mm:
            raise Decline(f"This :61: line isn't in the standard layout: {v.splitlines()[0][:40]}")
        val = iso_date(mm.group(1))
        book = val
        if mm.group(2):
            y = int(val[:4])
            if mm.group(2)[:2] == "01" and val[5:7] == "12":
                y += 1
            elif mm.group(2)[:2] == "12" and val[5:7] == "01":
                y -= 1
            book = f"{y}-{mm.group(2)[:2]}-{mm.group(2)[2:]}"
        mark = mm.group(3)
        credit = mark in ("C", "RD")
        rev = mark.startswith("R")
        own, svcr = mm.group(7).strip(), (mm.group(8) or "").strip()
        info = ""
        if i + 1 < len(m.fields) and m.fields[i + 1][0] == "86":
            m.used.add(i + 1)
            info = " ".join(x.strip() for x in m.fields[i + 1][1].split("\n") if x.strip())
        refs = w.E("Refs", w.T("EndToEndId", own if own and own != "NONREF" else None))
        entries.append(w.E("Ntry",
                           w.amt("Amt", mx_amount(mm.group(5), ccy), ccy),
                           w.T("CdtDbtInd", "CRDT" if credit else "DBIT"),
                           w.T("RvslInd", "true" if rev else None),
                           w.E("Sts", w.T("Cd", "BOOK")),
                           w.E("BookgDt", w.T("Dt", book)),
                           w.E("ValDt", w.T("Dt", val)),
                           w.T("AcctSvcrRef", svcr or None),
                           w.E("BkTxCd", w.E("Prtry", w.T("Cd", mm.group(6)), w.T("Issr", "SWIFT"))),
                           w.E("NtryDtls", w.E("TxDtls", refs)) if refs is not None else None,
                           w.T("AddtlNtryInf", info[:500] or None)))
    stmt = w.E("Stmt",
               w.T("Id", ref), w.T("ElctrncSeqNb", seq if seq.isdigit() else "1"),
               _acct(w, acct, ccy, m),
               opening, closing, avail, fwd, *entries)
    m.touch("28C")
    grp = w.E("GrpHdr", w.T("MsgId", _msg_id(out, ref)), w.T("CreDtTm", _created(out)))
    out.message = w.document("BkToCstmrStmt", grp, stmt)
    out.leftovers(m, "camt.053")
    return out


def _acct(w: MXWriter, acct: str, ccy: str, m: M):
    """Acct with its owner (the MT receiver) and servicer (the MT sender), so the header BICs aren't lost."""
    owner, servicer = m.receiver(), m.sender()
    return w.E("Acct", _acct_id(w, acct), w.T("Ccy", ccy),
               w.E("Ownr", w.E("Id", w.E("OrgId", w.T("AnyBIC", owner)))) if owner else None,
               w.bic_agent("Svcr", servicer))


def _acct_id(w: MXWriter, acct: str):
    el = w.account("Acct", acct)
    return el[0] if el is not None else None  # the <Id> inside


# ── MT900 / MT910 → camt.054 ────────────────────────────────────────────────
def mt9x0_camt054(src: str) -> Out:
    m, out, w = M(src), Out(), MXWriter(MESSAGE_VERSIONS["camt.054"])
    t = m.mt_type()
    if t not in ("900", "910"):
        t = "910" if (m.has("50K") or m.has("50A") or m.has("50F")) else "900"
        out.note(f"There's no block 2 to say MT900 or MT910; it was read as an MT{t}.")
    dt, ccy, amt = _amt32(m, "32A")
    rel = m.get("21")
    credit = t == "910"
    dbtr = _party(m, "50") if credit else Party()
    agt = (m.lines("52A") or [""])[-1]
    refs = w.E("Refs", w.T("EndToEndId", rel if rel and rel != "NONREF" else None))
    pties = w.E("RltdPties", w.party("Dbtr", dbtr, wrap_pty=True), w.account("DbtrAcct", dbtr.account)) if (dbtr.name or dbtr.account) else None
    agts = w.E("RltdAgts", w.bic_agent("DbtrAgt" if credit else "CdtrAgt", agt)) if agt else None
    dtls = w.E("NtryDtls", w.E("TxDtls", refs, pties, agts)) if (refs is not None or pties is not None or agts is not None) else None
    ntry = w.E("Ntry",
               w.amt("Amt", amt, ccy),
               w.T("CdtDbtInd", "CRDT" if credit else "DBIT"),
               w.E("Sts", w.T("Cd", "BOOK")),
               w.E("ValDt", w.T("Dt", dt)),
               dtls)
    ntf = w.E("Ntfctn", w.T("Id", m.get("20")), _acct(w, m.get("25", "25P"), ccy, m), ntry)
    grp = w.E("GrpHdr", w.T("MsgId", _msg_id(out, m.get("20"))), w.T("CreDtTm", _created(out)))
    m.touch("13D")
    out.message = w.document("BkToCstmrDbtCdtNtfctn", grp, ntf)
    out.leftovers(m, "camt.054")
    return out


# ── MT192 → camt.056 ────────────────────────────────────────────────────────
def mt192_camt056(src: str) -> Out:
    m, out, w = M(src), Out(), MXWriter(MESSAGE_VERSIONS["camt.056"])
    ref, orig = m.get("20"), m.get("21")
    s11 = m.lines("11S")
    orig_mt = s11[0].strip() if s11 else ""
    orig_dt = iso_date(s11[1].strip()[:6]) if len(s11) > 1 else ""
    n79 = " ".join(x.strip() for x in m.lines("79"))
    code = re.match(r"/([A-Z0-9]{4})/\s*(.*)", n79)
    sender, receiver = _sender_receiver(m)
    if not (sender and receiver):
        raise Decline("The MT192 has no header blocks, so the assigner and assignee banks are unknown.")
    uetr = m.uetr()
    nm = {"103": MESSAGE_VERSIONS["pacs.008"], "202": MESSAGE_VERSIONS["pacs.009"]}.get(orig_mt, MESSAGE_VERSIONS["pacs.008"])
    out.fill("OrgnlGrpInf/OrgnlMsgId", "NOTPROVIDED", "An MT192 doesn't carry the original message's MsgId.")
    out.fill("OrgnlEndToEndId", "NOTPROVIDED", "An MT192 doesn't carry the original end-to-end reference.")
    if not uetr:
        out.note("The MT192 has no {121:}, so OrgnlUETR is left out. Add the original payment's UETR if you have it.")
    i_dt, i_ccy, i_amt = ("", "", "")
    if m.has("32A"):
        i_dt, i_ccy, i_amt = _amt32(m, "32A")
    info = code.group(2) if code else n79
    infos = [info[i:i + 105] for i in range(0, min(len(info), 210), 105)] if info else []
    tx = w.E("TxInf",
             w.E("OrgnlGrpInf", w.T("OrgnlMsgId", "NOTPROVIDED"), w.T("OrgnlMsgNmId", nm)),
             w.T("OrgnlInstrId", orig),
             w.T("OrgnlEndToEndId", "NOTPROVIDED"),
             w.T("OrgnlUETR", uetr or None),
             w.amt("OrgnlIntrBkSttlmAmt", i_amt, i_ccy) if i_amt else None,
             w.T("OrgnlIntrBkSttlmDt", orig_dt or i_dt or None),
             w.E("CxlRsnInf", w.E("Rsn", w.T("Cd", code.group(1))) if code else None, *[w.T("AddtlInf", x) for x in infos]))
    asg = w.E("Assgnmt", w.T("Id", ref),
              w.E("Assgnr", w.E("Agt", w.E("FinInstnId", w.T("BICFI", sender)))),
              w.E("Assgne", w.E("Agt", w.E("FinInstnId", w.T("BICFI", receiver)))),
              w.T("CreDtTm", _created(out, "Assgnmt/CreDtTm")))
    out.message = w.document("FIToFIPmtCxlReq", asg, w.E("Undrlyg", tx))
    out.leftovers(m, "camt.056")
    return out
