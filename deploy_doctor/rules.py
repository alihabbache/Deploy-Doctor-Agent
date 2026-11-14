"""Knowledge base: weighted regex signals per failure category.

Each rule contributes its weight once per log, however many lines match.
`tag` narrows a category down (e.g. auth -> aws) and drives which fixes rank first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

CATEGORIES = {
    "auth": "Authentication / permissions",
    "dependency": "Dependency resolution",
    "build": "Build / compile",
    "test": "Test failure (incl. flaky)",
    "config": "Configuration / secrets",
    "infra": "Infrastructure / runner",
    "rollout": "Deployment rollout (Kubernetes / Helm)",
}


@dataclass(frozen=True)
class Rule:
    category: str
    label: str
    pattern: "re.Pattern[str]"
    weight: float
    tag: str = ""


def _r(category: str, label: str, pattern: str, weight: float, tag: str = "") -> Rule:
    return Rule(category, label, re.compile(pattern, re.IGNORECASE), weight, tag)


RULES: List[Rule] = [
    # ---- auth -------------------------------------------------------------
    _r("auth", "HTTP 401/403", r"\bHTTP[ /]?\S* ?40[13]\b|\b40[13]\b.*(unauthorized|forbidden)|\b(unauthorized|forbidden)\b.*\b40[13]\b", 3, "http"),
    _r("auth", "Missing cloud credentials", r"Unable to locate credentials|NoCredentialProviders|Could not load credentials|Credentials could not be loaded", 5, "aws"),
    _r("auth", "IAM denied", r"not authorized to perform|AccessDenied|is not authorized to", 4, "aws"),
    _r("auth", "Registry access denied", r"denied: .*(permission|requested access)|unauthorized: authentication required|requested access to the resource is denied", 4, "registry"),
    _r("auth", "Token lacks permission", r"Resource not accessible by integration", 6, "gh_perms"),
    _r("auth", "Bad credentials", r"Bad credentials|Authentication failed|Permission denied \(publickey\)", 4, "creds"),
    _r("auth", "Expired token", r"ExpiredToken|token (has )?expired|token is invalid", 3, "creds"),
    # ---- dependency -------------------------------------------------------
    _r("dependency", "npm peer conflict", r"ERESOLVE|Could not resolve dependency", 5, "npm_peer"),
    _r("dependency", "npm lockfile out of sync", r"package-lock\.json.*(in sync|out of sync)|npm ci.*can only install", 6, "lockfile"),
    _r("dependency", "npm 404", r"npm ERR!? (code )?E404|404 Not Found - GET https://registry\.npmjs", 5, "npm"),
    _r("dependency", "Python module missing", r"ModuleNotFoundError: No module named", 5, "pip"),
    _r("dependency", "pip no matching dist", r"No matching distribution found|Could not find a version that satisfies the requirement", 5, "pip"),
    _r("dependency", "Node module missing", r"Cannot find module '", 4, "npm"),
    _r("dependency", "Maven resolution", r"Could not resolve dependencies|Could not find artifact|Non-resolvable parent POM", 5, "maven"),
    _r("dependency", "Go module", r"missing go\.sum entry|go: .*module .* not found", 4, "go"),
    # ---- build ------------------------------------------------------------
    _r("build", "TypeScript error", r"error TS\d+", 5, "ts"),
    _r("build", "Syntax error", r"SyntaxError:", 4, ""),
    _r("build", "Java compile", r"cannot find symbol|COMPILATION ERROR", 5, "java"),
    _r("build", "Linker / header", r"undefined reference to|fatal error: .*No such file or directory", 4, "native"),
    _r("build", "Docker build", r"failed to solve|executor failed running|The command '.*' returned a non-zero code", 5, "docker"),
    _r("build", "Rust compile", r"error\[E\d+\]", 5, "rust"),
    _r("build", "Generic build failure", r"BUILD FAILURE|Compilation failed|Build failed", 2, ""),
    # ---- test -------------------------------------------------------------
    _r("test", "Assertion failure", r"AssertionError|AssertionFailedError|Expected:.*Received:", 3, ""),
    _r("test", "Test runner summary", r"FAILED [\w/.\-]+::|Tests:\s+\d+ failed|\d+ failed, \d+ passed|^FAIL\s+\S+\.(test|spec)\.", 4, ""),
    _r("test", "Timeout in test", r"Timeout of \d+ms exceeded|exceeded timeout of \d+|Exceeded timeout|test timed out", 4, "timeout"),
    _r("test", "Flaky wording", r"flaky|intermittent|passed on (re)?run|race condition", 3, "flaky"),
    _r("test", "Port conflict", r"EADDRINUSE|Address already in use", 3, "flaky"),
    _r("test", "Test network flake", r"socket hang up|ECONNRESET|ECONNREFUSED 127\.0\.0\.1", 2, "flaky"),
    # ---- config -----------------------------------------------------------
    _r("config", "Env var missing", r"\b[A-Z][A-Z0-9_]{3,}\b (is not set|must be set|is required|is undefined|is missing)|environment variable .{0,40}(not set|missing|required)|KeyError: '[A-Z][A-Z0-9_]+'", 5, "env"),
    _r("config", "Secret / input missing", r"Input required and not supplied|secret .{0,40}(not found|is empty|not set)", 5, "secret"),
    _r("config", "YAML / workflow syntax", r"Invalid workflow file|yaml: line \d+|mapping values are not allowed|could not find expected|YAML(Exception|Error)", 5, "yaml"),
    _r("config", "Terraform config", r"Error: (Invalid|Unsupported|Missing required) (value|argument|configuration)|Unsupported argument", 5, "tf"),
    _r("config", "Config drift", r"\bdrift\b|unrecognized (option|key|argument)", 3, ""),
    # ---- infra ------------------------------------------------------------
    _r("infra", "Out of memory", r"exit code 137|OOMKilled|Out of memory|heap out of memory|Cannot allocate memory|\bKilled\b", 5, "oom"),
    _r("infra", "Disk full", r"No space left on device|ENOSPC", 6, "disk"),
    _r("infra", "Rate limited", r"toomanyrequests|rate limit|429 Too Many Requests", 5, "ratelimit"),
    _r("infra", "Network", r"Could not resolve host|Temporary failure in name resolution|Connection (reset|timed out)|TLS handshake timeout|i/o timeout|50[23] (Bad Gateway|Service Unavailable)", 3, "network"),
    _r("infra", "Terraform state lock", r"Error acquiring the state lock", 6, "tflock"),
    _r("infra", "Runner lost", r"runner has received a shutdown signal|lost communication with the server|The operation was canceled", 4, "runner"),
    # ---- rollout ----------------------------------------------------------
    _r("rollout", "Image pull", r"ImagePullBackOff|ErrImagePull|Back-off pulling image|Failed to pull image", 6, "imagepull"),
    _r("rollout", "CrashLoop", r"CrashLoopBackOff", 6, "crashloop"),
    _r("rollout", "Probe failed", r"(Readiness|Liveness|Startup) probe failed", 5, "probe"),
    _r("rollout", "Rollout timeout", r"exceeded its progress deadline|timed out waiting for the condition|UPGRADE FAILED|rollout status.*timed out", 5, "rollout"),
    _r("rollout", "Unschedulable", r"Insufficient (cpu|memory)|FailedScheduling|\d+/\d+ nodes are available", 5, "schedule"),
]
