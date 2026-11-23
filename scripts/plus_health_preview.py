#!/usr/bin/env python3
"""Preview what the next Plus refresh's health report will say with this branch.

A pull request that adds or removes records shows its effect on the health
report only at the refresh after it is merged. Pull request 245 (merged
2026-11-22) left bare hours-of-service and weight waivers out of the FMCSA
supplement; Connecticut, Louisiana and New Hampshire lost records with them
and were yellow ("Declarations fell") on that day's refresh. This shows such
changes before the merge, in a form that can go in the pull request.

How: the files the build reads (scripts/, plus/, data/decl-index/) are copied
twice into a temporary folder, once from this checkout (with any uncommitted
changes) and once from the base branch. In each copy every state's FMCSA
supplement is rewritten and its summary rebuilt the way build-plus.py does it
without --collect, then graded with that copy's own plus_health.py against
the last refresh's plus/_health/health.json. What differs between the two
copies is what the branch changes. The checkout itself is not written to.

States that are not green now, or would not be on the next refresh, are
listed too, with when each would turn green if collecting works.

What it cannot know: the state scrapers are not run (they need the state
sites), so each state's source is taken to return what it returned on the
last refresh, and storm matches are the last refresh's, so records a branch
adds count as unmatched until a refresh joins them to storms.

    python3 scripts/plus_health_preview.py                  # against origin/main
    python3 scripts/plus_health_preview.py --base HEAD~1
    python3 scripts/plus_health_preview.py --now 2026-11-29T12:00:00+00:00
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# What build-plus.py and plus_health.py read.
TREE_PATHS = ("scripts", "plus", "data/decl-index")
# What each state's source returned on the last refresh. The scrapers are
# not run here, so these are carried over from the last refresh's summaries.
COLLECTION_FIELDS = (
    "source_status", "source_records_returned", "source_records_saved_before",
    "collection_error", "collection_failed", "kept_saved_records", "kept_saved_values",
    "retried", "retry_status", "retry_error", "first_attempt", "timing",
)
BAD_SOURCES = ("empty", "failed")      # as in plus_health.py
# Refreshes looked ahead when saying when a state turns green: enough for a
# failure to leave the grader's 4-run window with room to spare.
CLEAN_RUNS = 6
RUN_INTERVAL = timedelta(days=7)       # the weekly schedule in update-plus.yaml
NUMBERS = (
    ("declarations", "declarations"),
    ("dated", "with a signing date"),
    ("titled", "with a title"),
    ("linked", "with a working link"),
    ("storm_matched", "matched to storms"),
    ("excluded", "excluded on review"),
)
# What is kept of each state's predicted grade.
KEPT = ("grade", "reasons", "notes", "source", "declarations", "dated", "titled", "linked",
        "storm_matched", "excluded", "last_good_collection", "history")


def load_grader(tree: Path):
    """The plus_health.py of one copy, loaded under a name of its own."""
    spec = importlib.util.spec_from_file_location(
        "plus_health_preview_grader", str(tree / "scripts" / "plus_health.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def parse_now(text: str | None) -> datetime:
    moment = datetime.fromisoformat(text) if text else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def carry_collection(built: dict, last: dict | None) -> dict:
    """A rebuilt summary with what the state's source returned on the last
    refresh, since the scrapers are not run here."""
    summary = dict(built)
    for field in COLLECTION_FIELDS:
        if last and field in last:
            summary[field] = last[field]
    return summary


def clean(grader, summary: dict | None) -> dict | None:
    """The summary of a refresh whose collection works: a source that failed
    or returned nothing last time returns its records, with none kept from
    earlier runs. A source that worked is taken to work the same way again."""
    if not summary:
        return summary
    failing = grader.infer_source(summary) in BAD_SOURCES
    summary = dict(summary, retried=False)
    for field in ("retry_status", "retry_error", "first_attempt"):
        summary.pop(field, None)
    if failing:
        summary.update(source_status="ok", collection_error="", collection_failed=False,
                       kept_saved_records=0)
    return summary


def grade_run(grader, builder, state: dict, summary: dict | None, numbers: dict, history: list[dict],
              prior: dict | None, run_day, now: datetime) -> dict:
    """One refresh's grade for one state, made the way plus_health.main()
    makes it. history is the runs before this one; prior is the state's entry
    from the run before."""
    count = ((summary or {}).get("metrics") or {}).get("action_count") or 0
    since = builder.extract_coverage_start_label(state["abbreviation"],
                                                 (summary or {}).get("coverage", ""), count)
    entry = {"at": grader.run_label(now),
             "source": grader.infer_source(summary) if summary else "unknown",
             "declarations": count}
    history = (list(history) + [entry])[-grader.HISTORY_LENGTH:]
    last_good = grader.last_good_collection(prior, history)
    if prior is None and len(history) > 1:
        prior = {"declarations": history[-2].get("declarations")}
    graded = grader.grade_state(state, summary, numbers, history, prior, run_day, since,
                                last_good=last_good, now=now)
    graded.update(name=state["name"], since=since, history=history)
    return graded


def predict(tree: Path, health: dict | None, last_root: Path, now: datetime, rebuild: bool = True,
            clean_runs: int = CLEAN_RUNS) -> dict:
    """How the next refresh would grade every state from the files in tree,
    and how the refreshes after it would if collecting works each time.

    health is the last refresh's health.json; last_root holds the last
    refresh's state-summary.json files, which say what each source returned.
    With rebuild, each state's FMCSA supplement is rewritten in tree and its
    summary rebuilt, so tree must be a scratch copy. Without it, the
    summaries in tree are graded as they are, as plus_health.py grades them."""
    if rebuild and (tree / ".git").exists():
        raise SystemExit(f"{tree} is a git checkout; the preview writes only into scratch copies")
    grader = load_grader(tree)
    builder = grader.load_builder(tree)
    states = grader.load_states(tree)
    if rebuild:
        builder.NOAA_DATA_THROUGH = builder.noaa_data_through(tree)
    previous = (health or {}).get("states") or {}

    summaries = {}
    for state in states:
        state_dir = tree / "plus" / state["slug"]
        if not rebuild:
            summaries[state["abbreviation"]] = read_json(state_dir / "state-summary.json")
            continue
        # The refresh rewrites each supplement from the saved FMCSA entries
        # before it builds, so a change to them or to the rules that pick
        # them shows here as it will there.
        try:
            builder.write_fmcsa_supplement(state, state_dir, tree)
        except Exception as exc:  # as in build-plus.py: never breaks a state
            print(f"WARNING {state['abbreviation']}: FMCSA supplement not written ({exc})",
                  file=sys.stderr)
        built = builder.process_state(state, tree, False, False, True)
        last = read_json(last_root / "plus" / state["slug"] / "state-summary.json")
        summaries[state["abbreviation"]] = carry_collection(built, last)
    built_days = [datetime.strptime(s["generated_on"], "%Y-%m-%d").date()
                  for s in summaries.values() if s and s.get("generated_on")]
    run_day = max(built_days) if built_days else None
    shared = grader.file_hash(tree / "plus" / grader.CLASSIFIER)

    result = {"at": grader.run_label(now), "order": [s["abbreviation"] for s in states], "states": {}}
    for state in states:
        ab = state["abbreviation"]
        state_dir = tree / "plus" / state["slug"]
        summary = summaries[ab]
        try:
            numbers = grader.measure(builder, state, state_dir)
        except Exception as exc:  # as in plus_health.py
            numbers = {"actions": 0, "dated": 0, "titled": 0, "linked": 0, "storm_matched": 0}
            print(f"WARNING {ab}: could not read its files ({exc})", file=sys.stderr)
        own = grader.file_hash(state_dir / grader.CLASSIFIER)
        numbers["classifier_same"] = (own == shared) if own and shared else None
        prior = previous.get(ab)
        history = list((prior or {}).get("history") or [])
        upcoming = grade_run(grader, builder, state, summary, numbers, history, prior, run_day, now)
        runs = project(grader, builder, state, summary, numbers, history, prior, run_day, now,
                       clean_runs)
        gaps = (summary or {}).get("federal_without_state") or {}
        result["states"][ab] = {"name": state["name"],
                                "next": {key: upcoming.get(key) for key in KEPT},
                                "clean": runs, "gaps": list(gaps.get("ids") or [])}
    return result


def project(grader, builder, state: dict, summary: dict | None, numbers: dict, history: list[dict],
            prior: dict | None, run_day, now: datetime, runs: int = CLEAN_RUNS) -> list[dict]:
    """The grades of the next refreshes, one a week from now, if collecting
    works on each (see clean())."""
    graded_runs, before, past, working = [], prior, history, clean(grader, summary)
    for index in range(runs):
        graded = grade_run(grader, builder, state, working, numbers, past, before, run_day,
                           now + RUN_INTERVAL * index)
        graded_runs.append({"grade": graded["grade"], "reasons": graded["reasons"]})
        before, past = graded, graded["history"]
    return graded_runs


# ---------------------------------------------------------------- the report

def counts(prediction: dict) -> dict:
    grades = [row["next"]["grade"] for row in prediction["states"].values()]
    return {grade: grades.count(grade) for grade in ("green", "yellow", "red")}


def counts_text(numbers: dict) -> str:
    return f"{numbers.get('green', 0)} green, {numbers.get('yellow', 0)} yellow, {numbers.get('red', 0)} red"


def gap_total(prediction: dict) -> int:
    return sum(len(row["gaps"]) for row in prediction["states"].values())


def gap_change(before: list[str], after: list[str]) -> str:
    if before == after:
        return ""
    closed = [item for item in before if item not in after]
    opened = [item for item in after if item not in before]
    parts = (["closes " + ", ".join(closed)] if closed else []) + \
            (["opens " + ", ".join(opened)] if opened else [])
    return (f"Federal declarations with no state declaration {len(before)} to {len(after)}"
            + (f" ({'; '.join(parts)})" if parts else "") + ".")


def number_changes(before: dict, after: dict) -> str:
    """The counts that changed. Signing dates, titles, links and storm
    matches are given only where they did not move with the declarations
    (three records added, all dated, says nothing new about dating)."""
    moved = (after.get("declarations") or 0) - (before.get("declarations") or 0)
    changed = []
    for key, label in NUMBERS:
        old, new = before.get(key), after.get(key)
        if old is None or new is None or old == new:
            continue
        if key not in ("declarations", "excluded") and new - old == moved:
            continue
        changed.append(f"{label} {old} to {new}")
    if not changed:
        return ""
    text = "; ".join(changed)
    return text[0].upper() + text[1:] + "."


def branch_changes(base: dict, branch: dict) -> list[str]:
    """One line per state whose next refresh differs with the branch."""
    lines = []
    for ab in branch["order"]:
        after = branch["states"][ab]
        before = base["states"].get(ab)
        if before is None:
            lines.append(f"- {ab} {after['name']}: not on the base branch; "
                         f"{after['next']['grade']} on the next refresh.")
            continue
        old, new = before["next"], after["next"]
        parts = []
        if old["grade"] == new["grade"]:
            parts.append(f"{new['grade']} either way.")
        else:
            parts.append(f"{old['grade']} without this branch, {new['grade']} with it.")
        added = [reason for reason in new["reasons"] if reason not in old["reasons"]]
        dropped = [reason for reason in old["reasons"] if reason not in new["reasons"]]
        noted = [note for note in new["notes"] if note not in old["notes"]]
        unnoted = [note for note in old["notes"] if note not in new["notes"]]
        if added:
            parts.append("With it: " + " ".join(added))
        if dropped:
            parts.append("No longer: " + " ".join(dropped))
        if noted:
            parts.append("New note: " + " ".join(noted))
        if unnoted:
            parts.append("No longer noted: " + " ".join(unnoted))
        numbers = number_changes(old, new)
        gaps = gap_change(before["gaps"], after["gaps"])
        if len(parts) == 1 and old["grade"] == new["grade"] and not numbers and not gaps:
            continue
        lines.append(f"- {ab} {after['name']}: " + " ".join(part for part in parts + [numbers, gaps] if part))
    return lines


def when_green(runs: list[dict], failing: bool, shown: list[str]) -> str:
    """When a state turns green if collecting works from the next refresh on.
    failing: its source failed or returned nothing on the last refresh.
    shown: reasons the line has already given, not repeated."""
    for index, run in enumerate(runs, start=1):
        if run["grade"] == "green":
            where = "on the next refresh" if index == 1 else f"on refresh {index} from now"
            if failing:
                return f"If collecting works from the next refresh on: green {where}."
            return f"Green {where} if collecting keeps working."
    if not runs:
        return ""
    lead = "Even if collecting works, it does not" if failing else "Does not"
    left = runs[-1]["reasons"]
    return f"{lead} turn green on its own" + ("." if left == shown else ": " + " ".join(left))


def outlook(last: dict | None, prediction: dict) -> list[str]:
    """One line per state that is not green now or would not be next time."""
    lines = []
    for ab in prediction["order"]:
        row = prediction["states"][ab]
        now = ((last or {}).get("states") or {}).get(ab) or {}
        upcoming = row["next"]
        if now.get("grade", "green") == "green" and upcoming["grade"] == "green":
            continue
        parts = []
        if now.get("grade") == "green":
            parts.append("green now.")
        elif now.get("grade"):
            parts.append(f"{now['grade']} now: " + " ".join(now.get("reasons") or []))
        failing = upcoming.get("source") in BAD_SOURCES
        label = "Next refresh, if collecting fails again" if failing else "Next refresh"
        shown = now.get("reasons") or []
        if upcoming["grade"] == "green":
            parts.append(f"{label}: green.")
        elif upcoming["grade"] == now.get("grade") and failing:
            # The same failure, a run older; its sentence changes only in
            # the run count and the days since the last good collection.
            parts.append(f"{label}: {upcoming['grade']}.")
        elif upcoming["grade"] == now.get("grade") and upcoming["reasons"] == shown:
            parts.append(f"{label}: {upcoming['grade']}, for the same reasons.")
        else:
            parts.append(f"{label}: {upcoming['grade']}: " + " ".join(upcoming["reasons"]))
            shown = upcoming["reasons"]
        if failing or upcoming["grade"] != "green":
            parts.append(when_green(row["clean"], failing, shown))
        lines.append(f"- {ab} {row['name']}: " + " ".join(part for part in parts if part))
    return lines


def render(base: dict, branch: dict, last: dict | None, context: dict) -> str:
    lines = ["# Plus health preview", "",
             f"{context['branch']} against {context['base']}, for a refresh at {branch['at']}.",
             ""]
    if last:
        lines.append(f"Last refresh ({last.get('generated_at_label', 'time not recorded')}): "
                     f"{counts_text(last.get('counts') or {})}.")
    lines += [f"Next refresh with this branch: {counts_text(counts(branch))}; "
              f"without it: {counts_text(counts(base))}.",
              f"Federal declarations with no state declaration: {gap_total(branch)} with this "
              f"branch, {gap_total(base)} without.",
              "", "## What this branch changes on the next refresh", ""]
    changes = branch_changes(base, branch)
    if context.get("same"):
        lines.append(f"Nothing: these files match {context['base']}.")
    else:
        lines += changes or ["Nothing: every state grades the same, with the same counts and "
                             "federal gaps, with or without it."]
    lines += ["", "## States not green now or on the next refresh", ""]
    lines += outlook(last, branch) or ["None."]
    lines += ["", "## What this preview cannot know", "",
              "- The state scrapers are not run, so each state's source is taken to return what "
              "it returned on the last refresh.",
              "- Storm matches are the last refresh's, so records this branch adds count as "
              "unmatched until a refresh joins them to storms."]
    if context.get("code"):
        lines.append("- This branch changes code the refresh runs and this preview does not: "
                     + ", ".join(context["code"]) + ". The records shown are the ones the "
                     "current code saved.")
    if context.get("behind"):
        lines.append(f"- This branch is {context['behind']} commit"
                     f"{'' if context['behind'] == 1 else 's'} behind {context['base']} in these "
                     "files, so the changes since are previewed in its older copies. Rebase "
                     "onto it for an exact preview.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the copies

def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout.strip()


def extract(ref: str, target: Path) -> None:
    """The build's files as they are at ref, without touching the checkout."""
    target.mkdir(parents=True)
    paths = [path for path in TREE_PATHS
             if subprocess.run(["git", "cat-file", "-e", f"{ref}:{path}"], cwd=ROOT,
                               capture_output=True).returncode == 0]
    archive = subprocess.Popen(["git", "archive", "--format=tar", ref, *paths], cwd=ROOT,
                               stdout=subprocess.PIPE)
    unpacked = subprocess.run(["tar", "-x", "-C", str(target)], stdin=archive.stdout)
    archive.stdout.close()
    if archive.wait() or unpacked.returncode:
        raise SystemExit(f"could not copy the files at {ref}")


def copy_checkout(source: Path, target: Path) -> None:
    for path in TREE_PATHS:
        if (source / path).is_dir():
            shutil.copytree(source / path, target / path,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def changed_code(base: Path, branch: Path) -> list[str]:
    """Code under plus/ that the refresh runs (scrapers, adapters, the storm
    join) and this preview does not, where the two copies differ."""
    names = set()
    for tree in (base, branch):
        names |= {path.relative_to(tree).as_posix() for path in (tree / "plus").rglob("*.py")
                  if "__pycache__" not in path.parts and not path.name.startswith("test_")}
    return sorted(name for name in names
                  if not ((base / name).is_file() and (branch / name).is_file()
                          and (base / name).read_bytes() == (branch / name).read_bytes()))


def run_predictions(trees: dict[str, Path], health: Path, last_root: Path, now: datetime,
                    out_dir: Path) -> dict[str, dict]:
    """Each copy in its own process, side by side, so each loads its own
    build-plus.py and plus_health.py."""
    running = {}
    for name, tree in trees.items():
        out = out_dir / f"{name}.json"
        command = [sys.executable, str(Path(__file__).resolve()), "--predict-tree", str(tree),
                   "--health", str(health), "--last", str(last_root), "--now", now.isoformat(),
                   "--json-out", str(out)]
        running[name] = (subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          text=True), out)
    results = {}
    for name, (process, out) in running.items():
        _, errors = process.communicate()
        if process.returncode:
            raise SystemExit(f"the preview of the {name} copy failed:\n{errors[-3000:]}")
        results[name] = json.loads(out.read_text(encoding="utf-8"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview the next Plus refresh's health report "
                                                 "with this branch")
    parser.add_argument("--base", default="origin/main",
                        help="branch or commit to compare with (default origin/main, as last fetched)")
    parser.add_argument("--now", help="when the next refresh runs, ISO 8601 (default now)")
    parser.add_argument("--branch-root", type=Path, default=ROOT,
                        help="folder whose files are previewed (default this checkout)")
    parser.add_argument("--predict-tree", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--health", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--last", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--json-out", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    now = parse_now(args.now)

    if args.predict_tree:
        result = predict(args.predict_tree.resolve(), read_json(args.health) if args.health else None,
                         args.last.resolve(), now)
        args.json_out.write_text(json.dumps(result), encoding="utf-8")
        return 0

    try:
        base_sha = git("rev-parse", "--verify", "--quiet", f"{args.base}^{{commit}}")
    except subprocess.CalledProcessError:
        parser.error(f"{args.base} is not a branch or commit here")
    branch_root = args.branch_root.resolve()
    in_checkout = branch_root == ROOT
    context = {"base": f"{args.base} ({base_sha[:9]})"}
    if in_checkout:
        head = git("rev-parse", "HEAD")
        name = git("rev-parse", "--abbrev-ref", "HEAD")
        dirty = bool(git("status", "--porcelain", "--", *TREE_PATHS))
        context["branch"] = (f"Branch {name} ({head[:9]})"
                             + (" with uncommitted changes" if dirty else ""))
        context["same"] = head == base_sha and not dirty
        context["behind"] = int(git("rev-list", "--count", f"HEAD..{base_sha}", "--", *TREE_PATHS))
    else:
        context["branch"] = f"The files in {branch_root}"

    scratch = Path(tempfile.mkdtemp(prefix="plus_health_preview_"))
    try:
        base_tree = scratch / "base"
        extract(base_sha, base_tree)
        trees = {"base": base_tree}
        if not context.get("same"):
            trees["branch"] = scratch / "branch"
            copy_checkout(branch_root, trees["branch"])
            context["code"] = changed_code(base_tree, trees["branch"])
        health = base_tree / "plus" / "_health" / "health.json"
        last = read_json(health)
        # Both copies are graded against the base branch's last refresh,
        # which is what the refresh after a merge will read.
        results = run_predictions(trees, health, base_tree, now, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(render(results["base"], results.get("branch", results["base"]), last, context), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
