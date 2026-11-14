#!/usr/bin/env python3
"""Copy archived FEMA Daily Ops Briefing PDFs to monthly GitHub releases.

The PDFs are too large to keep publishing on GitHub Pages (the site has a
1 GB limit), so each one is also kept as a release asset:

    release tag   ops-briefings-YYYY-MM
    asset name    YYYY-MM-DD.pdf
    download URL  https://github.com/<repo>/releases/download/ops-briefings-YYYY-MM/YYYY-MM-DD.pdf

Every dated PDF in archive/ops-briefings/ is checked. A month's release is
created the first time it is needed, and a PDF is uploaded only when the
release does not already hold an asset of that name. An asset that exists
with a different size is reported and the run fails, so a release copy is
never replaced without someone looking at it.

Needs the GitHub CLI (gh) with GH_TOKEN set, which the GitHub Actions runner
provides. The repository comes from GITHUB_REPOSITORY, or --repo.

Usage:
    python scripts/upload_ops_briefings.py [--repo owner/name] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ARCHIVE_DIR = Path(os.environ.get("DD_OUT", "archive")) / "ops-briefings"
TAG_PREFIX = "ops-briefings-"
DATED_PDF = re.compile(r"(\d{4})-(\d{2})-\d{2}\.pdf")
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def tag_for(month_key: str) -> str:
    return TAG_PREFIX + month_key


def release_url(repo: str, filename: str) -> str:
    """The public download URL of one archived briefing."""
    found = DATED_PDF.fullmatch(filename)
    if not found:
        raise ValueError(f"not a dated briefing PDF: {filename}")
    return f"https://github.com/{repo}/releases/download/{tag_for(found.group(1) + '-' + found.group(2))}/{filename}"


def local_pdfs(folder: Path = ARCHIVE_DIR) -> dict[str, list[Path]]:
    """Dated PDFs on disk, grouped by YYYY-MM."""
    months: dict[str, list[Path]] = defaultdict(list)
    for pdf in sorted(folder.glob("*.pdf")):
        found = DATED_PDF.fullmatch(pdf.name)
        if found:
            months[f"{found.group(1)}-{found.group(2)}"].append(pdf)
    return dict(months)


def gh(args: list[str], runner=subprocess.run) -> subprocess.CompletedProcess:
    return runner(["gh", *args], capture_output=True, text=True)


def release_assets(repo: str, tag: str, runner=subprocess.run) -> dict[str, int] | None:
    """Asset name to size for an existing release, or None if there is no release."""
    # The REST endpoint, not "gh release view", which needs GraphQL.
    result = gh(["api", f"repos/{repo}/releases/tags/{tag}"], runner)
    if result.returncode != 0:
        if "HTTP 404" in (result.stderr or "") or "Not Found" in (result.stdout or ""):
            return None
        raise RuntimeError(f"could not read release {tag}: {(result.stderr or '').strip()}")
    return {a["name"]: int(a["size"]) for a in json.loads(result.stdout or "{}").get("assets", [])}


def sync(repo: str, folder: Path = ARCHIVE_DIR, dry_run: bool = False, runner=subprocess.run) -> dict:
    summary = {"created": [], "uploaded": [], "already_there": 0, "size_mismatch": []}
    for month_key, pdfs in sorted(local_pdfs(folder).items()):
        tag = tag_for(month_key)
        assets = release_assets(repo, tag, runner)
        if assets is None:
            year, month = month_key.split("-")
            title = f"FEMA Daily Ops Briefings, {MONTHS[int(month) - 1]} {year}"
            notes = (f"Archived FEMA Daily Operations Briefing PDFs for {MONTHS[int(month) - 1]} {year}, captured by "
                     "DisasterData.IO. One file per briefing date (YYYY-MM-DD.pdf). Each briefing has its own page "
                     "at https://disasterdata.io/ops-briefings/.")
            summary["created"].append(tag)
            if not dry_run:
                made = gh(["release", "create", tag, "--repo", repo, "--title", title, "--notes", notes,
                           "--latest=false"], runner)
                if made.returncode != 0:
                    raise RuntimeError(f"could not create release {tag}: {(made.stderr or '').strip()}")
            assets = {}
        missing = []
        for pdf in pdfs:
            size = pdf.stat().st_size
            if pdf.name not in assets:
                missing.append(pdf)
            elif assets[pdf.name] != size:
                summary["size_mismatch"].append(f"{tag}/{pdf.name}: release {assets[pdf.name]} bytes, local {size}")
            else:
                summary["already_there"] += 1
        if missing:
            summary["uploaded"].extend(f"{tag}/{p.name}" for p in missing)
            if not dry_run:
                sent = gh(["release", "upload", tag, "--repo", repo, *[str(p) for p in missing]], runner)
                if sent.returncode != 0:
                    raise RuntimeError(f"could not upload to {tag}: {(sent.stderr or '').strip()}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--dry-run", action="store_true", help="report what would change and change nothing")
    args = parser.parse_args(argv)
    if not args.repo:
        print("ERROR: no repository; pass --repo owner/name or set GITHUB_REPOSITORY.", file=sys.stderr)
        return 2
    summary = sync(args.repo, dry_run=args.dry_run)
    prefix = "Would " if args.dry_run else ""
    for tag in summary["created"]:
        print(f"{prefix}create release {tag}")
    for item in summary["uploaded"]:
        print(f"{prefix}upload {item}")
    print(f"{summary['already_there']} PDF(s) already in their release.")
    if summary["size_mismatch"]:
        for item in summary["size_mismatch"]:
            print(f"ERROR: size differs, left as is: {item}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
