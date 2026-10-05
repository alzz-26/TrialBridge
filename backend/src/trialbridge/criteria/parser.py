"""Free-text eligibility criteria -> structured, executable predicates.

Pipeline for one trial:
  1. split the eligibility block into inclusion / exclusion sections,
  2. split sections into individual criteria (bullets, numbered items, sub-bullets
     inherit their parent's lead-in text),
  3. for each criterion extract predicates:
       age    {"type": "age", "op": ">=", "value": 18}
       lab    {"type": "lab", "lab": "egfr", "op": ">", "value": 45, "unit": "..."}
       cond   {"type": "condition", "concept": "myocardial_infarction",
               "negated": false, "within_days": 180}
       med    {"type": "medication", "concept": "anticoagulant", "negated": false}
     plus a NegEx-style negation scope and a temporal window ("within 6 months"),
  4. criteria with no recognised predicate are kept as `unparsed` residue - the
     part Phase 2 hands to the local LLM.

Everything here is deterministic, so every match decision can be traced back
to a span of the original text.
"""

import re

from trialbridge.vocab import CONDITIONS, LAB_BY_KEY, LABS, MEDICATIONS, find_concepts

# ----------------------------------------------------------------------------- splitting
# headers may carry criteria on the same line: "Inclusion Criteria: 18 years, ..."
_INC_HDR = re.compile(r"^\s*(?:key\s+|main\s+|general\s+)?inclusion\s+criteria\b\s*:?", re.I | re.M)
_EXC_HDR = re.compile(r"^\s*(?:key\s+|main\s+|general\s+)?exclusion\s+criteria\b\s*:?", re.I | re.M)
_BULLET = re.compile(r"^(\s*)(?:[*\-•·▪◦]|\d{1,2}[.)]|[a-z][.)]|\(\w{1,3}\))\s+", re.I)


def split_sections(text: str) -> list[tuple[str, str]]:
    """Return [(kind, section_text)] with kind in {inclusion, exclusion}."""
    if not text:
        return []
    marks = [(m.start(), m.end(), "inclusion") for m in _INC_HDR.finditer(text)]
    marks += [(m.start(), m.end(), "exclusion") for m in _EXC_HDR.finditer(text)]
    marks.sort()
    if not marks:
        return [("inclusion", text)]
    out = []
    if text[: marks[0][0]].strip():
        out.append(("inclusion", text[: marks[0][0]]))
    for i, (_, end, kind) in enumerate(marks):
        nxt = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out.append((kind, text[end:nxt]))
    return out


def split_items(section: str) -> list[str]:
    """Split a section into criteria; children of a 'lead-in:' item get its text as prefix."""
    items: list[tuple[int, str]] = []  # (indent, text)
    for raw in section.splitlines():
        if not raw.strip():
            continue
        m = _BULLET.match(raw)
        if m:
            items.append((len(m.group(1).expandtabs(4)), raw[m.end():].strip()))
        elif items:
            items[-1] = (items[-1][0], items[-1][1] + " " + raw.strip())
        else:
            items.append((0, raw.strip()))
    out: list[str] = []
    stack: list[tuple[int, str]] = []  # open lead-ins
    for indent, txt in items:
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if txt.endswith(":"):
            stack.append((indent, txt))
            continue
        prefix = " ".join(s for _, s in stack)
        out.append(f"{prefix} {txt}".strip() if prefix else txt)
    # a dangling lead-in with no children is still a criterion
    for _, s in stack:
        if not any(o.startswith(s) for o in out):
            out.append(s)
    return [o for o in out if len(o) > 2]


# ----------------------------------------------------------------------------- comparators
_NUM = r"(\d{1,3}(?:,\d{3})+|\d+(?:[.,]\d+)?)"
_OPS = [
    (r"(?:≥|>=|=>|greater than or equal to|more than or equal to|equal to or (?:greater|more) than|at least|no less than|not less than|minimum(?: of)?)", ">="),
    (r"(?:≤|<=|=<|less than or equal to|equal to or less than|no more than|not more than|not greater than|not exceeding|at most|up to|maximum(?: of)?)", "<="),
    (r"(?:>|greater than|more than|above|over|higher than|exceeding|exceeds)", ">"),
    (r"(?:<|less than|below|under|lower than|fewer than)", "<"),
    (r"(?:=|equal to|of)", "="),
]
_OP_RX = [(re.compile(p + r"\s*" + _NUM, re.I), op) for p, op in _OPS]
_RANGE_RX = re.compile(r"(?:between\s+)?" + _NUM + r"\s*(?:%|[a-zµ/.²³0-9]*)?\s*(?:-|–|to|and)\s*" + _NUM, re.I)
_ULN_RX = re.compile(r"^\s*(?:x|×|times)?\s*(?:the\s+)?(?:upper limit of normal|uln)", re.I)


def _num(s: str) -> float:
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", s):  # thousands separator: 100,000
        return float(s.replace(",", ""))
    return float(s.replace(",", "."))  # decimal comma: 1,5


def _normalise_value(lab: str, value: float, tail: str) -> tuple[float, str | None]:
    """Convert common alternative units to the canonical unit of the lab."""
    t = tail[:25].lower()
    if lab == "hba1c" and "mmol" in t:
        return round(value / 10.929 + 2.15, 2), "converted from mmol/mol"
    if lab == "hemoglobin" and re.match(r"\s*g/l", t):
        return value / 10, "converted from g/L"
    if lab == "creatinine" and ("µmol" in t or "umol" in t or "μmol" in t):
        return round(value / 88.4, 2), "converted from µmol/L"
    if lab == "glucose" and "mmol" in t:
        return round(value * 18.0, 1), "converted from mmol/L"
    if lab in ("ldl", "hdl", "total_cholesterol") and "mmol" in t:
        return round(value * 38.67, 1), "converted from mmol/L"
    if lab == "triglycerides" and "mmol" in t:
        return round(value * 88.57, 1), "converted from mmol/L"
    if lab in ("platelets", "wbc") and value >= 1000:
        return value / 1000, "converted from /mm³"
    return value, None


def _lab_predicates(text: str) -> list[dict]:
    preds = []
    for lab in LABS:
        for m in lab._rx.finditer(text):
            window = text[m.end(): m.end() + 60]
            # stop the window at the next lab mention / clause boundary
            window = re.split(r"[;]|\band\b(?=\s+[a-z]{3,}\s*(?:[<>≤≥]|of|level))", window, maxsplit=1)[0]
            rng = _RANGE_RX.search(window)
            best = None
            for rx, op in _OP_RX:
                hit = rx.search(window)
                if hit and (best is None or hit.start() < best[0].start()):
                    best = (hit, op)
            if rng and (best is None or rng.start() <= best[0].start()) and re.search(r"between|-|–|to", rng.group(0)):
                lo, _ = _normalise_value(lab.key, _num(rng.group(1)), window[rng.end(1):])
                hi, note = _normalise_value(lab.key, _num(rng.group(2)), window[rng.end():])
                if lo < hi:
                    preds.append({"type": "lab", "lab": lab.key, "op": "between", "value": [lo, hi],
                                  "unit": lab.unit, "span": [m.start(), m.end() + rng.end()], "note": note})
                    break
            if best:
                hit, op = best
                if hit.start() > 30:
                    continue
                value = _num(hit.group(1))
                tail = window[hit.end():]
                note = None
                if lab.uln and _ULN_RX.match(tail):
                    note = f"{value:g} × ULN (ULN={lab.uln:g})"
                    value = round(value * lab.uln, 2)
                else:
                    value, note = _normalise_value(lab.key, value, tail)
                preds.append({"type": "lab", "lab": lab.key, "op": op, "value": value, "unit": lab.unit,
                              "span": [m.start(), m.end() + hit.end()], "note": note})
                break  # one predicate per lab per criterion
    # drop eGFR captured inside "creatinine clearance" duplicates etc.
    seen, out = set(), []
    for p in preds:
        if p["lab"] not in seen:
            seen.add(p["lab"])
            out.append(p)
    return out


# ----------------------------------------------------------------------------- age
_AGE_RXS = [
    (re.compile(r"(?:aged?|age of)\s*(?:between\s*)?(\d{1,3})\s*(?:-|–|to|and)\s*(\d{1,3})\s*(?:years?|yrs?)?", re.I), "range"),
    (re.compile(r"between\s*(?:the ages? of\s*)?(\d{1,3})\s*(?:and|-|to)\s*(\d{1,3})\s*years", re.I), "range"),
    (re.compile(r"(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})\s*years", re.I), "range"),
    (re.compile(r"(?:aged?|age)\s*(?:≥|>=|=>|of at least|at least|greater than or equal to)\s*(\d{1,3})", re.I), ">="),
    (re.compile(r"(?:aged?|age)\s*(?:>|over|above|older than|greater than)\s*(\d{1,3})", re.I), ">"),
    (re.compile(r"(?:aged?|age)\s*(?:≤|<=|=<|up to|no more than|at most)\s*(\d{1,3})", re.I), "<="),
    (re.compile(r"(?:aged?|age)\s*(?:<|under|below|younger than|less than)\s*(\d{1,3})", re.I), "<"),
    (re.compile(r"(\d{1,3})\s*(?:years?|yrs?)(?: of age| old)?\s*(?:or|and)\s*(?:older|above|over|greater)", re.I), ">="),
    (re.compile(r"(?:≥|>=)\s*(\d{1,3})\s*(?:years?|yrs?)", re.I), ">="),
    (re.compile(r"(?:≤|<=)\s*(\d{1,3})\s*(?:years?|yrs?)", re.I), "<="),
    (re.compile(r"(\d{1,3})\s*(?:years?|yrs?)(?: of age| old)?\s*(?:or|and)\s*(?:younger|below|under|less)", re.I), "<="),
]


def _age_predicates(text: str) -> list[dict]:
    if not re.search(r"\bage|years? old|years? of age|\byears?\b", text, re.I):
        return []
    for rx, kind in _AGE_RXS:
        m = rx.search(text)
        if not m:
            continue
        if kind == "range":
            lo, hi = int(m.group(1)), int(m.group(2))
            if 0 <= lo < hi <= 120:
                return [{"type": "age", "op": "between", "value": [lo, hi], "span": list(m.span())}]
        else:
            v = int(m.group(1))
            if 0 <= v <= 120:
                return [{"type": "age", "op": kind, "value": v, "span": list(m.span())}]
    return []


# ----------------------------------------------------------------------------- negation & time
_NEG_CUES = re.compile(
    r"\b(?:no|not|without|absence of|absent|free of|negative for|denies|denied|never|none|lack of|"
    r"no (?:known |prior |previous |history of |evidence of |current )|must not|cannot|unable to|rule out|excluding)\b",
    re.I,
)
_PSEUDO_NEG = re.compile(r"\b(?:not only|no change|not necessarily|whether or not)\b", re.I)
_SCOPE_BREAK = re.compile(r"[.;]|\b(?:but|however|except|although|who|which|and has|with)\b", re.I)
_WITHIN = re.compile(
    r"(?:within|in the|during the|in|for the|over the|prior|previous|last|past|<|≤)\s*"
    r"(?:(?:last|past|previous|prior|preceding)\s*)?(\d+|one|two|three|four|five|six|twelve)\s*"
    r"(days?|weeks?|wks?|months?|mos?|years?|yrs?)", re.I)
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "twelve": 12}
_UNIT_DAYS = {"d": 1, "w": 7, "m": 30.44, "y": 365.25}
_HISTORY = re.compile(r"\b(?:history of|prior|previous|ever had|past)\b", re.I)
_CURRENT = re.compile(r"\b(?:current(?:ly)?|active|ongoing|uncontrolled|untreated|concurrent|concomitant|presence of)\b", re.I)


def is_negated(text: str, start: int) -> bool:
    """NegEx-lite: a negation cue within the same clause, up to ~6 words before the mention."""
    pre = text[max(0, start - 60): start]
    parts = _SCOPE_BREAK.split(pre)
    clause = parts[-1] if parts else pre
    if _PSEUDO_NEG.search(clause):
        return False
    words = clause.split()
    return bool(_NEG_CUES.search(" ".join(words[-6:])))


def _within_days(text: str) -> int | None:
    m = _WITHIN.search(text)
    if not m:
        return None
    n = m.group(1).lower()
    n = _WORDNUM.get(n, None) or int(n)
    return int(round(n * _UNIT_DAYS[m.group(2)[0].lower()]))


def _concept_predicates(text: str, vocab, ptype: str) -> list[dict]:
    window = _within_days(text)
    out, seen = [], set()
    for concept, m in find_concepts(text, vocab):
        if concept.key in seen:
            continue
        seen.add(concept.key)
        p = {"type": ptype, "concept": concept.key, "label": concept.label,
             "negated": is_negated(text, m.start()), "span": [m.start(), m.end()]}
        if window:
            p["within_days"] = window
        if _CURRENT.search(text[max(0, m.start() - 40): m.start()]):
            p["status"] = "active"
        elif _HISTORY.search(text[max(0, m.start() - 40): m.start()]):
            p["status"] = "ever"
        out.append(p)
    return out


# ----------------------------------------------------------------------------- residual
_FILLER = set("""a an the of and or in on for to with without by at from as is are was were be been being this that these
those it its who which must should will may can have has had any all other such patients patient subjects subject participants
participant individuals adults adult men women male female aged age ages years year old least than more less greater equal
history prior previous current currently known diagnosis diagnosed confirmed documented evidence clinical clinically
significant study screening enrollment enrolment entry baseline visit months weeks days within past last time following
including include includes eligible eligibility criteria criterion inclusion exclusion willing able provide written informed
consent sign signed signing participate participation per mg dl ml min kg mmhg not no""".split())
_WORD = re.compile(r"[a-z][a-z'-]+", re.I)
RESIDUAL_LIMIT = 6  # more unexplained content words than this -> criterion only partially understood


def residual_words(text: str, preds: list[dict]) -> list[str]:
    """Content words not explained by any extracted predicate span."""
    keep = list(text)
    for p in preds:
        if "span" in p:
            s, e = p["span"]
            keep[s:e] = " " * (e - s)
    return [w for w in _WORD.findall("".join(keep).lower()) if w not in _FILLER and len(w) > 2]


# ----------------------------------------------------------------------------- public API
def parse_criterion(text: str, kind: str) -> dict:
    preds = _age_predicates(text) + _lab_predicates(text)
    preds += _concept_predicates(text, CONDITIONS, "condition")
    preds += _concept_predicates(text, MEDICATIONS, "medication")
    if not preds:
        return {"kind": kind, "text": text, "predicates": [{"type": "unparsed"}]}
    rest = residual_words(text, preds)
    if len(rest) > RESIDUAL_LIMIT:
        # partly understood: the rest goes to the LLM layer, the criterion cannot be decided alone
        preds.append({"type": "unparsed", "partial": True, "residual": rest[:12]})
    return {"kind": kind, "text": text, "predicates": preds}


def parse_eligibility(text: str | None, min_age: float | None = None, max_age: float | None = None,
                      sex: str | None = None) -> list[dict]:
    """Parse a trial's eligibility block plus its structured age / sex fields."""
    # ClinicalTrials.gov stores criteria as Markdown: "eGFR \< 45", "\>= 18"
    text = re.sub(r"\\([<>*_#=~\[\]()\-+.])", r"\1", text or "")
    criteria: list[dict] = []
    if min_age is not None or max_age is not None:
        if min_age is not None and max_age is not None:
            p = {"type": "age", "op": "between", "value": [min_age, max_age]}
            t = f"Age {min_age:g}–{max_age:g} years"
        elif min_age is not None:
            p, t = {"type": "age", "op": ">=", "value": min_age}, f"Age ≥ {min_age:g} years"
        else:
            p, t = {"type": "age", "op": "<=", "value": max_age}, f"Age ≤ {max_age:g} years"
        criteria.append({"kind": "inclusion", "text": t + " (registry field)", "predicates": [p], "structured": True})
    if sex and sex.upper() in ("MALE", "FEMALE"):
        criteria.append({"kind": "inclusion", "text": f"Sex: {sex.lower()} (registry field)",
                         "predicates": [{"type": "sex", "value": sex.upper()}], "structured": True})
    for kind, section in split_sections(text or ""):
        for item in split_items(section):
            c = parse_criterion(item, kind)
            # structured age already covers the registry limits
            if criteria and criteria[0].get("structured") and any(p["type"] == "age" for p in c["predicates"]):
                c["predicates"] = [p for p in c["predicates"] if p["type"] != "age"] or [{"type": "covered"}]
                if c["predicates"][0].get("partial"):  # only the residue is left
                    c["predicates"] = [{"type": "unparsed"}]
            criteria.append(c)
    return criteria


def parse_stats(criteria: list[dict]) -> dict:
    free = [c for c in criteria if not c.get("structured")]
    parsed = [c for c in free if c["predicates"][0]["type"] not in ("unparsed",)]
    full = [c for c in parsed if not any(p.get("partial") for p in c["predicates"])]
    by_type: dict[str, int] = {}
    for c in free:
        for p in c["predicates"]:
            t = "partial" if p.get("partial") else p["type"]
            by_type[t] = by_type.get(t, 0) + 1
    n = len(free)
    return {"criteria": n, "parsed": len(parsed), "fully_parsed": len(full),
            "coverage": round(len(parsed) / n, 3) if n else None,
            "full_coverage": round(len(full) / n, 3) if n else None, "predicates": by_type}


__all__ = ["parse_eligibility", "parse_criterion", "split_sections", "split_items", "is_negated",
           "parse_stats", "LAB_BY_KEY"]
