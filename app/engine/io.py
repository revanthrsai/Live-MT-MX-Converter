"""
Reading and writing ISO 20022 XML and SWIFT MT for the rules engine.

Readers remember which elements / fields were used, so whatever a translation
didn't carry over can be listed under "dropped" instead of disappearing.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from lxml import etree

from .. import checks


class Decline(Exception):
    """The deterministic engine cannot process this message reliably."""


# ── small formatting helpers ────────────────────────────────────────────────
def mt_amount(amount: str) -> str:
    """400.00 -> 400,00 ; 150000 -> 150000,"""
    a = (amount or "").strip()
    if not a:
        return ""
    return a.replace(".", ",") if "." in a else a + ","


def mx_amount(mt: str, ccy: str = "") -> str:
    """400,00 -> 400.00 ; 120, -> 120.00 (padded to the currency's decimals)."""
    raw = (mt or "").strip().replace(",", ".")
    if raw.endswith("."):
        raw = raw[:-1]
    try:
        d = Decimal(raw)
    except InvalidOperation:
        raise Decline(f"\"{mt}\" is not an amount.")
    places = checks.CCY_DECIMALS.get(ccy, 2)
    return str(d.quantize(Decimal(1).scaleb(-places))) if places else str(d.quantize(Decimal(1)))


def yymmdd(iso: str) -> str:
    iso = (iso or "")[:10]
    return iso[2:4] + iso[5:7] + iso[8:10] if checks.real_date(iso) else ""


def iso_date(yymmdd_: str) -> str:
    return checks.yymmdd_to_iso(yymmdd_) or ""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_uetr() -> str:
    return str(uuid.uuid4())


def wrap(text: str, width: int = 35, max_lines: int | None = None) -> tuple[list[str], bool]:
    """Split text into MT lines; returns (lines, cut) where cut means text was lost."""
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        while len(w) > width:  # a single long token
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(w[:width])
            w = w[width:]
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if max_lines is not None and len(lines) > max_lines:
        return lines[:max_lines], True
    return lines, False


def is_iban(acct: str) -> bool:
    a = re.sub(r"\s+", "", acct or "").upper()
    return bool(re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", a)) and a[:2] in checks.IBAN_LENGTHS and checks.iban_ok(a)[0]


def bic_ok(bic: str) -> bool:
    return bool(checks.BIC_RE.fullmatch(bic or ""))


# ── ISO 20022 reader ────────────────────────────────────────────────────────
def _xp(path: str) -> str:
    return ".//" + "//".join(f"*[local-name()='{p}']" for p in path.split("/"))


class X:
    """Path lookups on an XML subtree. "Dbtr/Nm" means an Nm somewhere under a Dbtr."""

    def __init__(self, el, used: set | None = None):
        self.el = el
        self.used = used if used is not None else set()

    @classmethod
    def parse(cls, xml: str) -> "X":
        root, err = checks._parse_xml(xml or "")
        if root is None:
            raise Decline(f"The XML doesn't parse: {err}")
        return cls(root)

    def _find(self, path: str):
        found = self.el.xpath(_xp(path))
        return found

    def node(self, path: str):
        f = self._find(path)
        return X(f[0], self.used) if f else None

    def all(self, path: str) -> list["X"]:
        return [X(e, self.used) for e in self._find(path)]

    def get(self, *paths: str) -> str:
        for p in paths:
            for e in self._find(p):
                t = (e.text or "").strip()
                if t:
                    self.used.add(e)
                    return t
        return ""

    def attr(self, path: str, name: str) -> str:
        f = self._find(path)
        return (f[0].get(name) or "") if f else ""

    def amount(self, path: str) -> tuple[str, str]:
        """(amount, currency) of the first element at path."""
        f = self._find(path)
        if not f:
            return "", ""
        self.used.add(f[0])
        return (f[0].text or "").strip(), f[0].get("Ccy") or ""

    def touch(self, *paths: str):
        """Mark elements as handled even though they're not copied (structural fields)."""
        for p in paths:
            for e in self._find(p):
                self.used.add(e)

    def text(self) -> str:
        return (self.el.text or "").strip()

    def unused(self) -> list[dict]:
        """Leaf values in this subtree that the translation never used."""
        out = []
        for e in self.el.iter():
            if not isinstance(e.tag, str) or len(e) or not (e.text or "").strip() or e in self.used:
                continue
            parts = checks.path_of(e).split(" › ")[1:]  # without the message root
            out.append({"field": "/".join(parts[-3:]), "value": (e.text or "").strip()[:70]})
        return out


# ── ISO 20022 writer ────────────────────────────────────────────────────────
class MXWriter:
    """E("Tag", child, child, text=..., Ccy=...) builds elements; empty ones are dropped."""

    def __init__(self, version: str):
        self.version = version
        self.ns = f"urn:iso:std:iso:20022:tech:xsd:{version}"

    def E(self, tag: str, *kids, text: str | None = None, **attrs):
        kids = [k for k in kids if k is not None]
        if text is None and not kids:
            return None
        if text is not None and str(text).strip() == "":
            return None
        el = etree.Element(f"{{{self.ns}}}{tag}", nsmap={None: self.ns})
        for k, v in attrs.items():
            if v:
                el.set(k, v)
        if text is not None:
            el.text = str(text)
        for k in kids:
            el.append(k)
        return el

    def T(self, tag: str, value: str | None):
        """A text element, or nothing when the value is empty."""
        return self.E(tag, text=value) if value else None

    def amt(self, tag: str, amount: str, ccy: str):
        return self.E(tag, text=amount, Ccy=ccy) if amount else None

    def bic_agent(self, tag: str, bic: str):
        return self.E(tag, self.E("FinInstnId", self.T("BICFI", bic))) if bic else None

    def account(self, tag: str, acct: str):
        if not acct:
            return None
        a = re.sub(r"\s+", "", acct)
        ident = self.E("IBAN", text=a.upper()) if is_iban(a) else self.E("Othr", self.T("Id", acct.strip()))
        return self.E(tag, self.E("Id", ident))

    def party(self, tag: str, p: "Party", wrap_pty: bool = False):
        if p is None or not (p.name or p.bic or p.address or p.country):
            return None
        adr = self.E("PstlAdr", self.T("TwnNm", p.town), self.T("Ctry", p.country),
                     *[self.T("AdrLine", x[:70]) for x in p.address[:3]])
        ident = self.E("Id", self.E("OrgId", self.T("AnyBIC", p.bic))) if p.bic else None
        inner = [self.T("Nm", p.name[:140] if p.name else None), adr, ident]
        if wrap_pty:
            return self.E(tag, self.E("Pty", *inner))
        return self.E(tag, *inner)

    def document(self, root_tag: str, *kids) -> str:
        root = self.E(root_tag, *kids)
        doc = self.E("Document", root)
        etree.indent(doc, space="  ")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + etree.tostring(doc, encoding="unicode")


# ── parties (names, addresses, accounts) ────────────────────────────────────
class Party:
    def __init__(self, name="", address=None, country="", town="", account="", bic=""):
        self.name, self.address, self.country, self.town = name, list(address or []), country, town
        self.account, self.bic = account, bic

    @classmethod
    def from_mx(cls, x: X, party: str, account: str | None = None) -> "Party":
        """party is e.g. "Dbtr" (or "Dbtr/Pty"); account e.g. "DbtrAcct"."""
        node = x.node(party)
        p = cls()
        if node is not None:
            p.name = node.get("Nm")
            p.bic = node.get("Id/OrgId/AnyBIC", "AnyBIC")
            street = " ".join(v for v in (node.get("PstlAdr/StrtNm"), node.get("PstlAdr/BldgNb")) if v)
            town = " ".join(v for v in (node.get("PstlAdr/PstCd"), node.get("PstlAdr/TwnNm")) if v)
            p.country = node.get("PstlAdr/Ctry")
            lines = [l.text() for l in node.all("PstlAdr/AdrLine") if l.text()]
            for l in node.all("PstlAdr/AdrLine"):
                x.used.add(l.el)
            p.address = lines + [", ".join(v for v in (street, town) if v)] if (street or town) else lines
            p.address = [a for a in p.address if a]
        if account:
            p.account = x.get(f"{account}/Id/IBAN", f"{account}/Id/Othr/Id")
        return p

    def mt_lines(self, max_lines: int = 4) -> tuple[list[str], bool]:
        """/account, name, address lines (35 characters each) for :50K: / :59:."""
        out = [f"/{self.account}"[:35]] if self.account else []
        cut = False
        name_lines, c1 = wrap(self.name, 35)
        out += name_lines
        addr = list(self.address)
        if self.country and not any(a.endswith(self.country) for a in addr):
            if addr:
                addr[-1] = f"{addr[-1]}, {self.country}"
            else:
                addr = [self.country]
        for a in addr:
            ls, _ = wrap(a, 35)
            out += ls
        if len(out) > max_lines:
            out, cut = out[:max_lines], True
        return out, cut

    @classmethod
    def from_mt(cls, option: str, lines: list[str]) -> "Party":
        """Party fields from :50a: / :59a: lines (options K, F, A or none)."""
        p = cls()
        lines = list(lines)
        if lines and lines[0].startswith("/"):
            p.account = lines.pop(0)[1:].strip()
        if option == "A":
            p.bic = lines[0].strip() if lines else ""
            return p
        if option == "F":
            names, addr = [], []
            for ln in lines:
                m = re.match(r"([1-8])/(.*)", ln)
                if not m:
                    continue
                k, v = m.group(1), m.group(2).strip()
                if k == "1":
                    names.append(v)
                elif k == "2":
                    addr.append(v)
                elif k == "3":
                    cc = re.match(r"([A-Z]{2})/?(.*)", v)
                    if cc:
                        p.country, p.town = cc.group(1), cc.group(2).strip()
                else:
                    addr.append(v)
            p.name, p.address = " ".join(names), addr
            return p
        if lines:
            p.name = lines[0].strip()
            p.address = [l.strip() for l in lines[1:] if l.strip()]
        return p


# ── SWIFT MT reader ─────────────────────────────────────────────────────────
class M:
    def __init__(self, text: str, fields: list | None = None):
        self.text = text or ""
        self.fields = fields if fields is not None else checks.mt_fields(self.text)
        self.used: set[int] = set()
        self._base = 0

    def _sub(self, start: int, end: int) -> "M":
        m = M(self.text, self.fields[start:end])
        m.used, m._base = self.used, self._base + start
        return m

    def _idx(self, tag: str) -> list[int]:
        return [i for i, (t, _) in enumerate(self.fields) if t == tag]

    def full(self, *tags: str) -> str:
        for tag in tags:
            for i in self._idx(tag):
                self.used.add(self._base + i)
                return self.fields[i][1]
        return ""

    def get(self, *tags: str) -> str:
        return self.full(*tags).split("\n")[0].strip()

    def lines(self, *tags: str) -> list[str]:
        return [x.rstrip() for x in self.full(*tags).split("\n") if x.strip()]

    def option(self, num: str) -> tuple[str, list[str]]:
        """(option letter, lines) for field 50a / 59a etc., e.g. ("K", [...])."""
        for i, (t, v) in enumerate(self.fields):
            if t[:2] == num and (len(t) == 2 or t[2:].isalpha()):
                self.used.add(self._base + i)
                return t[2:], [x.rstrip() for x in v.split("\n") if x.strip()]
        return "", []

    def has(self, tag: str) -> bool:
        return bool(self._idx(tag))

    def all(self, tag: str) -> list[str]:
        out = []
        for i in self._idx(tag):
            self.used.add(self._base + i)
            out.append(self.fields[i][1])
        return out

    def split_on(self, tag: str) -> tuple["M", list["M"]]:
        """Sequence A (fields before the first tag) and one sequence per occurrence of tag."""
        idx = self._idx(tag)
        if not idx:
            return self, []
        seqs = [self._sub(a, b) for a, b in zip(idx, idx[1:] + [len(self.fields)])]
        return self._sub(0, idx[0]), seqs

    def touch(self, *tags: str):
        for tag in tags:
            for i in self._idx(tag):
                self.used.add(self._base + i)

    # header blocks
    def _addr(self, block: str) -> str:
        if block == "1":
            m = re.search(r"\{1:F\d\d([A-Z0-9]{12})", self.text)
        else:
            m = re.search(r"\{2:[IO]\d{3}(?:\d{10}\d{6})?([A-Z0-9]{12})", self.text)
        if not m:
            return ""
        lt = m.group(1)
        return lt[:8] if lt[9:12] == "XXX" else lt[:8] + lt[9:12]

    def sender(self) -> str:
        return self._addr("1")

    def receiver(self) -> str:
        return self._addr("2")

    def mt_type(self) -> str:
        m = re.search(r"\{2:[IO](\d{3})", self.text)
        return m.group(1) if m else ""

    def uetr(self) -> str:
        m = re.search(r"\{121:([0-9a-fA-F-]{36})\}", self.text)
        return m.group(1).lower() if m else ""

    def unused(self) -> list[dict]:
        return [{"field": f":{t}:", "value": v.replace("\n", " ")[:70]}
                for i, (t, v) in enumerate(self.fields) if (self._base + i) not in self.used]


# ── SWIFT MT writer ─────────────────────────────────────────────────────────
def lt_address(bic: str, letter: str) -> str:
    b = (bic or "").upper()
    return b[:8] + letter + (b[8:11] if len(b) == 11 else "XXX")


def mt_message(mt_type: str, sender: str, receiver: str, fields: list[tuple[str, list[str] | str]], uetr: str = "") -> str:
    """Blocks 1-4. Header blocks are written only when both BICs are known."""
    body = []
    for tag, val in fields:
        lines = [val] if isinstance(val, str) else list(val or [])
        lines = [l for l in lines if l is not None and str(l) != ""]
        if not lines:
            continue
        body.append(f":{tag}:" + "\n".join(lines))
    b4 = "{4:\n" + "\n".join(body) + "\n-}"
    if not (bic_ok(sender) and bic_ok(receiver)):
        return b4
    head = "{1:F01" + lt_address(sender, "A") + "0000000000}{2:I" + mt_type + lt_address(receiver, "X") + "N}"
    if uetr:
        head += "{3:{121:" + uetr.lower() + "}}"
    return head + b4


# ── what a translation returns ──────────────────────────────────────────────
class Out:
    def __init__(self):
        self.message = ""
        self.filled: list[dict] = []
        self.dropped: list[dict] = []
        self.notes: list[str] = []
        self.parts: list[tuple[str, str]] = []  # (source piece, message) when one MX became several MTs

    def fill(self, field: str, value: str, reason: str):
        self.filled.append({"field": field, "value": value, "reason": reason})

    def drop(self, field: str, value: str, reason: str):
        if value:
            self.dropped.append({"field": field, "value": value, "reason": reason})

    def note(self, text: str):
        self.notes.append(text)

    def leftovers(self, reader, target: str):
        """Everything the reader never used goes under dropped, so nothing disappears silently."""
        seen = {(d["field"], d["value"]) for d in self.dropped}
        for d in reader.unused():
            if (d["field"], d["value"]) not in seen:
                self.dropped.append({**d, "reason": f"No field for it in {target}."})
