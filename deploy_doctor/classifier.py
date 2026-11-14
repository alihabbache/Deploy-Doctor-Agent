"""Score every category against the log and return a ranked diagnosis."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from .entities import extract
from .models import Candidate, Diagnosis, Evidence, Log
from .rules import RULES

MIN_SCORE = 3.0  # below this we say "unknown" instead of guessing
MAX_EVIDENCE = 6
LINES_PER_RULE = 2


def classify(log: Log) -> Diagnosis:
    scores: Dict[str, float] = defaultdict(float)
    tags: Dict[str, List[str]] = defaultdict(list)
    evidence: Dict[str, Dict[int, Evidence]] = defaultdict(dict)

    for rule in RULES:
        hits = [ln for ln in log.lines if rule.pattern.search(ln.text)]
        if not hits:
            continue
        scores[rule.category] += rule.weight
        if rule.tag and rule.tag not in tags[rule.category]:
            tags[rule.category].append(rule.tag)
        for ln in hits[:LINES_PER_RULE]:
            evidence[rule.category].setdefault(
                ln.no, Evidence(ln.no, ln.text, ln.step, rule.label)
            )

    total = sum(scores.values())
    candidates = [
        Candidate(
            category=cat,
            score=score,
            share=score / total,
            tags=tags[cat],
            evidence=sorted(evidence[cat].values(), key=lambda e: e.line_no)[:MAX_EVIDENCE],
        )
        for cat, score in sorted(scores.items(), key=lambda kv: -kv[1])
    ]

    entities = extract(log)
    if not candidates or candidates[0].score < MIN_SCORE:
        return Diagnosis("unknown", 0.0, candidates, entities)

    top = candidates[0]
    runner_up = candidates[1].score if len(candidates) > 1 else 0.0
    strength = min(1.0, top.score / 10.0)
    margin = (top.score - runner_up) / top.score
    confidence = min(0.95, 0.15 + 0.5 * strength + 0.35 * margin)
    return Diagnosis(top.category, round(confidence, 2), candidates, entities)
