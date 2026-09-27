"""Readable keyword baseline with abstention when evidence is unclear."""

import re

FAILURE_PATTERNS = {
    "database_failure": re.compile(r"\b(?:database|postgres(?:ql)?|mysql|sql|connection pool)\b[^.;!?:]{0,65}\b(?:cannot connect|can't connect|unable to connect|connect(?:ion)? (?:fail|time ?out|refus)|timeouts?|time out|timed out|fail(?:ure|ing|ed|s)?|errors?|refused|unavailable|exhausted|drop(?:ped|s)?)\b|\b(?:cannot connect|can't connect|unable to connect|connect(?:ion)? (?:fail|time ?out|refus)|timeouts?|time out|timed out|fail(?:ure|ing|ed|s)?|errors?|refused|unavailable)\b[^.;!?:]{0,55}\b(?:database|postgres(?:ql)?|mysql|sql)\b", re.I),
    "authentication_failure": re.compile(r"\b(?:authentication|login|sign in|credentials?|passwords?|tokens?|unauthorized|access denied|401|api keys?)\b[^.;!?:]{0,55}\b(?:fail(?:ure|ing|ed|s)?|reject(?:ed|s)?|invalid|expired|denied|unauthorized|401|cannot|can't|unable)\b|\b(?:unauthorized|access denied|401|invalid api keys?)\b|\b(?:reject(?:ed|s)?|invalid|expired)\b[^.;!?:]{0,45}\b(?:login|credentials?|passwords?|tokens?|api keys?)\b", re.I),
    "disk_full": re.compile(r"\b(?:disk|storage|filesystem|volume|partition)\b[^.;!?:]{0,55}\b(?:full|exhausted|no space|ran out|out of space)\b|\b(?:no space left|no free space|out of space|disk full|storage exhausted|filesystem full|volume is full)\b|\bfull\b[^.;!?:]{0,35}\b(?:disk|storage|filesystem|volume|partition)\b", re.I),
}
NEGATION = re.compile(r"\b(?:no|not|never|without|resolved|recovered|cleared|fixed|stopped|did not|doesn't|isn't|aren't)\b", re.I)
HISTORICAL = re.compile(r"\b(?:yesterday|last (?:week|night|month)|earlier|previously|\d+ days? ago)\b", re.I)
HEALTHY = re.compile(r"\b(?:all (?:health|readiness) checks? pass|healthy|operating normally|normal operation|no errors|no incidents|service is up|running normally|requests? (?:are )?succeed(?:ing|ful)|endpoints? respond successfully|every readiness check passes|metrics? (?:are )?normal|writes? (?:are )?(?:completing|succeeding))\b", re.I)


def _active_failure(text: str, pattern: re.Pattern) -> bool:
    for match in pattern.finditer(text):
        clause_start = max(text.rfind(mark, 0, match.start()) for mark in ".;!?:") + 1
        clause_end = min((text.find(mark, match.end()) for mark in ".;!?:" if text.find(mark, match.end()) >= 0), default=len(text))
        context = text[clause_start:match.end()]
        clause = text[clause_start:clause_end]
        negation = NEGATION.search(context)
        no_space_cue = negation is not None and re.match(r"no (?:free )?space left?\b", context[negation.start():], re.I)
        if (negation and not no_space_cue) or HISTORICAL.search(clause):
            continue
        return True
    return False


def predict_rules(text: str) -> dict:
    hits = [label for label, pattern in FAILURE_PATTERNS.items() if _active_failure(text, pattern)]
    if len(hits) == 1:
        selected = hits[0]
        reason = "one current failure category has a matching cue"
    elif len(hits) > 1:
        selected = None
        reason = "multiple failure categories have matching cues"
    elif HEALTHY.search(text) and not any(_active_failure(text, pattern) for pattern in FAILURE_PATTERNS.values()):
        selected = "healthy"
        reason = "explicit statement of normal operation"
    else:
        selected = None
        reason = "no sufficiently clear active category cue"
    return {"backend": "rules", "selected_class": selected, "scores": None, "inference_seconds": None, "abstention_reason": reason}
