"""Orchestration: raw log text in, Report out."""
from __future__ import annotations

from .classifier import classify
from .fixes import propose
from .ingest import ingest
from .models import Report


def diagnose(raw: str) -> Report:
    log = ingest(raw)
    diagnosis = classify(log)
    return Report(
        provider=log.provider,
        line_count=len(log.lines),
        diagnosis=diagnosis,
        fixes=propose(diagnosis),
    )
