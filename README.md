# Deploy Doctor Agent

A **rule-based** agent (no LLM yet). Give it a failed CI/CD log. It classifies the failure, cites the evidence lines, and proposes the **top 3 fixes as diffs**.

```text
$ python3 -m deploy_doctor samples/k8s_imagepull.log
Diagnosis: Deployment rollout (Kubernetes / Helm) (rollout), confidence 95%

Evidence:
  line 5: Warning  Failed  kubelet  Failed to pull image "ghcr.io/acme/checkout-api:3f9a1c2": ... not found
  line 6: Warning  Failed  kubelet  Error: ErrImagePull

Fix #1: Confirm `ghcr.io/acme/checkout-api:3f9a1c2` was actually pushed  [risk: low]
Fix #2: Make the release roll back automatically on failure  [risk: low]
--- a/.github/workflows/deploy.yml
+++ b/.github/workflows/deploy.yml
-      - run: helm upgrade app ./chart --install
+      - run: helm upgrade app ./chart --install --atomic --timeout 5m
Fix #3: Add an imagePullSecret for `ghcr.io/acme/checkout-api:3f9a1c2`  [risk: medium]
```

- **Problem:** failed deployments waste hours. The logs are long and the cause is usually a known pattern.
- **Solution:** an agent that ingests the failed run, classifies it, and proposes ranked fixes with diffs.
- **Impact (hypothesis):** lower mean time to recovery. Not yet measured on real incidents.

Project page: <https://alihabbache.github.io/Deploy-Doctor-Agent/> (source: [`docs/index.html`](docs/index.html))

## Try it

Python 3.9+, standard library only.

```bash
python3 -m deploy_doctor samples/k8s_imagepull.log      # text report
python3 -m deploy_doctor samples/oom_build.log --json   # for tools
python3 -m deploy_doctor samples/flaky_pytest.log --markdown   # for PR comments
cat my_failed_run.log | python3 -m deploy_doctor -      # stdin

python3 -m deploy_doctor.evaluate                       # accuracy on labelled logs
python3 -m unittest discover -s tests
```

Exit codes: `0` diagnosed, `1` unknown, `2` bad input.

## Pipeline

| Stage | File | Job |
|---|---|---|
| Ingest | `ingest.py` | Strip ANSI, timestamps and CI prefixes. Keep line numbers. Detect provider. |
| Classify | `classifier.py`, `rules.py` | Weighted regex rules score 7 categories: auth, dependency, build, test, config, infra, rollout. |
| Extract | `entities.py` | Pull names (env var, package, image, test, lock ID) from the log. |
| Propose | `fixes.py` | Fill fix templates with those names, rank by fit x category share, keep 3. |
| Report | `report.py`, `cli.py` | Text, JSON or Markdown. |

A log that matches nothing returns `unknown` and no fixes. It does not guess.

## Honest status

- This is a **proof of concept**: rule-based, offline, deterministic.
- `samples/` (11 logs) and `samples/holdout/` (7 logs, one of them this project's own real CI failure) are labelled in `expected.json` and all pass. I wrote them, so treat that as a smoke test and not a benchmark. Real-world accuracy is unknown.
- **Real-log check:** I ran it on 20 recent failed GitHub Actions logs from public repos (flask, requests, pytest, django, numpy, pandas, react). It returned `unknown` for 14 and a diagnosis for 6. Many of the 14 are lint, format or type-check failures (flake8, isort, ruff, mypy), which no rule covers yet. I did not hand-verify the 6, so there is no accuracy number. Coverage on real logs is low, and that is the next thing to fix.
- Diffs are **templates** with placeholders (for example `<ACCOUNT_ID>`). They are not patches against your real files.
- Confidence is match strength, capped at 95%. It is not a probability.
- Fixes are proposals. Nothing is applied automatically. Each carries a risk level.

## Roadmap

1. Collect and label 100+ real failed logs, then measure the top-3 hit rate. Add a `gh run view --log-failed` fetcher.
2. LLM fallback for low-confidence logs, and diffs generated from the user's real files.
3. GitHub Action that comments on failed runs, with an optional human-approved fix PR.
4. GitLab, Jenkins and CircleCI adapters.

## Add a rule

Add a `Rule(...)` in `deploy_doctor/rules.py`, a template in `deploy_doctor/fixes.py`, a labelled log in `samples/`, then run the evaluate command.

MIT licensed.
