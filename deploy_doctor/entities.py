"""Pull concrete names (package, env var, image, ...) out of a log so fixes can be specific."""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .models import Log

# (entity name, regex with one capture group). First match in the log wins.
PATTERNS: List[Tuple[str, str]] = [
    ("env_var", r"\b([A-Z][A-Z0-9_]{3,}) (?:is not set|must be set|is required|is undefined|is missing)"),
    ("env_var", r"KeyError: '([A-Z][A-Z0-9_]+)'"),
    ("env_var", r"environment variable ['\"`]?([A-Z][A-Z0-9_]{2,})"),
    ("input", r"Input required and not supplied: (\S+)"),
    ("py_module", r"No module named '([\w.\-]+)'"),
    ("node_module", r"Cannot find module '([^']+)'"),
    ("peer_pkg", r'peer (\S+?)@"([^"]+)" from'),
    ("resolving", r"While resolving: (\S+?)@(\S+)"),
    ("iam_action", r"not authorized to perform: ([\w:*]+)"),
    ("maven_artifact", r"Could not find artifact ([\w.\-]+:[\w.\-]+:[\w.\-]+:[\w.\-]+)"),
    ("image", r'(?:Failed to pull image|pulling image|Back-off pulling image) \\?"([^"\\]+)'),
    ("tool_version", r"The version '([^']+)' with architecture '[^']+' was not found for (.+?)\.?$"),
    ("image_missing", r"(failed to resolve reference.*not found|manifest unknown|manifest for .* not found)"),
    ("deployment", r'deployment "([^"]+)"'),
    ("test_name", r"FAILED ([\w/.\-]+::[\w:\[\]\-]+)"),
    ("test_name", r"^FAIL\s+(\S+\.(?:test|spec)\.\S+)"),
    ("test_name", r"✕\s+(.+?)(?: \(\d+ ?ms\))?$"),
    ("port", r"EADDRINUSE[^\d]*(\d{2,5})"),
    ("port", r"Address already in use.*?:(\d{2,5})"),
    ("ts_error", r"(\S+\.tsx?)\((\d+),\d+\): error (TS\d+): (.+)"),
    ("lock_id", r"\bID:\s+([0-9a-f]{8}-[0-9a-f-]{27})"),
    ("exit_code", r"exit(?:ed with)? code[: ]+(\d+)"),
    ("timeout_ms", r"(?:Timeout of|exceeded timeout of) (\d+) ?ms"),
]
COMPILED = [(name, re.compile(rx)) for name, rx in PATTERNS]


def extract(log: Log) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for line in log.lines:
        for name, rx in COMPILED:
            if name in found:
                continue
            m = rx.search(line.text)
            if not m:
                continue
            if name == "peer_pkg":
                found["peer_pkg"], found["peer_range"] = m.group(1), m.group(2)
            elif name == "tool_version":
                found["tool_version"], found["runner_os"] = m.group(1), m.group(2)
            elif name == "resolving":
                found["resolving"], found["resolving_ver"] = m.group(1), m.group(2)
            elif name == "ts_error":
                found["ts_file"], found["ts_line"], found["ts_code"], found["ts_msg"] = m.groups()
                found["ts_error"] = m.group(0)
            else:
                found[name] = m.group(1)
    return found
