"""Health check for every DisasterData Plus state, run after each refresh.

Grades all 50 states green, yellow or red, says why in plain words, and keeps
a short history so a source that fails every few weeks is caught. Before
this, problems surfaced one state at a time, whenever someone looked: a
state whose site refused every request still showed its saved records, and
a state collecting the wrong list simply showed 0.

Writes:
  plus/_health/health.json   current grades and the last runs per state
  plus/_health/HEALTH.md     the same as a readable report
  --issue-body-out PATH      the report, for the "Plus health report" issue
  --changes-out PATH         grade changes since the last run, for a comment
  $GITHUB_STEP_SUMMARY       the report, shown on the workflow run page

The _health folder is kept off the public site (Jekyll skips folders that
start with an underscore) but is visible in the repository. This script
never fails the run.

    python -u scripts/plus_health.py [--issue-body-out F] [--changes-out F]
    python -u scripts/plus_health.py --seed-from-git 16   # one-off, rebuilds history
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

GREEN, YELLOW, RED = "green", "yellow", "red"
HISTORY_LENGTH = 12
FLAKY_WINDOW = 4          # runs looked at for a source that fails now and then
THIN_BELOW = 10           # fewer declarations than this reads as a short coverage window
BAD_SOURCES = ("empty", "failed")
SOURCE_WORDS = {
    "ok": "returned everything",
    "partial": "returned part",
    "empty": "returned nothing",
    "failed": "failed",
    "not_collected": "not collected",
    "unknown": "not recorded",
}
RULES = """How grades are set

Red, needs attention now:
- the state site failed or returned nothing, on this run and on the retry
- no declarations on the page
- fewer than half the declarations have a signing date, so the rest cannot be matched to storms
- declarations fell by more than a fifth since the last run
- the page was not rebuilt on this run

Yellow, working with gaps:
- the source failed on another of the last 4 runs
- the source left out more than a tenth of the saved records, which are shown from earlier runs
- fewer than 10 declarations, which usually means the source only covers recent years
- more than a tenth of the declarations have no signing date, title or working link
- fewer than a quarter of the dated declarations matched any storm record
- declarations fell since the last run

Green: none of the above."""


def load_builder(repo_root: Path):
    spec = importlib.util.spec_from_file_location(
        "build_plus", str(repo_root / "scripts" / "build-plus.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("build_plus", module)
    spec.loader.exec_module(module)
    return module


def load_states(repo_root: Path) -> list[dict]:
    manifest = json.loads((repo_root / "scripts" / "plus" / "state-manifest.json").read_text())
    return manifest if isinstance(manifest, list) else manifest["states"]


def infer_source(summary: dict) -> str:
    """What the source returned, from a summary. Summaries written before the
    source was recorded directly are read the same way the numbers imply:
    if every record on the page had to be kept from earlier runs, the source
    returned nothing."""
    status = summary.get("source_status")
    if status:
        if summary.get("retried") and summary.get("retry_status"):
            return summary["retry_status"]
        return status
    if summary.get("collection_failed"):
        return "failed"
    kept = summary.get("kept_saved_records") or 0
    count = (summary.get("metrics") or {}).get("action_count") or 0
    if kept and kept >= count:
        return "empty"
    if kept:
        return "partial"
    return "unknown"


def short_error(text: str) -> str:
    text = (text or "").replace("Collection failed: ", "").strip()
    return text if len(text) <= 140 else text[:137] + "..."


def measure(bp, state: dict, state_dir: Path) -> dict:
    """What the state's page actually shows: the same loaders the page uses."""
    actions, _ = bp.load_state_actions(state, state_dir)
    storm_rows, _ = bp.load_storm_match_rows(state_dir)
    matched_ids = {bp.clean(row.get("declaration_id")) for row in storm_rows}
    dated = [a for a in actions if a["date_signed"]]
    return {
        "actions": len(actions),
        "dated": len(dated),
        "titled": sum(1 for a in actions if a["title"]),
        "linked": sum(1 for a in actions if a["source_url"].startswith("http")),
        "storm_matched": sum(1 for a in dated if a["declaration_id"] in matched_ids),
    }


def trailing_bad(history: list[dict]) -> int:
    count = 0
    for entry in reversed(history):
        if entry.get("source") not in BAD_SOURCES:
            break
        count += 1
    return count


def grade_state(state: dict, summary: dict | None, numbers: dict, history: list[dict],
                previous: dict | None, run_day, since: str) -> dict:
    """Grade one state. history includes this run's entry as its last item."""
    red, yellow, notes = [], [], []
    name = state["name"]
    if summary is None:
        return {"grade": RED, "reasons": ["No page has been built for this state."], "notes": [],
                "source": "unknown", "source_error": "", "bad_source_streak": 0,
                "declarations": 0, "federal": 0, **numbers}

    source = infer_source(summary)
    count = (summary.get("metrics") or {}).get("action_count") or 0
    federal = (summary.get("metrics") or {}).get("federal_declaration_count") or 0
    streak = trailing_bad(history)
    error = short_error(summary.get("retry_error") or summary.get("collection_error") or "")

    if source in BAD_SOURCES:
        what = "failed" if source == "failed" else "returned nothing"
        retry = " and on the retry" if summary.get("retried") else ""
        runs = f", {streak} runs in a row" if streak > 1 else ""
        detail = f" ({error})" if error else ""
        shown = " The page is showing records saved from earlier runs." if count else ""
        red.append(f"The state site {what} on this run{retry}{detail}{runs}.{shown}")
    else:
        earlier = sum(1 for entry in history[-FLAKY_WINDOW:-1] if entry.get("source") in BAD_SOURCES)
        if earlier:
            runs = min(FLAKY_WINDOW, len(history)) - 1
            if runs == 1:
                yellow.append("The source failed or returned nothing on the run before this one.")
            else:
                yellow.append(f"The source failed or returned nothing on {earlier} of the "
                              f"{runs} runs before this one.")
        if summary.get("retried") and summary.get("first_attempt"):
            notes.append("Failed on the first try this run and recovered on the retry.")
        kept = summary.get("kept_saved_records") or 0
        if source == "partial" and kept:
            if count and kept > count * 0.1:
                yellow.append(f"The source left out {kept} of {count} saved records; they are "
                              "shown from earlier runs.")
            else:
                notes.append(f"The source left out {kept} saved record(s); shown from earlier runs.")

    built = summary.get("generated_on")
    if built and run_day:
        try:
            built_day = datetime.strptime(built, "%Y-%m-%d").date()
            if built_day < run_day - timedelta(days=1):
                red.append(f"The page was not rebuilt on this run (last built {built}).")
        except ValueError:
            pass

    if count == 0:
        red.append("No declarations on the page"
                   + (f" ({since.lower()})." if since.startswith("Since") else "."))
    else:
        if numbers["dated"] < count * 0.5:
            verb = "has" if numbers["dated"] == 1 else "have"
            red.append(f"Only {numbers['dated']} of {count} declarations {verb} a signing date, "
                       "so the rest cannot be matched to storms.")
        elif numbers["dated"] < count * 0.9:
            yellow.append(f"{missing(count - numbers['dated'], count)} no signing date.")
        if numbers["titled"] < count * 0.9:
            yellow.append(f"{missing(count - numbers['titled'], count)} no title.")
        if numbers["linked"] < count * 0.9:
            yellow.append(f"{missing(count - numbers['linked'], count)} no working document link.")
        if count < THIN_BELOW:
            window = f" ({since.lower()})" if since and since != "No data loaded" else ""
            yellow.append(f"Only {plural(count, 'declaration')} against {federal} federal ones"
                          f"{window}, so the source is likely missing most of the record.")
        if numbers["dated"] >= THIN_BELOW and numbers["storm_matched"] < numbers["dated"] * 0.25:
            yellow.append(f"Only {numbers['storm_matched']} of {numbers['dated']} dated "
                          "declarations matched any storm record.")

    before = (previous or {}).get("declarations")
    if before and count < before:
        message = f"Declarations fell from {before} to {count} since the last run."
        (red if count < before * 0.8 else yellow).append(message)

    grade = RED if red else YELLOW if yellow else GREEN
    return {"grade": grade, "reasons": red + yellow, "notes": notes, "source": source,
            "source_error": error, "bad_source_streak": streak, "declarations": count,
            "federal": federal, **numbers}


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def missing(lacking: int, count: int) -> str:
    return f"{lacking} of {count} declarations {'has' if lacking == 1 else 'have'}"


def cell(text) -> str:
    """Safe inside a Markdown table cell."""
    return str(text).replace("|", "/").replace("\n", " ").strip()


def run_label(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def render_report(result: dict, states: list[dict]) -> str:
    rows = result["states"]
    counts = result["counts"]
    lines = [
        "# Plus health report",
        "",
        f"Checked {result['generated_at_label']} after the refresh. "
        f"**{counts['green']} green, {counts['yellow']} yellow, {counts['red']} red.**",
        "",
    ]
    order = [state["abbreviation"] for state in states]

    def section(grade, heading):
        members = [ab for ab in order if rows[ab]["grade"] == grade]
        if not members:
            return
        lines.extend([f"## {heading} ({len(members)})", "",
                      "| State | Declarations | Why |", "|---|---:|---|"])
        for ab in members:
            row = rows[ab]
            why = " ".join(row["reasons"]) or "-"
            lines.append(f"| {cell(row['name'])} ({ab}) | {row['declarations']} | {cell(why)} |")
        lines.append("")

    section(RED, "Red: needs attention")
    section(YELLOW, "Yellow: working with gaps")
    greens = [ab for ab in order if rows[ab]["grade"] == GREEN]
    if greens:
        lines.extend([f"## Green ({len(greens)})", "", ", ".join(greens), ""])

    lines.extend(render_timing(result, states))

    lines.extend([
        "## Every state", "",
        "| State | Grade | Source this run | Failed runs in a row | Declarations | Federal "
        "| Dated | Titled | Linked | Storm matched | Notes |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    for ab in order:
        row = rows[ab]
        lines.append(
            f"| {ab} | {row['grade']} | {SOURCE_WORDS.get(row.get('source'), row.get('source', '-'))} "
            f"| {row.get('bad_source_streak', 0)} | {row.get('declarations', 0)} "
            f"| {row.get('federal', 0)} | {row.get('dated', 0)} | {row.get('titled', 0)} "
            f"| {row.get('linked', 0)} | {row.get('storm_matched', 0)} "
            f"| {cell(' '.join(row.get('notes', [])))} |")
    lines.extend(["", "<details><summary>How grades are set</summary>", "", RULES, "", "</details>", ""])
    return "\n".join(lines)


def minutes(seconds: float) -> str:
    return f"{seconds / 60:.1f} min" if seconds >= 60 else f"{seconds:.0f} s"


def render_timing(result: dict, states: list[dict], top: int = 10) -> list[str]:
    """Which states took the longest this run: collecting from the state
    source, and matching storms. Empty when the run recorded no timing."""
    rows = []
    for state in states:
        row = result["states"][state["abbreviation"]]
        collect, join = row.get("collect_seconds"), row.get("storm_join_seconds")
        if collect is None and join is None:
            continue
        rows.append((state["abbreviation"], collect or 0.0, join or 0.0))
    if not rows:
        return []
    rows.sort(key=lambda item: item[1] + item[2], reverse=True)
    total_collect = sum(item[1] for item in rows)
    total_join = sum(item[2] for item in rows)
    lines = ["## Where the time went", "",
             f"Collecting from state sources took {minutes(total_collect)} in all, and matching "
             f"storms took {minutes(total_join)}. The {min(top, len(rows))} slowest states:", "",
             "| State | Collecting | Matching storms |", "|---|---:|---:|"]
    for ab, collect, join in rows[:top]:
        lines.append(f"| {ab} | {minutes(collect)} | {minutes(join)} |")
    lines.append("")
    return lines


def render_changes(result: dict, previous: dict | None, states: list[dict]) -> str:
    if not previous or not previous.get("states"):
        counts = result["counts"]
        return (f"First health report: {counts['green']} green, {counts['yellow']} yellow, "
                f"{counts['red']} red.")
    lines = []
    for state in states:
        ab = state["abbreviation"]
        now = result["states"][ab]
        before = previous["states"].get(ab, {}).get("grade")
        if before and before != now["grade"]:
            reason = f" {now['reasons'][0]}" if now["reasons"] else ""
            lines.append(f"- **{now['name']}** went from {before} to {now['grade']}.{reason}")
    if not lines:
        return ""
    counts = result["counts"]
    return ("Changes since the last run "
            f"({previous.get('generated_at_label', 'previous run')}):\n\n" + "\n".join(lines)
            + f"\n\nNow {counts['green']} green, {counts['yellow']} yellow, {counts['red']} red.")


def seed_history(repo_root: Path, states: list[dict], runs: int) -> dict[str, list[dict]]:
    """History from past refresh commits, oldest first. The newest refresh is
    left out because the files on disk already are that run."""
    log = subprocess.run(
        ["git", "log", "--format=%H %cI", "--grep=Auto-refresh Plus state data", "-n", str(runs + 1)],
        cwd=repo_root, capture_output=True, text=True, check=True).stdout.split("\n")
    commits = [line.split(" ", 1) for line in log if line.strip()][1:]
    history: dict[str, list[dict]] = {state["abbreviation"]: [] for state in states}
    for sha, when in reversed(commits):
        moment = datetime.fromisoformat(when).astimezone(timezone.utc)
        for state in states:
            shown = subprocess.run(
                ["git", "show", f"{sha}:plus/{state['slug']}/state-summary.json"],
                cwd=repo_root, capture_output=True)
            if shown.returncode:
                continue
            try:
                summary = json.loads(shown.stdout)
            except json.JSONDecodeError:
                continue
            history[state["abbreviation"]].append({
                "at": run_label(moment), "source": infer_source(summary),
                "declarations": (summary.get("metrics") or {}).get("action_count") or 0,
            })
    return history


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade every Plus state after a refresh")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--issue-body-out", type=Path)
    parser.add_argument("--changes-out", type=Path)
    parser.add_argument("--seed-from-git", type=int, default=0,
                        help="rebuild the history from this many earlier refresh commits")
    parser.add_argument("--now", help="run time as ISO 8601, for tests")
    parser.add_argument("--out-dir", type=Path, help="where health.json and HEALTH.md go "
                        "(default plus/_health)")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    bp = load_builder(repo_root)
    states = load_states(repo_root)
    now = (datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc))
    now = now.astimezone(timezone.utc)

    out_dir = args.out_dir or repo_root / "plus" / "_health"
    out_dir.mkdir(parents=True, exist_ok=True)
    health_path = out_dir / "health.json"
    previous = None
    if health_path.exists():
        try:
            previous = json.loads(health_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = None
    past = {ab: list(entry.get("history", [])) for ab, entry in (previous or {}).get("states", {}).items()}
    if args.seed_from_git:
        past = seed_history(repo_root, states, args.seed_from_git)
        previous = None

    summaries = {}
    for state in states:
        path = repo_root / "plus" / state["slug"] / "state-summary.json"
        try:
            summaries[state["abbreviation"]] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summaries[state["abbreviation"]] = None
    built_days = [datetime.strptime(s["generated_on"], "%Y-%m-%d").date()
                  for s in summaries.values() if s and s.get("generated_on")]
    run_day = max(built_days) if built_days else None

    result = {"generated_at": now.isoformat(timespec="minutes"),
              "generated_at_label": run_label(now), "states": {}}
    for state in states:
        ab = state["abbreviation"]
        summary = summaries[ab]
        state_dir = repo_root / "plus" / state["slug"]
        try:
            numbers = measure(bp, state, state_dir)
        except Exception as exc:  # a broken file must not stop the report
            numbers = {"actions": 0, "dated": 0, "titled": 0, "linked": 0, "storm_matched": 0}
            print(f"WARNING {ab}: could not read its files ({exc})", file=sys.stderr)
        count = ((summary or {}).get("metrics") or {}).get("action_count") or 0
        since = bp.extract_coverage_start_label(ab, (summary or {}).get("coverage", ""), count)
        entry = {"at": run_label(now), "source": infer_source(summary) if summary else "unknown",
                 "declarations": count}
        history = (past.get(ab, []) + [entry])[-HISTORY_LENGTH:]
        prior = (previous or {}).get("states", {}).get(ab)
        if prior is None and len(history) > 1:
            prior = {"declarations": history[-2].get("declarations")}
        graded = grade_state(state, summary, numbers, history, prior, run_day, since)
        timing = (summary or {}).get("timing") or {}
        graded.update(name=state["name"], since=since, history=history,
                      collect_seconds=timing.get("collect_seconds"),
                      storm_join_seconds=timing.get("storm_join_seconds"))
        result["states"][ab] = graded

    grades = [row["grade"] for row in result["states"].values()]
    result["counts"] = {g: grades.count(g) for g in (GREEN, YELLOW, RED)}
    report = render_report(result, states)
    changes = render_changes(result, previous, states)

    health_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "HEALTH.md").write_text(report, encoding="utf-8")
    if args.issue_body_out:
        args.issue_body_out.write_text(report, encoding="utf-8")
    if args.changes_out:
        args.changes_out.write_text(changes, encoding="utf-8")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")

    counts = result["counts"]
    print(f"Plus health: {counts['green']} green, {counts['yellow']} yellow, {counts['red']} red.")
    for ab, row in result["states"].items():
        if row["grade"] == RED:
            print(f"  RED {ab}: {' '.join(row['reasons'])}")
    if changes:
        print(changes)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # the report is advisory; never fail the refresh
        print(f"WARNING: health check could not finish: {exc}", file=sys.stderr)
        raise SystemExit(0)
