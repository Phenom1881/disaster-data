"""Health check for every DisasterData Plus state, run after each refresh.

Grades all 50 states green, yellow or red, says why in plain words, and keeps
a short history so a source that fails every few weeks is caught. Before
this, problems surfaced one state at a time, whenever someone looked: a
state whose site refused every request still showed its saved records, and
a state collecting the wrong list simply showed 0.

Writes:
  plus/_health/health.json   current grades, the last runs per state, and when
                             collecting from each state last worked
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
import hashlib
import importlib.util
import re
import json
import os
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

GREEN, YELLOW, RED = "green", "yellow", "red"
HISTORY_LENGTH = 12
FLAKY_WINDOW = 4          # runs looked at for a source that fails now and then
THIN_BELOW = 10           # fewer declarations than this reads as a short coverage window
BAD_SOURCES = ("empty", "failed")
GOOD_SOURCES = ("ok", "partial")
DROUGHT_RE = re.compile(r"\bdrought\b", re.I)
# A state site that refuses now and then (New Hampshire's registry, Ohio's
# feed) is not an emergency while its page still shows the records saved from
# the last good collection. It turns red once that collection is this old.
STALE_AFTER_DAYS = 28
LABEL_FORMAT = "%Y-%m-%d %H:%M UTC"
# Every state runs its own copy of the storm classifier, and the copies must
# be identical, or one state's storm matches are not made the same way as the
# others'. plus/eo_storm_join.py is the shared copy they are compared with.
# It fell three versions behind the state copies (2026-09-26 to 2026-10-15)
# without anything noticing, and on 2026-09-11 eight state copies had been
# stale or missing. A state whose copy differs is flagged.
CLASSIFIER = "eo_storm_join.py"
SOURCE_WORDS = {
    "ok": "returned everything",
    "partial": "returned part",
    "empty": "no declarations",
    "failed": "failed",
    "not_collected": "not collected",
    "manual": "maintained by hand",
    "unknown": "not recorded",
}
RULES = """How grades are set

Red, needs attention now:
- collecting from the state source failed or produced no declarations, on this run and on the retry, and the last successful collection was 4 weeks ago or more (or no records are saved to show)
- no declarations on the page
- fewer than half the declarations have a signing date, so the rest cannot be matched to storms
- declarations fell by more than a fifth since the last run
- the page was not rebuilt on this run

Yellow, working with gaps:
- collecting failed or produced no declarations on this run and on the retry, but the page shows records saved from a successful collection less than 4 weeks ago
- collection failed or produced no declarations on another of the last 4 runs
- the source left out more than a tenth of the saved records, which are shown from earlier runs
- fewer than 10 declarations, which usually means the source only covers recent years
- more than a tenth of the declarations have no signing date, title or working link
- its storm classifier (eo_storm_join.py) differs from the shared copy in plus/
- fewer than a quarter of the dated declarations matched any storm record
- declarations fell since the last run

A fall is not counted against a state when records a reviewer excluded as not
weather events (hazard_overrides.csv) explain it; the report notes it instead.

Green: none of the above.

A state marked as maintained by hand (its automatic source does not work, so
its records are added by hand from official announcements and news coverage)
is not graded on collection; the other checks still apply."""


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
    if every record on the page had to be kept from earlier runs, collection
    produced no declarations."""
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


def file_hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def measure(bp, state: dict, state_dir: Path) -> dict:
    """What the state's page actually shows: the same loaders the page uses."""
    actions, _ = bp.load_state_actions(state, state_dir)
    storm_rows, _ = bp.load_storm_match_rows(state_dir)
    matched_ids = {bp.clean(row.get("declaration_id")) for row in storm_rows}
    dated = [a for a in actions if a["date_signed"]]
    # Drought orders are left out of the storm match rate. NOAA's storm
    # database logs drought only in some months (Idaho's 207 county drought
    # orders found drought entries in June 2001 and few other months), so a
    # low rate there says nothing about whether the join works.
    weather = [a for a in dated if not DROUGHT_RE.search(a["title"] or "")]
    # Records a reviewer marked "exclude" in hazard_overrides.csv are left off
    # the page on purpose. Counted so a fall they explain is not flagged.
    reviewed_out = bp.excluded_declaration_ids(state_dir)
    if reviewed_out:
        every, _ = bp.all_state_actions(state, state_dir)
        reviewed_out &= {row["declaration_id"] for row in every}
    return {
        "actions": len(actions),
        "dated": len(dated),
        "titled": sum(1 for a in actions if a["title"]),
        "linked": sum(1 for a in actions if a["source_url"].startswith("http")),
        "storm_matched": sum(1 for a in dated if a["declaration_id"] in matched_ids),
        "dated_not_drought": len(weather),
        "matched_not_drought": sum(1 for a in weather if a["declaration_id"] in matched_ids),
        "excluded": len(reviewed_out),
    }


def trailing_bad(history: list[dict]) -> int:
    count = 0
    for entry in reversed(history):
        if entry.get("source") not in BAD_SOURCES:
            break
        count += 1
    return count


def parse_label(label) -> datetime | None:
    try:
        return datetime.strptime(str(label), LABEL_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def last_good_collection(prior: dict | None, history: list[dict]) -> str | None:
    """When collecting from the state last worked, as a run label. Kept in
    health.json from run to run, so it outlasts the 12-run history. history
    includes this run's entry as its last item."""
    for entry in reversed(history):
        if entry.get("source") in GOOD_SOURCES and parse_label(entry.get("at")):
            return entry["at"]
    return (prior or {}).get("last_good_collection")


def stale_source(count: int, last_good: str | None, history: list[dict], streak: int,
                 now: datetime | None) -> tuple[bool, str]:
    """For a source that failed on this run: whether that is red yet, and the
    sentence saying how old the records on the page are."""
    if not count:
        return True, ""
    good = parse_label(last_good)
    if good and now:
        days = (now - good).days
        age = f"{days} day{'' if days == 1 else 's'} ago"
        if days >= STALE_AFTER_DAYS:
            return True, (f" The page is showing records saved from earlier runs; the last successful "
                          f"collection was {good:%Y-%m-%d} ({age}), four weeks or more.")
        return False, (f" The page is showing records saved from earlier runs; the last successful "
                       f"collection was {good:%Y-%m-%d} ({age}). This turns red at four weeks.")
    first_bad = parse_label(history[-streak].get("at")) if streak else None
    if first_bad and now:
        days = (now - first_bad).days
        if days >= STALE_AFTER_DAYS:
            return True, (f" The page is showing records saved from earlier runs. No successful "
                          f"collection is on record, and collection has failed since at least "
                          f"{first_bad:%Y-%m-%d} ({days} days), four weeks or more.")
        return False, (f" The page is showing records saved from earlier runs. No successful collection "
                       f"is on record, and collection has failed since at least {first_bad:%Y-%m-%d}. "
                       "This turns red at four weeks.")
    return False, " The page is showing records saved from earlier runs."


def grade_state(state: dict, summary: dict | None, numbers: dict, history: list[dict],
                previous: dict | None, run_day, since: str, last_good: str | None = None,
                now: datetime | None = None) -> dict:
    """Grade one state. history includes this run's entry as its last item.
    last_good is when collecting from this state last worked (a run label)."""
    red, yellow, notes = [], [], []
    name = state["name"]
    if summary is None:
        return {"grade": RED, "reasons": ["No page has been built for this state."], "notes": [],
                "source": "unknown", "source_error": "", "bad_source_streak": 0,
                "declarations": 0, "federal": 0, "last_good_collection": last_good, **numbers}

    source = infer_source(summary)
    count = (summary.get("metrics") or {}).get("action_count") or 0
    federal = (summary.get("metrics") or {}).get("federal_declaration_count") or 0
    streak = trailing_bad(history)
    error = short_error(summary.get("retry_error") or summary.get("collection_error") or "")
    if now is None and run_day:
        now = datetime.combine(run_day, time(), tzinfo=timezone.utc)

    if source == "manual":
        detail = f" This run's automatic source attempt: {error}." if error else ""
        notes.append("Maintained by hand: no automatic source works for this state, so declarations "
                     "are added from official announcements and news coverage." + detail)
    elif source in BAD_SOURCES:
        # Said about collection, not the site: "no declarations" can mean the
        # site refused (Ohio's feed answered 406) or that it answered but none
        # of its declarations could be read (New Hampshire on 2026-09-27 listed
        # all 340 orders, but its six weather orders had no readable signing
        # date, so none reached the join file).
        what = "failed" if source == "failed" else "produced no declarations"
        retry = " and on the retry" if summary.get("retried") else ""
        runs = f", {streak} runs in a row" if streak > 1 else ""
        detail = f" ({error})" if error else ""
        is_red, shown = stale_source(count, last_good, history, streak, now)
        (red if is_red else yellow).append(
            f"Collecting from the state source {what} on this run{retry}{detail}{runs}.{shown}")
    else:
        earlier = sum(1 for entry in history[-FLAKY_WINDOW:-1] if entry.get("source") in BAD_SOURCES)
        if earlier:
            runs = min(FLAKY_WINDOW, len(history)) - 1
            if runs == 1:
                yellow.append("Collection failed or produced no declarations on the run before this one.")
            else:
                yellow.append(f"Collection failed or produced no declarations on {earlier} of the "
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
        rated = numbers.get("dated_not_drought", numbers["dated"])
        matched = numbers.get("matched_not_drought", numbers["storm_matched"])
        if rated >= THIN_BELOW and matched < rated * 0.25:
            drought = numbers["dated"] - rated
            yellow.append(f"Only {matched} of {rated} dated "
                          + ("non-drought " if drought else "")
                          + "declarations matched any storm record.")
        elif numbers["dated"] - rated:
            notes.append(f"{numbers['dated'] - rated} drought declaration(s) are not counted in the storm "
                         "match rate; NOAA's storm database logs drought only in some months.")

    if numbers.get("classifier_same") is False:
        yellow.append(f"Its storm classifier ({CLASSIFIER}) differs from the shared copy in plus/, so its "
                      "storm matches are not made the same way as other states'.")

    before = (previous or {}).get("declarations")
    if before and count < before:
        # Records newly excluded on review explain part or all of a fall. A
        # run with no excluded count saved from before (the first run that
        # records one) is read as no change, so nothing is excused unseen.
        excluded_now = numbers.get("excluded")
        excluded_before = (previous or {}).get("excluded")
        if excluded_now is None:
            reviewed = 0
        else:
            if excluded_before is None:
                excluded_before = excluded_now
            reviewed = min(max(0, excluded_now - excluded_before), before - count)
        unexplained = before - count - reviewed
        if unexplained:
            message = f"Declarations fell from {before} to {count} since the last run."
            if reviewed:
                message += (f" {plural(reviewed, 'record')} of that {'was' if reviewed == 1 else 'were'} "
                            f"excluded on review; {unexplained} {'is' if unexplained == 1 else 'are'} "
                            "not explained.")
            (red if count + reviewed < before * 0.8 else yellow).append(message)
        else:
            notes.append(f"Declarations fell from {before} to {count} because "
                         f"{plural(reviewed, 'record')} reviewed as not weather events "
                         f"{'was' if reviewed == 1 else 'were'} excluded.")

    grade = RED if red else YELLOW if yellow else GREEN
    return {"grade": grade, "reasons": red + yellow, "notes": notes, "source": source,
            "source_error": error, "bad_source_streak": streak, "declarations": count,
            "federal": federal, "last_good_collection": last_good, **numbers}


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
    lines.extend(render_federal_gaps(result, states))

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


def render_federal_gaps(result: dict, states: list[dict], top: int = 10) -> list[str]:
    """Where a state's list is most likely incomplete: FEMA's weather major
    disasters and emergencies, in the years the state's page covers, that
    have no state declaration on the page within the crosswalk's window
    (federal_without_state() in build-plus.py). Not part of any grade.
    Empty until a refresh has written the numbers."""
    rows = []
    for state in states:
        row = result["states"][state["abbreviation"]]
        compared = row.get("fema_compared")
        if compared:
            rows.append((state["abbreviation"], row.get("fema_since"),
                         row.get("fema_without_state") or 0, compared))
    if not rows:
        return []
    missing = sum(item[2] for item in rows)
    compared = sum(item[3] for item in rows)
    window = result.get("federal_window_days", 21)
    lines = ["## FEMA declarations with no state declaration", "",
             f"{missing:,} of the {compared:,} FEMA weather major disasters and emergencies in the "
             "years each state's page covers have no state declaration on that page within "
             f"{window} days. A state's list is most likely incomplete where this is high."]
    worst = sorted((item for item in rows if item[2]), key=lambda item: (item[2], item[2] / item[3]),
                   reverse=True)[:top]
    if worst:
        lines.extend(["", f"The {len(worst)} states with the most:", "",
                      "| State | Since | No state declaration | FEMA declarations |",
                      "|---|---:|---:|---:|"])
        lines.extend(f"| {ab} | {since} | {count} | {total} |" for ab, since, count, total in worst)
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

    shared_classifier = file_hash(repo_root / "plus" / CLASSIFIER)

    result = {"generated_at": now.isoformat(timespec="minutes"),
              "generated_at_label": run_label(now), "states": {},
              "federal_window_days": bp.FEDERAL_MATCH_WINDOW_DAYS}
    for state in states:
        ab = state["abbreviation"]
        summary = summaries[ab]
        state_dir = repo_root / "plus" / state["slug"]
        try:
            numbers = measure(bp, state, state_dir)
        except Exception as exc:  # a broken file must not stop the report
            numbers = {"actions": 0, "dated": 0, "titled": 0, "linked": 0, "storm_matched": 0}
            print(f"WARNING {ab}: could not read its files ({exc})", file=sys.stderr)
        own = file_hash(state_dir / CLASSIFIER)
        # None when either copy is missing: a state without its own copy
        # already fails its storm join, and no shared copy means nothing to
        # compare with.
        numbers["classifier_same"] = (own == shared_classifier) if own and shared_classifier else None
        count = ((summary or {}).get("metrics") or {}).get("action_count") or 0
        since = bp.extract_coverage_start_label(ab, (summary or {}).get("coverage", ""), count)
        entry = {"at": run_label(now), "source": infer_source(summary) if summary else "unknown",
                 "declarations": count}
        history = (past.get(ab, []) + [entry])[-HISTORY_LENGTH:]
        prior = (previous or {}).get("states", {}).get(ab)
        last_good = last_good_collection(prior, history)
        if prior is None and len(history) > 1:
            prior = {"declarations": history[-2].get("declarations")}
        graded = grade_state(state, summary, numbers, history, prior, run_day, since,
                             last_good=last_good, now=now)
        timing = (summary or {}).get("timing") or {}
        gaps = (summary or {}).get("federal_without_state") or {}
        graded.update(name=state["name"], since=since, history=history,
                      collect_seconds=timing.get("collect_seconds"),
                      storm_join_seconds=timing.get("storm_join_seconds"),
                      fema_since=gaps.get("since"), fema_compared=gaps.get("compared"),
                      fema_without_state=gaps.get("count"))
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
