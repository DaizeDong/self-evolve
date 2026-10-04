"""Inventory private runtime storage without reading or deleting its payloads."""
from pathlib import Path, PurePosixPath
import os
import stat

from . import runtime_data


MANIFEST_FILE = "storage-manifest.json"
CATEGORIES = ("CORE", "EVIDENCE", "DERIVED", "SCRATCH", "UNKNOWN")
_MAX_ISSUES = 64
_CACHE_NAMES = frozenset({
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".nox", ".venv", "node_modules",
})
_CORE_FILES = frozenset({
    "events.jsonl", "target.json", "pending_actions.jsonl",
    "archive/lineage.json", "_holdout/holdout.json",
})
_EVIDENCE_FILES = frozenset({
    "reflections.jsonl", "reflector-outcomes.jsonl", "proposals.jsonl",
    "outbound_seq.jsonl", "archive/retired.jsonl",
})


def classify(relative, area="run", *, is_directory=False):
    """Classify a relative metadata path; classification never permits deletion."""
    path = PurePosixPath(relative)
    directory_parts = path.parts if is_directory else path.parts[:-1]
    if area != "run" or any(part in _CACHE_NAMES for part in directory_parts):
        return "SCRATCH"
    name = path.as_posix()
    if name in _CORE_FILES:
        return "CORE"
    if path.parts and path.parts[0] in {"base-snapshot", "_frozen"}:
        return "CORE"
    if (len(path.parts) >= 4 and path.parts[:2] == ("archive", "versions")
            and path.parts[3] == "snapshot"):
        return "CORE"
    if name in _EVIDENCE_FILES:
        return "EVIDENCE"
    if name in {"state.json", MANIFEST_FILE} or path.parts[:2] == ("archive", "current"):
        return "DERIVED"
    return "UNKNOWN"


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024))


def inventory(target, run_id, write=False):
    """Count one private run and its candidate trees using names and sizes only.

    No profile, event, prompt, source or result payload is opened or hashed.
    A manifest is a bounded metadata report, not proof of inactivity or recovery.
    Shared grader, agent, EDGAR and calibration scratch is outside this run scope.
    """
    run = runtime_data.run_directory(target, run_id)
    roots = {
        "run": run,
        "candidate": runtime_data.worktree_directory(target, run_id),
        "self_candidate": runtime_data.worktree_directory(target, "self__" + run_id),
    }
    report = {
        "schema_version": 1,
        "status": "uninitialized",
        "run_id": run_id,
        "scope": "run_and_candidate_worktrees",
        "activity": "unverified",
        "cleanup_allowed": False,
        "recovery_verified": False,
        "areas": {},
        "categories": {name: {"files": 0, "bytes": 0} for name in CATEGORIES},
        "unknown_count": 0,
        "issues": [],
        "issues_omitted": 0,
    }

    def issue(area, relative, kind):
        report["unknown_count"] += 1
        if len(report["issues"]) < _MAX_ISSUES:
            report["issues"].append({"area": area, "path": relative[:512], "kind": kind})
        else:
            report["issues_omitted"] += 1

    def visit(directory, root, area, totals):
        with os.scandir(directory) as scan:
            entries = sorted(scan, key=lambda entry: entry.name)
        relative_directory = Path(directory).relative_to(root).as_posix()
        known_parents = {".", "archive", "archive/versions", "_holdout"}
        if (not entries and area == "run" and relative_directory not in known_parents
                and classify(relative_directory, area, is_directory=True) == "UNKNOWN"
                and not (relative_directory.startswith("archive/versions/")
                         and len(PurePosixPath(relative_directory).parts) == 3)):
            issue(area, relative_directory, "unclassified_directory")
        for entry in entries:
            relative = (Path(entry.path).relative_to(root)).as_posix()
            # Git metadata is not runtime DATA; the generated manifest excludes itself.
            if entry.name == ".git" or (area == "run" and relative == MANIFEST_FILE):
                continue
            info = entry.stat(follow_symlinks=False)
            if _linked(info):
                totals["links"] += 1
                issue(area, relative, "link_not_followed")
                continue
            category = classify(relative, area, is_directory=stat.S_ISDIR(info.st_mode))
            if stat.S_ISDIR(info.st_mode):
                visit(entry.path, root, area, totals)
            elif stat.S_ISREG(info.st_mode):
                totals["files"] += 1
                totals["bytes"] += info.st_size
                report["categories"][category]["files"] += 1
                report["categories"][category]["bytes"] += info.st_size
                if category == "UNKNOWN":
                    issue(area, relative, "unclassified_file")
            else:
                issue(area, relative, "unsupported_entry")

    for area, root in roots.items():
        totals = {"exists": False, "files": 0, "bytes": 0, "links": 0}
        report["areas"][area] = totals
        try:
            info = root.lstat()
        except FileNotFoundError:
            continue
        totals["exists"] = True
        if _linked(info):
            totals["links"] += 1
            issue(area, ".", "link_not_followed")
        elif not stat.S_ISDIR(info.st_mode):
            issue(area, ".", "not_a_directory")
        else:
            visit(root, root, area, totals)

    if report["areas"]["run"]["exists"]:
        report["status"] = "review_required" if report["unknown_count"] else "inventoried"
    if write:
        if not report["areas"]["run"]["exists"]:
            raise FileNotFoundError("Cannot write a storage manifest for a missing run")
        runtime_data.write_json(run / MANIFEST_FILE, report)
    return report
