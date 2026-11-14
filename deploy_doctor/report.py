"""Render a Report as text, JSON or Markdown."""
from __future__ import annotations

import json
from dataclasses import asdict

from .models import Report
from .rules import CATEGORIES


def _label(category: str) -> str:
    return CATEGORIES.get(category, "Unknown")


def to_dict(report: Report) -> dict:
    d = report.diagnosis
    return {
        "provider": report.provider,
        "lines_analyzed": report.line_count,
        "category": d.category,
        "category_label": _label(d.category),
        "confidence": d.confidence,
        "entities": d.entities,
        "evidence": [asdict(e) for e in d.evidence],
        "alternatives": [
            {"category": c.category, "share": round(c.share, 2)} for c in d.candidates[1:]
        ],
        "fixes": [
            {
                "rank": i,
                "title": f.title,
                "why": f.why,
                "risk": f.risk,
                "score": f.score,
                "file": f.file,
                "command": f.command,
                "diff": f.diff,
            }
            for i, f in enumerate(report.fixes, start=1)
        ],
    }


def to_json(report: Report) -> str:
    return json.dumps(to_dict(report), indent=2)


def _fix_blocks(report: Report, md: bool):
    for i, f in enumerate(report.fixes, start=1):
        head = f"Fix #{i}: {f.title}  [risk: {f.risk}]"
        yield f"### {head}" if md else head
        yield f.why
        if f.diff:
            yield f"```diff\n{f.diff}\n```" if md else f.diff
        if f.command:
            yield f"```bash\n{f.command}\n```" if md else f"$ {f.command}"
        yield ""


def to_text(report: Report, md: bool = False) -> str:
    d = report.diagnosis
    out = []
    if d.category == "unknown":
        out.append("Diagnosis: unknown (no known failure pattern matched)")
        out.append(f"Analyzed {report.line_count} lines ({report.provider}).")
        out.append("Next step: look at the first error above the final 'exit code' line, "
                   "or add a rule for this pattern in deploy_doctor/rules.py.")
        return "\n".join(out)

    title = f"Diagnosis: {_label(d.category)} ({d.category}), confidence {d.confidence:.0%}"
    out.append(f"## {title}" if md else title)
    out.append(f"Analyzed {report.line_count} lines ({report.provider}).")
    if len(d.candidates) > 1:
        alts = ", ".join(f"{c.category} {c.share:.0%}" for c in d.candidates[1:3])
        out.append(f"Also matched: {alts}")
    out.append("")
    out.append("**Evidence**" if md else "Evidence:")
    for e in d.evidence:
        step = f" [{e.step}]" if e.step else ""
        out.append(f"  line {e.line_no}{step}: {e.text}")
    out.append("")
    out.extend(_fix_blocks(report, md))
    out.append("Proposals only. Nothing was applied to your repo.")
    return "\n".join(out)


def to_markdown(report: Report) -> str:
    return to_text(report, md=True)
