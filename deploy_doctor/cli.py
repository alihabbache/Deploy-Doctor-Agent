"""Command line entry point: python -m deploy_doctor <log|-> [--json|--markdown]."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .agent import diagnose
from .report import to_json, to_markdown, to_text


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="deploy_doctor",
        description="Classify a failed CI/CD log and propose the top 3 fixes with diffs.",
    )
    p.add_argument("log", help="path to a log file, or - for stdin")
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="machine-readable output")
    fmt.add_argument("--markdown", action="store_true", help="Markdown (e.g. for a PR comment)")
    p.add_argument("--version", action="version", version=f"deploy_doctor {__version__}")
    args = p.parse_args(argv)

    try:
        raw = sys.stdin.read() if args.log == "-" else open(args.log, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        print(f"error: cannot read {args.log}: {exc.strerror}", file=sys.stderr)
        return 2
    if not raw.strip():
        print("error: log is empty", file=sys.stderr)
        return 2

    report = diagnose(raw)
    if args.json:
        print(to_json(report))
    elif args.markdown:
        print(to_markdown(report))
    else:
        print(to_text(report))
    return 0 if report.diagnosis.category != "unknown" else 1


if __name__ == "__main__":
    sys.exit(main())
