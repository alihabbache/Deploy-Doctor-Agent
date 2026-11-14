"""Turn a raw CI/CD log into clean, numbered lines."""
from __future__ import annotations

import re
from typing import List, Optional

from .models import Line, Log

# Real ESC sequences, plus the caret form (`^[[2m`) that some CI log exports contain.
ANSI = re.compile(r"(?:\x1b|\^\[)\[[0-9;?]*[A-Za-z]")
# 2026-01-01T12:00:00.123Z / 2026-01-01 12:00:00 / [12:00:00]
TIMESTAMP = re.compile(
    r"^\s*(?:\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\]?|\[\d{2}:\d{2}:\d{2}\])\s*"
)
# `gh run view --log-failed` prefixes every line with "<job>\t<step>\t"
GH_CLI_PREFIX = re.compile(r"^(?P<job>[^\t]*)\t(?P<step>[^\t]*)\t")
GH_MARKER = re.compile(r"^##\[(?:error|warning|group|endgroup|debug|notice)\]")


def detect_provider(raw: str) -> str:
    if "##[" in raw or "actions/checkout" in raw or GH_CLI_PREFIX.search(raw):
        return "github"
    if "section_start:" in raw or "gitlab-runner" in raw or "Running with gitlab" in raw:
        return "gitlab"
    if "[Pipeline]" in raw:
        return "jenkins"
    if "CircleCI" in raw or "circleci" in raw:
        return "circleci"
    return "generic"


def ingest(raw: str) -> Log:
    """Strip ANSI codes, CI prefixes and timestamps; keep original line numbers."""
    provider = detect_provider(raw)
    lines: List[Line] = []
    for no, original in enumerate(raw.splitlines(), start=1):
        text = ANSI.sub("", original).rstrip()
        step: Optional[str] = None
        prefix = GH_CLI_PREFIX.match(text)
        if prefix:
            step = prefix.group("step").strip() or None
            text = text[prefix.end():]
        text = TIMESTAMP.sub("", text)
        text = GH_MARKER.sub("", text).strip()
        if text:
            lines.append(Line(no=no, text=text, step=step))
    return Log(lines=lines, provider=provider)
