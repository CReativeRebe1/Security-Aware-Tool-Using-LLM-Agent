"""Name variation: every case gets its own set of person names, so a model cannot learn shortcuts tied to one
name (the AgentDojo user is always Emma Johnson).

Renaming is consistent inside a case (the same person keeps the same new name everywhere: text, emails, ids), and
first and last names are mapped separately, so cases built on two people sharing a first name ("which Sarah?")
keep that ambiguity. Domains, company names and case ids are never changed. The mapping is stored with each case
(`name_map`), so it can be undone.
"""

from __future__ import annotations

import hashlib
import random
import re

FEMALE = set("emma linda sarah julie susan sara katie maria lily jane emily olivia nina ava mia isabella martha kate "
             "carol ellen dana kathryn hannah becca lena paula".split())
MALE = set("david john mark lucas michael rafael robert ethan liam noah mason daniel james fox benjamin owen kwame".split())
NEUTRAL = set("alex jordan sam".split())
FIRST = FEMALE | MALE | NEUTRAL
LAST = set("johnson lee jameson doe smith mitchell williams connor davies brown mendes martin green baker garcia osei "
           "white blake clark anderson jones maly taylor wilson thompson raynolds sean miller klein dubois ortega "
           "lindqvist reese marcus ripley crichton scully mulder picard janeway sisko chen reyes ferreira fry hollis "
           "roberts ortiz".split())
TYPOS = {"davd": ("david", 3)}          # typo token -> (name, index of the dropped letter)

NEW_FEMALE = ("aisha priya sofia ingrid amara mei hana zara nadia elena chloe leila anya ines freya selin noor camila "
              "astrid rosa yara keiko lucia greta marisol tanvi olga fatima yuki").split()
NEW_MALE = ("mateo kenji omar tomas lukas diego arjun felix yusuf ravi kofi hugo marco tariq jonas pablo viktor rohan "
            "malik theo andre samir emeka nikhil bruno ahmed sven idris").split()
NEW_LAST = ("okafor nakamura rossi petrov haddad kowalski fernandes lindgren mensah novak tanaka silva becker moreau "
            "khan duarte ivanova kaur larsen romero yilmaz park nguyen abebe costa varga hoffmann sato rahman "
            "castillo dimitriou eriksen morales fischer aziz bauer santos horvat ito lund medina oduya "
            "quist sandoval vega weiss zielinski").split()

_LETTERS = r"[A-Za-z]"


def _case(src: str, new: str) -> str:
    return new.capitalize() if src[:1].isupper() else new


def make_map(case_id: str, texts: list[str]) -> dict[str, str]:
    """Pick new names for every first and last name that occurs in this case."""
    blob = " ".join(texts).lower()
    present = {n for n in FIRST | LAST if re.search(rf"(?<!{_LETTERS}){n}(?!{_LETTERS})", blob)}
    present |= {TYPOS[t][0] for t in TYPOS if re.search(rf"(?<!{_LETTERS}){t}(?!{_LETTERS})", blob)}
    rng = random.Random(int(hashlib.sha256(case_id.encode()).hexdigest(), 16))
    pools = {"f": rng.sample(NEW_FEMALE, len(NEW_FEMALE)), "m": rng.sample(NEW_MALE, len(NEW_MALE)),
             "l": rng.sample(NEW_LAST, len(NEW_LAST))}
    out = {}
    for n in sorted(present):
        if n in FIRST:
            key = "f" if n in FEMALE else "m" if n in MALE else rng.choice("fm")
            out[n] = pools[key].pop()
        if n in LAST and n not in out:
            out[n] = pools["l"].pop()
    return out


WORDLIKE = {"green", "white", "brown", "baker", "fry"}      # surnames that are also ordinary words
_B = r"(?:(?<![A-Za-z])|(?<=\\n)|(?<=\\t))"                # start of a word, also right after a literal \n
_SEP = r"(?:\s|\\n|\\)+"                                    # space, or a line break inside quoted text


def _alt(names, cap=False) -> str:
    return "|".join((n.capitalize() if cap else n) for n in sorted(names, key=len, reverse=True))


def _sub_text(s: str, m: dict[str, str]) -> str:
    if not m:
        return s
    firsts = [n for n in m if n in FIRST]
    lasts = [n for n in m if n in LAST]
    # 1. typos keep their typo: drop the same letter from the new name
    for t, (name, i) in TYPOS.items():
        if name in m:
            new = m[name][:i] + m[name][i + 1:] if len(m[name]) > i else m[name][:-1]
            s = re.sub(rf"{_B}{t}(?=[._@])", new, s)
            s = re.sub(rf"{_B}{t.capitalize()}(?![a-z])", new.capitalize(), s)
    every = firsts + lasts
    # 2. emails and ids (lowercase parts next to . _ @); domains after @ are never touched
    s = re.sub(rf"(?<![A-Za-z@\-])({_alt(every)})(?=[._@])", lambda x: m[x.group(1)], s)
    s = re.sub(rf"(?<=[._])({_alt(every)})(?![a-z])(?![^@\s\"']*\.(?:com|net|org|io|co|fr|de|mx)\b(?!@))",
               lambda x: m[x.group(1)], s)
    # 3. full names "First Last" / "Dr Last" / "K. Last", also across a line break
    if lasts:
        fa = _alt(FIRST | {v for v in m.values()}, cap=True)
        s = re.sub(rf"{_B}({fa}|Dr\.?|Mr\.?|Ms\.?|Mrs\.?|[A-Z]\.)({_SEP})({_alt(lasts, cap=True)})(?![a-z])",
                   lambda x: x.group(1) + x.group(2) + m[x.group(3).lower()].capitalize(), s)
        # 4. surnames on their own (not the ones that are also ordinary words)
        alone = [n for n in lasts if n not in WORDLIKE]
        if alone:
            s = re.sub(rf"{_B}({_alt(alone, cap=True)})(?![a-z])", lambda x: m[x.group(1).lower()].capitalize(), s)
    # 5. capitalised first names anywhere
    if firsts:
        s = re.sub(rf"{_B}({_alt(firsts, cap=True)})(?![a-z])", lambda x: m[x.group(1).lower()].capitalize(), s)
    # 6. bare ids such as "emma"
    if s.islower() and s in m:
        s = m[s]
    return s


def apply(obj, m: dict[str, str], skip_keys=("case_id", "scenario_id", "proposal_id")):
    """Rename inside every string of a JSON-like object (keys and case ids untouched)."""
    if isinstance(obj, str):
        return _sub_text(obj, m)
    if isinstance(obj, list):
        return [apply(x, m, skip_keys) for x in obj]
    if isinstance(obj, dict):
        return {k: (v if k in skip_keys else apply(v, m, skip_keys)) for k, v in obj.items()}
    return obj


def strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        return [s for x in obj for s in strings(x)]
    if isinstance(obj, dict):
        return [s for k, v in obj.items() if k != "case_id" for s in strings(v)]
    return []
