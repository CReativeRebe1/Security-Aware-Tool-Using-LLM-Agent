"""Amounts a person asked for, read from free text (shared by gateexp and guards so they cannot drift apart).

A number counts unless it is clearly something else: an invoice / reference number, the year of a date, or part of
an account number ("IBAN ... ends with 3000"). "1.8k" = 1800.
"""

from __future__ import annotations

import re

_MONEY = re.compile(r"(?:(?:€|\$|£|\b(?:eur|usd|gbp|chf)\b)\s*)?(?<![\w.,#-])(\d[\d,]*(?:\.\d+)?)(\s*k\b)?",
                    re.IGNORECASE)
_NOT_AMOUNT = re.compile(r"(invoice|bill|order|ref(?:erence)?|no\.?|number|id|account|#)\s*$", re.IGNORECASE)
_DOC_TOTAL = re.compile(r"(?:total|amount due|amount|balance due|sum)\D{0,20}?(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
_POINTS_AT_DOC = re.compile(r"\b(bill|invoice|statement|document|file|letter)\b", re.IGNORECASE)


_DATE_PART = re.compile(r"\s*[-/.]\s*\d{1,2}\b")
_ID_CONTEXT = re.compile(r"(starts? with|ends? with|ending (?:in|with)|last \w+ digits|digits|iban|account(?: number)?|"
                         r"acct)\s*(?:is|:)?\s*$", re.IGNORECASE)


def amounts_in(text: str) -> list[float]:
    out = []
    for m in _MONEY.finditer(text):
        if _NOT_AMOUNT.search(text[:m.start()]):
            continue
        if not m.group(2) and _DATE_PART.match(text, m.end(1)) and len(m.group(1)) == 4:
            continue                         # the year of a date (2024-06-01, 2024/06/01), not an amount
        if _ID_CONTEXT.search(text[:m.start()]):
            continue                         # part of an account number ("ends with 3000"), not an amount
        try:
            x = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.append(x * 1000 if m.group(2) else x)
    return out


