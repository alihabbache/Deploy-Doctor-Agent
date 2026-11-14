"""Plain data containers shared by every stage of the pipeline."""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Line:
    no: int  # 1-based line number in the original input
    text: str  # cleaned text (no ANSI, no timestamp, no CI prefix)
    step: Optional[str] = None  # CI step name when the format exposes it


@dataclass
class Log:
    lines: List[Line]
    provider: str  # github | gitlab | jenkins | circleci | generic


@dataclass
class Evidence:
    line_no: int
    text: str
    step: Optional[str]
    signal: str  # label of the rule that matched


@dataclass
class Candidate:
    category: str
    score: float
    share: float  # score / sum of all category scores
    tags: List[str]
    evidence: List[Evidence]


@dataclass
class Diagnosis:
    category: str  # winning category, or "unknown"
    confidence: float  # 0..0.95, strength of the rule match (not a probability)
    candidates: List[Candidate]  # every category with at least one hit, best first
    entities: Dict[str, str] = field(default_factory=dict)

    @property
    def primary(self) -> Optional[Candidate]:
        return self.candidates[0] if self.candidates else None

    @property
    def evidence(self) -> List[Evidence]:
        return self.primary.evidence if self.primary else []


@dataclass
class Fix:
    category: str
    title: str
    why: str
    risk: str  # low | medium | high
    fit: float  # 0..1 how well the template matches the evidence
    file: Optional[str] = None
    before: str = ""
    after: str = ""
    command: Optional[str] = None
    score: float = 0.0  # fit weighted by the category's share of the evidence

    @property
    def diff(self) -> str:
        if not self.file or self.before == self.after:
            return ""
        src = f"a/{self.file}" if self.before else "/dev/null"
        out = difflib.unified_diff(
            self.before.splitlines(),
            self.after.splitlines(),
            src,
            f"b/{self.file}",
            lineterm="",
            n=3,
        )
        return "\n".join(out)


@dataclass
class Report:
    provider: str
    line_count: int
    diagnosis: Diagnosis
    fixes: List[Fix]
