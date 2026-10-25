"""Deterministic MT ↔ MX conversion engine.

Only explicitly registered source/destination pairs are supported. This
package has no AI fallback, remote dependency or runtime schema fetching.
"""
from __future__ import annotations

import copy
from decimal import Decimal

from .. import checks
from . import mt_to_mx, mx_to_mt
from .io import Decline, Out

TRANSLATORS = {
    ("pacs.008", "MT103"): mx_to_mt.pacs008_mt103,
    ("pacs.004", "MT103 RETN"): mx_to_mt.pacs004_mt103retn,
    ("pain.001", "MT101"): mx_to_mt.pain001_mt101,
    ("pain.008", "MT104"): mx_to_mt.pain008_mt104,
    ("camt.053", "MT940"): mx_to_mt.camt053_mt940,
    ("camt.054", "MT900 / MT910"): mx_to_mt.camt054_mt9x0,
    ("camt.056", "MT192"): mx_to_mt.camt056_mt192,
    ("pacs.002", "MT199"): mx_to_mt.pacs002_mt199,
    ("pain.002", "MT199"): mx_to_mt.pain002_mt199,
    ("MT103", "pacs.008"): mt_to_mx.mt103_pacs008,
    ("MT103 RETN", "pacs.004"): mt_to_mx.mt103retn_pacs004,
    ("MT101", "pain.001"): mt_to_mx.mt101_pain001,
    ("MT104", "pain.008"): mt_to_mx.mt104_pain008,
    ("MT940", "camt.053"): mt_to_mx.mt940_camt053,
    ("MT900 / MT910", "camt.054"): mt_to_mx.mt9x0_camt054,
    ("MT192", "camt.056"): mt_to_mx.mt192_camt056,
}


# An MT carries one of these per message; an MX can carry several. Each one becomes its own MT,
# which is how banks translate them in practice.
SPLIT_ON = {
    ("pacs.008", "MT103"): ("CdtTrfTxInf", "transaction"),
    ("pacs.004", "MT103 RETN"): ("TxInf", "returned transaction"),
    ("pain.001", "MT101"): ("PmtInf", "payment information block"),
    ("pain.008", "MT104"): ("PmtInf", "payment information block"),
    ("camt.053", "MT940"): ("Stmt", "statement"),
    ("camt.054", "MT900 / MT910"): ("Ntry", "entry"),
    ("camt.056", "MT192"): ("TxInf", "underlying transaction"),
}
_CONTAINERS = ("Ntfctn", "Stmt", "Undrlyg", "PmtInf")
_TX = ("CdtTrfTxInf", "DrctDbtTxInf", "TxInf")
_TX_AMT = ("IntrBkSttlmAmt", "InstdAmt", "RtrdIntrBkSttlmAmt")


def _top(root, name):
    """Occurrences of name that aren't nested inside another occurrence of name."""
    out = []
    for el in root.iter():
        if isinstance(el.tag, str) and checks.local(el.tag) == name:
            anc, nested = el.getparent(), False
            while anc is not None:
                if checks.local(anc.tag) == name:
                    nested = True
                    break
                anc = anc.getparent()
            if not nested:
                out.append(el)
    return out


def split_mx(source: str, name: str) -> list[str]:
    """One copy of the message per occurrence of `name`, with the group header's count and control sum redone."""
    from lxml import etree
    root, _ = checks._parse_xml(source)
    if root is None or len(_top(root, name)) < 2:
        return [source]
    parts = []
    n = len(_top(root, name))
    for i in range(n):
        doc = copy.deepcopy(root)
        for j, el in enumerate(_top(doc, name)):
            if j != i:
                el.getparent().remove(el)
        for c in [e for e in doc.iter() if isinstance(e.tag, str) and checks.local(e.tag) in _CONTAINERS and checks.local(e.tag) != name]:
            if not _top(c, name) and c.getparent() is not None and name not in ("PmtInf", "Stmt"):
                c.getparent().remove(c)
        grp = next((e for e in doc.iter() if isinstance(e.tag, str) and checks.local(e.tag) == "GrpHdr"), None)
        if grp is not None:
            txs = [e for e in doc.iter() if isinstance(e.tag, str) and checks.local(e.tag) in _TX]
            kids = {checks.local(k.tag): k for k in grp if isinstance(k.tag, str)}
            if "NbOfTxs" in kids and txs:
                kids["NbOfTxs"].text = str(len(txs))
            if "CtrlSum" in kids and txs:
                total = Decimal(0)
                for tx in txs:
                    a = next((x for x in tx.iter() if isinstance(x.tag, str) and checks.local(x.tag) in _TX_AMT), None)
                    if a is not None and checks.norm_amount(a.text or ""):
                        total += Decimal(checks.norm_amount(a.text))
                places = len(kids["CtrlSum"].text.split(".")[1]) if "." in (kids["CtrlSum"].text or "") else 2
                kids["CtrlSum"].text = f"{total:.{places}f}"
        parts.append(etree.tostring(doc, encoding="unicode"))
    return parts


def supports(src: str | None, tgt: str) -> bool:
    return (src or "", tgt) in TRANSLATORS


def translate(source: str, src: str, tgt: str) -> Out:
    """Raises Decline when the engine can't do this one faithfully."""
    fn = TRANSLATORS.get((src, tgt))
    if fn is None:
        raise Decline(f"No conversion rules are registered for {src} → {tgt}.")
    try:
        split = SPLIT_ON.get((src, tgt))
        pieces = split_mx(source, split[0]) if split else [source]
        if len(pieces) == 1:
            out = fn(source)
            out.parts = [(source, out.message)]
            return out
        outs = [fn(p) for p in pieces]
        out = Out()
        out.message = "\n\n".join(o.message for o in outs)
        out.parts = [(p, o.message) for p, o in zip(pieces, outs)]
        seen = set()
        for o in outs:
            for f in o.filled:
                if (f["field"], f["value"]) not in seen:
                    seen.add((f["field"], f["value"]))
                    out.filled.append(f)
            for d in o.dropped:
                if (d["field"], d["value"]) not in seen:
                    seen.add((d["field"], d["value"]))
                    out.dropped.append(d)
            for n in o.notes:
                if n not in out.notes:
                    out.notes.append(n)
        refs = [checks.mt_fields(m)[0][1].split("\n")[0] if checks.mt_fields(m) else "" for _, m in out.parts]
        dupes = sorted({r for r in refs if r and refs.count(r) > 1})
        if dupes:
            out.notes.insert(0, f"After cutting to 16 characters, several messages share the reference {', '.join(dupes)} in :20:. "
                                "The receiving bank needs each one to be unique, so give them distinct references before sending.")
        mt = tgt.split(" ")[0] if tgt != "MT900 / MT910" else "MT900/MT910"
        out.notes.insert(0, f"The {src} carries {len(pieces)} {split[1]}s and an {mt} carries one, "
                            f"so this is {len(pieces)} {mt} messages, one per {split[1]}.")
        return out
    except Decline:
        raise
    except Exception as e:  # noqa: BLE001 — an engine bug must become a visible conversion error
        raise Decline(f"The conversion rules could not read this message ({type(e).__name__}).") from e


__all__ = ["Decline", "Out", "TRANSLATORS", "split_mx", "supports", "translate"]
