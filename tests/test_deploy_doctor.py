import json
import subprocess
import sys
import unittest
from pathlib import Path

from deploy_doctor.agent import diagnose
from deploy_doctor.evaluate import run
from deploy_doctor.ingest import ingest
from deploy_doctor.report import to_dict, to_json, to_markdown, to_text

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


def sample(name: str):
    return diagnose((SAMPLES / name).read_text(encoding="utf-8"))


class IngestTests(unittest.TestCase):
    def test_strips_ansi_timestamps_and_markers(self):
        raw = "\x1b[31m2026-01-01T00:00:00.123Z ##[error]boom\x1b[0m\n\n"
        log = ingest(raw)
        self.assertEqual([l.text for l in log.lines], ["boom"])
        self.assertEqual(log.lines[0].no, 1)

    def test_keeps_original_line_numbers_across_blank_lines(self):
        log = ingest("a\n\n\nb")
        self.assertEqual([l.no for l in log.lines], [1, 4])

    def test_github_cli_prefix_yields_step_name(self):
        log = ingest("deploy\tRun aws sync\t2026-01-01T00:00:00Z bad creds")
        self.assertEqual(log.lines[0].step, "Run aws sync")
        self.assertEqual(log.lines[0].text, "bad creds")

    def test_provider_detection(self):
        self.assertEqual(ingest("##[error]x").provider, "github")
        self.assertEqual(ingest("Running with gitlab-runner 16").provider, "gitlab")
        self.assertEqual(ingest("[Pipeline] sh").provider, "jenkins")
        self.assertEqual(ingest("hello").provider, "generic")


class ClassifierTests(unittest.TestCase):
    def test_every_labelled_sample(self):
        for d in (SAMPLES, SAMPLES / "holdout"):
            rows, accuracy = run(d)
            for r in rows:
                with self.subTest(file=r["file"]):
                    self.assertTrue(r["category_ok"], f"{r['file']}: {r['expected']} != {r['got']}")
                    self.assertTrue(r["top_fix_ok"], f"{r['file']}: top fix was {r['top_fix']!r}")
            self.assertEqual(accuracy, 1.0)

    def test_unknown_gives_no_fixes_and_zero_confidence(self):
        r = sample("unknown_noise.log")
        self.assertEqual(r.diagnosis.category, "unknown")
        self.assertEqual(r.fixes, [])
        self.assertEqual(r.diagnosis.confidence, 0.0)

    def test_confidence_is_capped_and_never_certain(self):
        for f in SAMPLES.glob("*.log"):
            self.assertLessEqual(sample(f.name).diagnosis.confidence, 0.95)

    def test_evidence_points_at_real_lines(self):
        raw = (SAMPLES / "missing_env_var.log").read_text().splitlines()
        for e in sample("missing_env_var.log").diagnosis.evidence:
            self.assertIn(e.text, raw[e.line_no - 1])

    def test_mixed_log_reports_alternative_category(self):
        r = sample("jest_port_timeout.log")
        self.assertEqual(r.diagnosis.category, "test")

    def test_entities_extracted(self):
        e = sample("missing_env_var.log").diagnosis.entities
        self.assertEqual(e["env_var"], "DATABASE_URL")
        self.assertEqual(sample("terraform_lock.log").diagnosis.entities["lock_id"],
                         "8f1c2d3e-4a5b-6c7d-8e9f-0a1b2c3d4e5f")


class FixTests(unittest.TestCase):
    def test_at_most_three_fixes_ranked_by_score(self):
        for f in SAMPLES.glob("*.log"):
            fixes = sample(f.name).fixes
            self.assertLessEqual(len(fixes), 3)
            self.assertEqual([x.score for x in fixes], sorted((x.score for x in fixes), reverse=True))

    def test_every_fix_is_actionable(self):
        for f in SAMPLES.glob("*.log"):
            for fix in sample(f.name).fixes:
                with self.subTest(file=f.name, fix=fix.title):
                    self.assertTrue(fix.diff or fix.command)
                    self.assertIn(fix.risk, {"low", "medium", "high"})

    def test_diff_is_unified_format(self):
        fix = sample("missing_env_var.log").fixes[0]
        self.assertTrue(fix.diff.startswith("--- a/"))
        self.assertIn("+++ b/.github/workflows/deploy.yml", fix.diff)
        self.assertIn("+          DATABASE_URL: ${{ secrets.DATABASE_URL }}", fix.diff)

    def test_new_file_diff_uses_dev_null(self):
        fix = [x for x in sample("npm_peer_conflict.log").fixes if x.file == ".npmrc"][0]
        self.assertTrue(fix.diff.startswith("--- /dev/null"))

    def test_high_risk_fix_is_labelled(self):
        fix = sample("terraform_lock.log").fixes[0]
        self.assertEqual(fix.risk, "high")
        self.assertIn("force-unlock 8f1c2d3e", fix.command)


class ReportTests(unittest.TestCase):
    def test_json_round_trip(self):
        d = json.loads(to_json(sample("k8s_imagepull.log")))
        self.assertEqual(d["category"], "rollout")
        self.assertEqual(len(d["fixes"]), 3)
        self.assertEqual(d["fixes"][0]["rank"], 1)

    def test_markdown_and_text_render(self):
        r = sample("github_aws_auth.log")
        self.assertIn("```diff", to_markdown(r))
        self.assertIn("Fix #1", to_text(r))
        self.assertIn("Nothing was applied", to_text(r))

    def test_unknown_text_message(self):
        self.assertIn("unknown", to_text(sample("unknown_noise.log")))
        self.assertEqual(to_dict(sample("unknown_noise.log"))["fixes"], [])


class CliTests(unittest.TestCase):
    def cli(self, *args, stdin=None):
        return subprocess.run([sys.executable, "-m", "deploy_doctor", *args],
                              input=stdin, capture_output=True, text=True, cwd=ROOT)

    def test_file_input(self):
        p = self.cli(str(SAMPLES / "oom_build.log"))
        self.assertEqual(p.returncode, 0)
        self.assertIn("Fix #1", p.stdout)

    def test_stdin_input_and_ansi(self):
        p = self.cli("-", "--json", stdin="\x1b[31mError:\x1b[0m DATABASE_URL is not set\nprocess exit code 1\n")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout)["category"], "config")

    def test_unknown_exits_1(self):
        self.assertEqual(self.cli(str(SAMPLES / "unknown_noise.log")).returncode, 1)

    def test_missing_file_exits_2(self):
        p = self.cli("nope.log")
        self.assertEqual(p.returncode, 2)
        self.assertIn("cannot read", p.stderr)

    def test_empty_input_exits_2(self):
        self.assertEqual(self.cli("-", stdin="  \n").returncode, 2)


if __name__ == "__main__":
    unittest.main()
