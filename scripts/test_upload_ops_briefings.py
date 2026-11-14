"""Tests for upload_ops_briefings.py, with a fake gh in place of GitHub.

Run:  python -m unittest test_upload_ops_briefings
"""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("upload_ops_briefings", HERE / "upload_ops_briefings.py")
up = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(up)

REPO = "owner/site"


class FakeGh:
    """Holds releases as {tag: {asset: size}} and answers gh the way the CLI does."""

    def __init__(self, releases=None):
        self.releases = {tag: dict(assets) for tag, assets in (releases or {}).items()}
        self.calls = []

    def __call__(self, cmd, capture_output=True, text=True):
        self.calls.append(cmd)
        if cmd[1] == "api":
            tag = cmd[2].rsplit("/", 1)[1]
            if tag not in self.releases:
                return subprocess.CompletedProcess(cmd, 1, '{"message":"Not Found","status":"404"}',
                                                   "gh: Not Found (HTTP 404)\n")
            assets = [{"name": n, "size": s} for n, s in self.releases[tag].items()]
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"assets": assets}), "")
        verb, tag = cmd[2], cmd[3]
        if verb == "create":
            self.releases[tag] = {}
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if verb == "upload":
            for path in cmd[6:]:
                self.releases[tag][Path(path).name] = Path(path).stat().st_size
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)


def folder_with(*names):
    tmp = tempfile.TemporaryDirectory()
    for i, name in enumerate(names):
        (Path(tmp.name) / name).write_bytes(b"%PDF" + b"x" * (10 + i))
    return tmp


class UploadTests(unittest.TestCase):
    def test_release_url_uses_the_month_tag(self):
        self.assertEqual(up.release_url(REPO, "2026-11-09.pdf"),
                         "https://github.com/owner/site/releases/download/ops-briefings-2026-11/2026-11-09.pdf")
        with self.assertRaises(ValueError):
            up.release_url(REPO, "history.csv")

    def test_only_dated_pdfs_are_grouped_by_month(self):
        with folder_with("2026-10-31.pdf", "2026-11-01.pdf", "2026-11-02.pdf", "notes.pdf") as tmp:
            Path(tmp, "history.csv").write_text("date\n")
            months = up.local_pdfs(Path(tmp))
        self.assertEqual({k: [p.name for p in v] for k, v in months.items()},
                         {"2026-10": ["2026-10-31.pdf"], "2026-11": ["2026-11-01.pdf", "2026-11-02.pdf"]})

    def test_missing_months_are_created_and_every_pdf_uploaded(self):
        fake = FakeGh()
        with folder_with("2026-10-31.pdf", "2026-11-01.pdf") as tmp:
            summary = up.sync(REPO, Path(tmp), runner=fake)
        self.assertEqual(summary["created"], ["ops-briefings-2026-10", "ops-briefings-2026-11"])
        self.assertEqual(set(fake.releases), {"ops-briefings-2026-10", "ops-briefings-2026-11"})
        self.assertIn("2026-11-01.pdf", fake.releases["ops-briefings-2026-11"])
        create = next(c for c in fake.calls if c[2] == "create")
        self.assertIn("--latest=false", create)
        self.assertIn("FEMA Daily Ops Briefings, October 2026", create)

    def test_assets_already_there_are_not_uploaded_again(self):
        with folder_with("2026-11-01.pdf", "2026-11-02.pdf") as tmp:
            size = Path(tmp, "2026-11-01.pdf").stat().st_size
            fake = FakeGh({"ops-briefings-2026-11": {"2026-11-01.pdf": size}})
            summary = up.sync(REPO, Path(tmp), runner=fake)
        self.assertEqual(summary["created"], [])
        self.assertEqual(summary["uploaded"], ["ops-briefings-2026-11/2026-11-02.pdf"])
        self.assertEqual(summary["already_there"], 1)
        uploads = [c for c in fake.calls if c[2] == "upload"]
        self.assertEqual(len(uploads), 1)
        self.assertNotIn("--clobber", uploads[0])

    def test_a_size_mismatch_is_reported_and_never_replaced(self):
        with folder_with("2026-11-01.pdf") as tmp:
            fake = FakeGh({"ops-briefings-2026-11": {"2026-11-01.pdf": 1}})
            summary = up.sync(REPO, Path(tmp), runner=fake)
        self.assertEqual(len(summary["size_mismatch"]), 1)
        self.assertEqual(fake.releases["ops-briefings-2026-11"]["2026-11-01.pdf"], 1)
        self.assertFalse([c for c in fake.calls if c[2] == "upload"])

    def test_dry_run_changes_nothing(self):
        fake = FakeGh()
        with folder_with("2026-11-01.pdf") as tmp:
            summary = up.sync(REPO, Path(tmp), dry_run=True, runner=fake)
        self.assertEqual(summary["uploaded"], ["ops-briefings-2026-11/2026-11-01.pdf"])
        self.assertEqual(fake.releases, {})

    def test_other_gh_errors_stop_the_run(self):
        def broken(cmd, capture_output=True, text=True):
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 401: Bad credentials")
        with folder_with("2026-11-01.pdf") as tmp, self.assertRaises(RuntimeError):
            up.sync(REPO, Path(tmp), runner=broken)

    def test_no_long_dashes(self):
        for path in (HERE / "upload_ops_briefings.py", Path(__file__)):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
