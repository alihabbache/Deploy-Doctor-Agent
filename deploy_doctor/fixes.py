"""Fix library: each template inspects tags/entities and returns a concrete, ranked Fix.

Templates never touch your repo. `before`/`after` are minimal snippets of the file that
usually needs changing; the diff is a proposal to review, not a patch to auto-apply.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .models import Candidate, Diagnosis, Fix

Ctx = Dict[str, str]
Template = Callable[[List[str], Ctx], Optional[Fix]]

WF = ".github/workflows/deploy.yml"


def _fix(cat: str, title: str, why: str, risk: str, fit: float, **kw) -> Fix:
    return Fix(category=cat, title=title, why=why, risk=risk, fit=fit, **kw)


# --------------------------------------------------------------------- auth
def auth_oidc(tags, ctx):
    fit = 0.9 if "aws" in tags else 0.45
    return _fix(
        "auth", "Replace static cloud keys with OIDC role assumption",
        "Missing, expired or rotated long-lived keys are the top cause of cloud auth failures. "
        "OIDC issues a short-lived token per run, so there is nothing to rotate.",
        "medium", fit, file=WF,
        before="""\
permissions:
  contents: read
jobs:
  deploy:
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1""",
        after="""\
permissions:
  contents: read
  id-token: write
jobs:
  deploy:
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<ACCOUNT_ID>:role/<DEPLOY_ROLE>
          aws-region: us-east-1""",
    )


def auth_iam(tags, ctx):
    if "aws" not in tags or not ctx.get("iam_action"):
        return None
    action = ctx["iam_action"]
    return _fix(
        "auth", f"Grant the deploy role `{action}`",
        f"The log shows the role is not authorized to perform `{action}`. Add exactly that action, scoped to the target resource.",
        "medium", 0.9, file="infra/deploy-role-policy.json",
        before="""\
{
  "Statement": [
    { "Effect": "Allow", "Action": ["s3:PutObject"], "Resource": "arn:aws:s3:::<BUCKET>/*" }
  ]
}""",
        after=f"""\
{{
  "Statement": [
    {{ "Effect": "Allow", "Action": ["s3:PutObject", "{action}"], "Resource": "arn:aws:s3:::<BUCKET>/*" }}
  ]
}}""",
    )


def auth_gh_perms(tags, ctx):
    fit = 0.95 if "gh_perms" in tags else 0.4
    return _fix(
        "auth", "Give the workflow token the permission it is missing",
        "'Resource not accessible by integration' means GITHUB_TOKEN is read-only for this API. Grant the narrowest scope at job level.",
        "low", fit, file=WF,
        before="""\
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:""",
        after="""\
jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
      pull-requests: write
    steps:""",
    )


def auth_registry(tags, ctx):
    fit = 0.9 if "registry" in tags else 0.35
    return _fix(
        "auth", "Log in to the container registry before pushing",
        "'denied' or 'authentication required' on push/pull means no valid registry login in this job.",
        "low", fit, file=WF,
        before="""\
      - uses: docker/build-push-action@v6
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}:${{ github.sha }}""",
        after="""\
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}:${{ github.sha }}""",
    )


def auth_rotate(tags, ctx):
    fit = 0.8 if "creds" in tags else 0.3
    return _fix(
        "auth", "Rotate the expired or invalid secret",
        "Bad or expired credentials cannot be fixed in code. Issue a new token and update the repo secret.",
        "low", fit, command="gh secret set DEPLOY_TOKEN --repo <OWNER>/<REPO>",
    )


# --------------------------------------------------------------- dependency
def dep_peer(tags, ctx):
    if "npm_peer" not in tags:
        return None
    old = ctx.get("resolving")
    pkg = ctx.get("peer_pkg", "<package>")
    rng = ctx.get("peer_range", "<range>")
    if old:
        ver = ctx.get("resolving_ver", "<CURRENT>")
        return _fix(
            "dependency", f"Upgrade `{old}` to a release that supports your current `{pkg}`",
            f"`{old}@{ver}` only allows `{pkg}` {rng}. Upgrading the lagging library fixes the cause "
            f"without downgrading `{pkg}`. Check its changelog for breaking changes.",
            "medium", 0.85, file="package.json",
            before=f'  "dependencies": {{\n    "{old}": "^{ver}"\n  }}',
            after=f'  "dependencies": {{\n    "{old}": "^<LATEST_COMPATIBLE>"\n  }}',
        )
    return _fix(
        "dependency", f"Align `{pkg}` with the peer range `{rng}`",
        "ERESOLVE means two packages demand incompatible versions. Aligning the version fixes the cause instead of hiding it.",
        "medium", 0.7, file="package.json",
        before=f'  "dependencies": {{\n    "{pkg}": "^<CURRENT>"\n  }}',
        after=f'  "dependencies": {{\n    "{pkg}": "{rng}"\n  }}',
    )


def dep_legacy_peer(tags, ctx):
    fit = 0.7 if "npm_peer" in tags else 0.0
    if not fit:
        return None
    return _fix(
        "dependency", "Unblock the build with legacy peer resolution (temporary)",
        "Restores npm 6 behaviour so the pipeline goes green now. Treat it as a stopgap and open a ticket for the real conflict.",
        "high", fit, file=".npmrc", before="", after="legacy-peer-deps=true",
    )


def dep_lockfile(tags, ctx):
    if "lockfile" not in tags:
        return None
    return _fix(
        "dependency", "Regenerate the lockfile and commit it",
        "`npm ci` refuses to run when package.json and package-lock.json disagree.",
        "low", 0.95, command="npm install --package-lock-only && git add package-lock.json && git commit -m 'chore: sync lockfile'",
    )


def dep_py_module(tags, ctx):
    mod = ctx.get("py_module")
    fit = 0.9 if mod else 0.0
    if not mod:
        return None
    pkg = mod.split(".")[0].replace("_", "-")
    return _fix(
        "dependency", f"Add `{pkg}` to requirements",
        f"`{mod}` is imported but never installed in CI. If the import name differs from the PyPI name, adjust it.",
        "low", fit, file="requirements.txt",
        before="flask==3.0.3\nrequests==2.32.3",
        after=f"flask==3.0.3\nrequests==2.32.3\n{pkg}",
    )


def dep_node_module(tags, ctx):
    mod = ctx.get("node_module")
    if not mod or mod.startswith("."):
        return None
    return _fix(
        "dependency", f"Declare `{mod}` in package.json",
        "The module is required at runtime but not listed, so it only works where it happens to be hoisted.",
        "low", 0.85, file="package.json",
        before='  "dependencies": {\n    "express": "^4.19.2"\n  }',
        after=f'  "dependencies": {{\n    "express": "^4.19.2",\n    "{mod}": "^<VERSION>"\n  }}',
    )


def dep_pip_pin(tags, ctx):
    if "pip" not in tags:
        return None
    return _fix(
        "dependency", "Pin a Python version the package supports",
        "'No matching distribution' usually means the runner's Python is too new or too old for a wheel.",
        "low", 0.6, file=WF,
        before="      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.13'",
        after="      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.11'",
    )


def dep_maven(tags, ctx):
    art = ctx.get("maven_artifact")
    if "maven" not in tags or not art:
        return None
    g, a, _, v = art.split(":")
    return _fix(
        "dependency", f"Publish or resolve `{g}:{a}:{v}` before this build",
        "Maven cannot find the artifact in any configured repository. Usually the upstream module was never "
        "deployed, or CI lacks the internal repository and its credentials.",
        "medium", 0.9, file="pom.xml",
        before="  <repositories>\n  </repositories>",
        after="  <repositories>\n    <repository>\n      <id>internal</id>\n      <url>https://<INTERNAL_REPO>/maven</url>\n    </repository>\n  </repositories>",
    )


def dep_cache(tags, ctx):
    return _fix(
        "dependency", "Clear the dependency cache and re-run",
        "A corrupt or stale cache produces resolution errors that vanish on a clean install.",
        "low", 0.4, command="gh cache delete --all && gh run rerun <RUN_ID> --failed",
    )


# -------------------------------------------------------------------- build
def build_ts(tags, ctx):
    if "ts" not in tags:
        return None
    where = f"{ctx['ts_file']}:{ctx['ts_line']}" if "ts_file" in ctx else "the reported file"
    code = ctx.get("ts_code", "TS####")
    return _fix(
        "build", f"Fix {code} at {where}",
        f"The compiler reports: {ctx.get('ts_msg', 'type error')}. Fix the type at the source rather than loosening the config.",
        "low", 0.8, command=f"npx tsc --noEmit  # then open {where}",
    )


def build_ts_pin(tags, ctx):
    if "ts" not in tags:
        return None
    return _fix(
        "build", "Pin TypeScript so CI matches local",
        "A caret range lets CI pick up a newer compiler with stricter checks than the one you tested.",
        "low", 0.6, file="package.json",
        before='    "typescript": "^5.0.0"',
        after='    "typescript": "5.4.5"',
    )


def build_docker(tags, ctx):
    fit = 0.8 if "docker" in tags else 0.0
    if not fit:
        return None
    return _fix(
        "build", "Pin the Docker base image",
        "`latest` and floating tags change under you; a pinned tag makes the build reproducible.",
        "low", fit, file="Dockerfile",
        before="FROM node:latest\nWORKDIR /app\nCOPY . .\nRUN npm ci && npm run build",
        after="FROM node:20.12-slim\nWORKDIR /app\nCOPY . .\nRUN npm ci && npm run build",
    )


def build_toolchain(tags, ctx):
    return _fix(
        "build", "Pin the toolchain version in CI",
        "Compile errors that appear only in CI are most often a runner using a different compiler or runtime version.",
        "low", 0.5, file=WF,
        before="      - uses: actions/setup-node@v4\n        with:\n          node-version: latest",
        after="      - uses: actions/setup-node@v4\n        with:\n          node-version: 20\n          cache: npm",
    )


# --------------------------------------------------------------------- lint
def lint_format(tags, ctx):
    if "format" not in tags:
        return None
    hook = ctx.get("hook", "the formatter")
    return _fix(
        "lint", f"Run `{hook}` locally and commit what it changes",
        "The formatter rewrote files in CI, which counts as a failure. Run the same hook on your machine, "
        "review the diff, and commit it.",
        "low", 0.95, command="pre-commit run --all-files && git add -u && git commit -m 'Apply formatter'",
    )


def lint_types(tags, ctx):
    if "types" not in tags:
        return None
    where = f"{ctx['type_file']}:{ctx['type_line']}" if "type_file" in ctx else "the reported line"
    msg = ctx.get("type_msg", "type error")
    return _fix(
        "lint", f"Fix the type error at {where}",
        f"The type checker reports: {msg}. Narrow the type at the source instead of adding `# type: ignore`.",
        "low", 0.85, command=f"mypy {ctx.get('type_file', '.')}  # then open {where}",
    )


def lint_precommit_local(tags, ctx):
    fit = 0.6 if "precommit" in tags else 0.3
    return _fix(
        "lint", "Install the pre-commit hook so this fails before the push",
        "These checks run the same way locally. Installing the git hook catches them at commit time.",
        "low", fit, command="pre-commit install",
    )


# --------------------------------------------------------------------- test
def test_warning_filter(tags, ctx):
    if "warning_error" not in tags:
        return None
    cls = ctx.get("warning_class", "DeprecationWarning")
    msg = ctx.get("warning_msg", "")
    note = f" The warning is: {msg}" if msg else ""
    return _fix(
        "test", f"Stop `{cls}` from failing the run while you migrate",
        "pytest is configured to turn warnings into errors, so a deprecation in a dependency "
        "(here a development build) fails the suite before any test runs." + note,
        "low", 0.9, file="pyproject.toml",
        before='[tool.pytest.ini_options]\nfilterwarnings = [\n    "error",\n]',
        after='[tool.pytest.ini_options]\nfilterwarnings = [\n    "error",\n    "default::' + cls + '",\n]',
    )


def test_retry(tags, ctx):
    fit = 0.85 if "flaky" in tags else 0.3
    name = ctx.get("test_name", "")
    note = f" Affected: `{name}`." if name else ""
    why = ("Intermittent failures waste a full re-run. Retrying just the failing test "
           "keeps the signal and saves minutes." + note)
    if "::" in name:  # pytest node id
        return _fix("test", "Retry flaky tests in CI, not the whole pipeline", why, "low", fit,
                    file="pytest.ini",
                    before="[pytest]\naddopts = -q",
                    after="[pytest]\naddopts = -q --reruns 2 --reruns-delay 1")
    return _fix("test", "Retry flaky tests in CI, not the whole pipeline", why, "low", fit,
                file="jest.setup.js", before="",
                after="jest.retryTimes(2, { logErrorsBeforeRetry: true });")


def test_timeout(tags, ctx):
    if "timeout" not in tags:
        return None
    ms = int(ctx.get("timeout_ms", "5000"))
    return _fix(
        "test", f"Raise the test timeout from {ms} ms to {ms * 3} ms on CI",
        "Shared runners are slower than laptops. Give slow integration tests more headroom.",
        "low", 0.8, file="jest.config.js",
        before=f"module.exports = {{\n  testTimeout: {ms},\n}};",
        after=f"module.exports = {{\n  testTimeout: process.env.CI ? {ms * 3} : {ms},\n}};",
    )


def test_port(tags, ctx):
    if "port" not in ctx:
        return None
    p = ctx["port"]
    return _fix(
        "test", f"Stop hard-coding port {p} in tests",
        "Parallel workers collide on a fixed port. Port 0 asks the OS for a free one.",
        "low", 0.9, file="test/server.test.js",
        before=f"const server = app.listen({p});",
        after="const server = app.listen(0);\nconst { port } = server.address();",
    )


def test_quarantine(tags, ctx):
    name = ctx.get("test_name")
    return _fix(
        "test", "Quarantine the failing test and track it" if name else "Reproduce the failing test locally",
        "If it is a known flake, skip it with a ticket link so the deploy is unblocked; otherwise run it alone to confirm it is real.",
        "medium", 0.45,
        command=f"pytest -x -k '{name.split('::')[-1]}' --count=20" if name and "::" in name else "npm test -- --runInBand",
    )


# ------------------------------------------------------------------- config
def cfg_env(tags, ctx):
    var = ctx.get("env_var")
    if not var:
        return None
    return _fix(
        "config", f"Pass `{var}` into the deploy job",
        f"`{var}` is read at runtime but the workflow never provides it.",
        "low", 0.9, file=WF,
        before="      - run: ./deploy.sh",
        after=f"      - run: ./deploy.sh\n        env:\n          {var}: ${{{{ secrets.{var} }}}}",
    )


def cfg_set_secret(tags, ctx):
    name = ctx.get("env_var") or ctx.get("input")
    if not name:
        return None
    return _fix(
        "config", f"Create the `{name}` secret in the repository",
        "Referencing a secret that does not exist yields an empty string, not an error, which surfaces later as a confusing failure.",
        "low", 0.8, command=f"gh secret set {name} --repo <OWNER>/<REPO>",
    )


def cfg_yaml(tags, ctx):
    if "yaml" not in tags:
        return None
    return _fix(
        "config", "Lint workflows before they run",
        "A YAML/schema error stops the run before any step executes. actionlint catches it on the pull request.",
        "low", 0.8, file=".github/workflows/lint.yml", before="",
        after="""\
name: lint-workflows
on: [pull_request]
jobs:
  actionlint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: raven-actions/actionlint@v2""",
    )


def cfg_tf(tags, ctx):
    if "tf" not in tags:
        return None
    return _fix(
        "config", "Validate Terraform before plan/apply",
        "Invalid arguments are cheap to catch with `terraform validate` and expensive to catch in apply.",
        "low", 0.7, file=WF,
        before="      - run: terraform apply -auto-approve",
        after="      - run: terraform fmt -check\n      - run: terraform validate\n      - run: terraform apply -auto-approve",
    )


def cfg_example(tags, ctx):
    var = ctx.get("env_var")
    return _fix(
        "config", "Document required settings and fail fast",
        "Validate config at startup so a missing value fails in seconds with a clear message.",
        "low", 0.35, file=".env.example", before="",
        after=f"{var or 'REQUIRED_SETTING'}=changeme",
    )


# -------------------------------------------------------------------- infra
def infra_oom(tags, ctx):
    fit = 0.9 if "oom" in tags else 0.0
    if not fit:
        return None
    return _fix(
        "infra", "Raise the Node heap limit for the build",
        "Exit code 137 / heap out of memory means the process was killed for exceeding available RAM.",
        "low", fit, file=WF,
        before="      - run: npm run build",
        after="      - run: npm run build\n        env:\n          NODE_OPTIONS: --max-old-space-size=4096",
    )


def infra_bigger_runner(tags, ctx):
    if "runner_image" in tags:
        return None
    fit = 0.7 if "oom" in tags else 0.3
    return _fix(
        "infra", "Move the job to a larger runner",
        "If the workload genuinely needs more memory or CPU, a larger runner is cheaper than repeated failed runs.",
        "medium", fit, file=WF,
        before="    runs-on: ubuntu-latest", after="    runs-on: ubuntu-latest-8-cores",
    )


def infra_disk(tags, ctx):
    if "disk" not in tags:
        return None
    return _fix(
        "infra", "Free disk space before the heavy step",
        "Hosted runners ship large preinstalled toolchains. Removing the ones you do not use frees ~25 GB.",
        "low", 0.9, file=WF,
        before="      - uses: actions/checkout@v4",
        after="      - run: sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc\n      - uses: actions/checkout@v4",
    )


def infra_ratelimit(tags, ctx):
    if "ratelimit" not in tags:
        return None
    return _fix(
        "infra", "Authenticate to Docker Hub to lift pull limits",
        "Anonymous pulls from shared runner IPs hit the rate limit. Authenticated pulls get a far higher quota.",
        "low", 0.9, file=WF,
        before="      - uses: actions/checkout@v4",
        after="      - uses: docker/login-action@v3\n        with:\n          username: ${{ secrets.DOCKERHUB_USER }}\n          password: ${{ secrets.DOCKERHUB_TOKEN }}\n      - uses: actions/checkout@v4",
    )


def infra_retry(tags, ctx):
    fit = 0.8 if "network" in tags else 0.25
    return _fix(
        "infra", "Retry the step that talks to the network",
        "DNS, TLS and 5xx errors are transient. A bounded retry turns most of them into a green run.",
        "low", fit, file=WF,
        before="      - run: ./deploy.sh",
        after="      - uses: nick-fields/retry@v3\n        with:\n          timeout_minutes: 10\n          max_attempts: 3\n          command: ./deploy.sh",
    )


def infra_runner_pin(tags, ctx):
    if "runner_image" not in tags:
        return None
    ver = ctx.get("tool_version", "<VERSION>")
    os_ = ctx.get("runner_os", "the runner image")
    return _fix(
        "infra", f"Pin the runner image so `{ver}` is available",
        f"`ubuntu-latest` moves to a new OS release over time, and {os_} has no build of version {ver}. "
        "A pinned image keeps the toolchain reproducible.",
        "low", 0.95, file=WF,
        before="    runs-on: ubuntu-latest",
        after="    runs-on: ubuntu-24.04",
    )


def infra_bump_version(tags, ctx):
    if "runner_image" not in tags:
        return None
    ver = ctx.get("tool_version", "<VERSION>")
    return _fix(
        "infra", f"Or move off the unavailable version `{ver}`",
        "If the old version is end-of-life, upgrading is the durable fix. Pin the runner (previous fix) as a stopgap.",
        "medium", 0.7, file=WF,
        before=f"          python-version: '{ver}'",
        after="          python-version: '3.12'",
    )


def infra_tflock(tags, ctx):
    if "tflock" not in tags:
        return None
    lid = ctx.get("lock_id", "<LOCK_ID>")
    return _fix(
        "infra", "Release the stale Terraform state lock",
        "A cancelled or crashed run left the lock behind. Confirm no apply is running, then unlock.",
        "high", 0.95, command=f"terraform force-unlock {lid}",
    )


# ------------------------------------------------------------------ rollout
def roll_imagepull(tags, ctx):
    if "imagepull" not in tags:
        return None
    img = ctx.get("image", "<IMAGE>")
    missing = "image_missing" in ctx  # registry answered "not found": credentials are not the problem
    return _fix(
        "rollout", f"Add an imagePullSecret for `{img}`",
        "ImagePullBackOff means the node cannot fetch the image: wrong tag, missing push, or no pull credentials."
        + (" The registry said the tag was not found, so check the push first." if missing else ""),
        "medium", 0.5 if missing else 0.9, file="k8s/deployment.yaml",
        before="    spec:\n      containers:\n        - name: app\n          image: " + img,
        after="    spec:\n      imagePullSecrets:\n        - name: regcred\n      containers:\n        - name: app\n          image: " + img,
    )


def roll_verify_image(tags, ctx):
    if "imagepull" not in tags:
        return None
    img = ctx.get("image", "<IMAGE>")
    return _fix(
        "rollout", f"Confirm `{img}` was actually pushed",
        "Deploy jobs often run before, or without, the push that creates the tag."
        + (" The registry reported the reference as not found." if "image_missing" in ctx else ""),
        "low", 0.95 if "image_missing" in ctx else 0.7, command=f"docker manifest inspect {img}",
    )


def roll_crashloop(tags, ctx):
    if "crashloop" not in tags:
        return None
    dep = ctx.get("deployment", "<DEPLOYMENT>")
    return _fix(
        "rollout", "Read the previous container's logs",
        "CrashLoopBackOff hides the real error; the crash reason is in the last terminated container.",
        "low", 0.85, command=f"kubectl logs deploy/{dep} --previous --tail=100",
    )


def roll_probe(tags, ctx):
    fit = 0.85 if "probe" in tags else 0.4
    return _fix(
        "rollout", "Give the app time to start before probing",
        "Probes that start too early kill a healthy but slow-booting container.",
        "low", fit, file="k8s/deployment.yaml",
        before="          readinessProbe:\n            httpGet: { path: /healthz, port: 8080 }\n            initialDelaySeconds: 2\n            failureThreshold: 3",
        after="          startupProbe:\n            httpGet: { path: /healthz, port: 8080 }\n            failureThreshold: 30\n            periodSeconds: 2\n          readinessProbe:\n            httpGet: { path: /healthz, port: 8080 }\n            failureThreshold: 3",
    )


def roll_atomic(tags, ctx):
    fit = 0.75 if "rollout" in tags else 0.3
    return _fix(
        "rollout", "Make the release roll back automatically on failure",
        "`--atomic` reverts a failed Helm upgrade, so a bad release never stays half-deployed.",
        "low", fit, file=WF,
        before="      - run: helm upgrade app ./chart --install",
        after="      - run: helm upgrade app ./chart --install --atomic --timeout 5m",
    )


def roll_resources(tags, ctx):
    if "schedule" not in tags:
        return None
    return _fix(
        "rollout", "Lower resource requests so the pod can be scheduled",
        "'Insufficient cpu/memory' means no node can satisfy the requests. Right-size them from real usage.",
        "medium", 0.85, file="k8s/deployment.yaml",
        before="          resources:\n            requests: { cpu: '2', memory: 4Gi }",
        after="          resources:\n            requests: { cpu: 500m, memory: 1Gi }",
    )


TEMPLATES: Dict[str, List[Template]] = {
    "auth": [auth_oidc, auth_iam, auth_gh_perms, auth_registry, auth_rotate],
    "dependency": [dep_peer, dep_legacy_peer, dep_lockfile, dep_py_module, dep_node_module, dep_pip_pin, dep_maven, dep_cache],
    "build": [build_ts, build_ts_pin, build_docker, build_toolchain],
    "lint": [lint_format, lint_types, lint_precommit_local],
    "test": [test_warning_filter, test_retry, test_timeout, test_port, test_quarantine],
    "config": [cfg_env, cfg_set_secret, cfg_yaml, cfg_tf, cfg_example],
    "infra": [infra_oom, infra_bigger_runner, infra_disk, infra_ratelimit, infra_retry, infra_runner_pin, infra_bump_version, infra_tflock],
    "rollout": [roll_imagepull, roll_verify_image, roll_crashloop, roll_probe, roll_atomic, roll_resources],
}

MIN_FIT = 0.2


def propose(diagnosis: Diagnosis, limit: int = 3) -> List[Fix]:
    """Rank fixes across all matching categories by fit x category share."""
    pool: List[Fix] = []
    for cand in diagnosis.candidates:
        for tpl in TEMPLATES.get(cand.category, []):
            fix = tpl(cand.tags, diagnosis.entities)
            if fix and fix.fit >= MIN_FIT:
                fix.score = round(fix.fit * cand.share, 3)
                pool.append(fix)
    if diagnosis.category == "unknown":
        return []
    pool.sort(key=lambda f: (-f.score, f.risk != "low"))
    return pool[:limit]
