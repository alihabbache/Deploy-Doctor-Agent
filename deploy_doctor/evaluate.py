"""Run the agent over samples/ and compare with samples/expected.json.

    python -m deploy_doctor.evaluate
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Tuple

from .agent import diagnose

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def run(samples: Path = SAMPLES) -> Tuple[List[dict], float]:
    expected = json.loads((samples / "expected.json").read_text())
    rows = []
    for name, want in expected.items():
        report = diagnose((samples / name).read_text(encoding="utf-8"))
        got = report.diagnosis.category
        top = report.fixes[0].title if report.fixes else ""
        rows.append(
            {
                "file": name,
                "expected": want["category"],
                "got": got,
                "confidence": report.diagnosis.confidence,
                "category_ok": got == want["category"],
                "top_fix": top,
                "top_fix_ok": want["top_fix_contains"].lower() in top.lower(),
            }
        )
    accuracy = sum(r["category_ok"] for r in rows) / len(rows)
    return rows, accuracy


def main() -> int:
    rows, accuracy = run()
    for r in rows:
        mark = "ok  " if r["category_ok"] and r["top_fix_ok"] else "FAIL"
        print(f"{mark} {r['file']:<28} {r['expected']:<11} -> {r['got']:<11} {r['confidence']:.0%}  {r['top_fix']}")
    fix_ok = sum(r["top_fix_ok"] for r in rows)
    print(f"\nclassification accuracy: {accuracy:.0%} ({sum(r['category_ok'] for r in rows)}/{len(rows)})")
    print(f"top-fix match:           {fix_ok}/{len(rows)}")
    return 0 if accuracy == 1.0 and fix_ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
