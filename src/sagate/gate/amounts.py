"""Amounts a person asked for, read from free text (shared by gateexp and guards so they cannot drift apart).

A number counts unless it is clearly something else: an invoice / reference number, the year of a date, or part of
an account number ("IBAN ... ends with 3000"). "1.8k" = 1800. Both separator styles are read: "1,800.50" and
"1.800,50" are 1800.5; a separator followed by exactly three digits groups thousands ("1.800" = 1800, the larger
reading, so a split payment is not missed). Amounts in words count too ("eighteen hundred", "two thousand five
hundred", "fifty euros").
"""

from __future__ import annotations

import re

_MONEY = re.compile(r"(?:(?:€|\$|£|\b(?:eur|usd|gbp|chf)\b)\s*)?(?<![\w.,#-])(\d[\d.,]*\d|\d)(\s*k\b)?",
                    re.IGNORECASE)
_NOT_AMOUNT = re.compile(r"(?<![a-z])(invoice|bill|order|ref(?:erence)?|no\.?|number|id|account|#)\s*$", re.IGNORECASE)
_DOC_TOTAL = re.compile(r"(?:total|amount due|amount|balance due|sum)\D{0,20}?(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
_POINTS_AT_DOC = re.compile(r"\b(bill|invoice|statement|document|file|letter)\b", re.IGNORECASE)


_EXP = re.compile(r"[eE][+-]?\d+\b")
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
        exp = _EXP.match(text, m.end(1))
        x = float(m.group(1) + exp.group(0)) if exp and not m.group(2) and "," not in m.group(1) \
            else _number(m.group(1))   # 5e3 is 5000, not 5
        if x is None:
            continue
        out.append(x * 1000 if m.group(2) else x)
    return out + _word_amounts(text)


_DOTTED_DATE = re.compile(r"\d{4}[.]\d{1,2}[.]\d{1,2}|\d{1,2}[.]\d{1,2}[.]\d{2}(?:\d{2})?")


def _number(tok: str) -> float | None:
    """'1,800.50' / '1.800,50' / '1.800' / '1800' -> float. The last separator is the decimal point when one or two
    digits follow it; every other separator groups thousands."""
    seps = [i for i, ch in enumerate(tok) if ch in ".,"]
    if not seps:
        return float(tok)
    last = seps[-1]
    whole, frac = tok[:last], tok[last + 1:]
    if _DOTTED_DATE.fullmatch(tok):
        return None                          # 2024.06.01 / 01.06.24: a date, not an amount
    if len(frac) in (1, 2):
        digits = re.sub(r"[.,]", "", whole)
        return float(f"{digits}.{frac}") if digits else None
    if len(frac) == 3 and all(len(g) == 3 for g in re.split(r"[.,]", tok)[1:]):
        return float(re.sub(r"[.,]", "", tok))
    return None


_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                     "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if i > 1}
_SCALES = {"hundred": 100, "thousand": 1000}
_WORD = re.compile(r"[a-z]+", re.IGNORECASE)
_CURRENCY_AFTER = re.compile(r"\s*(euros?|eur|dollars?|usd|pounds?|gbp|francs?|chf)\b", re.IGNORECASE)


def _word_amounts(text: str) -> list[float]:
    """Amounts written in words. A run counts when it holds a tens or scale word ("fifty", "eighteen hundred") or
    is followed by a currency ("five euros"), so "one payment" or "two transfers" do not."""
    out, words = [], [(m.group(0).lower(), m.start(), m.end()) for m in _WORD.finditer(text)]
    i = 0
    while i < len(words):
        j, total, cur, strong = i, 0, 0, False
        while j < len(words):
            w = words[j][0]
            gap = text[words[j - 1][2]:words[j][1]] if j > i else ""
            if j > i and gap.strip(" -") != "":
                break
            if w in _UNITS:
                cur += _UNITS[w]
            elif w in _TENS:
                cur += _TENS[w]; strong = True
            elif w in _SCALES:
                cur = max(cur, 1) * _SCALES[w]; strong = True
                if w == "thousand":
                    total, cur = total + cur, 0
            elif w == "and" and j > i and j + 1 < len(words) and (words[j + 1][0] in _UNITS or words[j + 1][0] in _TENS):
                pass
            else:
                break
            j += 1
        if j > i:
            if strong or _CURRENCY_AFTER.match(text, words[j - 1][2]):
                out.append(float(total + cur))
            i = j
        else:
            i += 1
    return out




def call_amount(args: dict | None) -> float | None:
    """The amount argument of a call. None when the call has none; a number written as text ("1.800,00") is read
    like free text; an amount that cannot be read counts as unlimited, so limit checks fail closed."""
    v = (args or {}).get("amount")
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) if v == v else float("inf")    # NaN compares false with every limit: fail closed
    if re.fullmatch(r"\s*\d+(?:\.\d+)?[eE][+-]?\d+\s*", str(v)):
        return float(v)                        # "5e3" is 5000; "1.800" stays European thousands below
    found = amounts_in(str(v))
    return found[0] if len(found) == 1 else float("inf")
