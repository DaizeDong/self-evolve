
"""Generated author controls for accepted-state grading and lifecycle edge cases."""
import ast
import builtins
import contextlib
import copy
from dataclasses import asdict, dataclass, fields, replace
import hashlib
import io
import json
import math
import posixpath
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = (
    "tools/make_fixtures.py", "tools/sie/calibrate.py", "tools/sie/archive.py",
    "tools/sie/business_tree.py", "tools/sie/runtime_data.py", "tools/sie/events.py",
    "tools/sie/state.py", "tools/sie/cli.py", "tools/sie/probes/exec_probe.py",
)
SOURCES = {name: (ROOT / name).read_bytes() for name in SOURCE_PATHS}


def definitions(relative, namespace, names=None, constants=()):
    tree = ast.parse(SOURCES[relative], relative)
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and (names is None or node.name in names):
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in constants for target in node.targets):
            nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), relative, "exec"), namespace)
    return namespace


def fixture():
    scope = definitions("tools/make_fixtures.py", {}, {"review11_behavior_samples"})
    return scope["review11_behavior_samples"]()


class MemoryFiles:
    """Only synthetic bytes are exposed to production path and stream collaborators."""
    def __init__(self):
        self.files = {}
        self.directories = {"/"}
        self.fsyncs = 0

    def path(self, value):
        return MemoryPath(self, str(value))

    def mkdir(self, value, **kwargs):
        path = PurePosixPath(str(value))
        self.directories.update(str(parent) for parent in (path, *path.parents))

    def put(self, value, content):
        name = str(value)
        self.mkdir(posixpath.dirname(name))
        self.files[name] = content.encode("utf-8") if isinstance(content, str) else content

    def open(self, value, mode="r", encoding="utf-8", errors="strict", **kwargs):
        name = str(value)
        if name not in self.files and not any(flag in mode for flag in ("w", "a")):
            raise FileNotFoundError(name)
        content = b"" if "w" in mode else self.files.get(name, b"")
        writable = any(flag in mode for flag in ("w", "a", "+"))
        owner = self
        if "b" in mode:
            class Stream(io.BytesIO):
                def fileno(self):
                    return 0
                def close(self):
                    if not self.closed and writable:
                        owner.put(name, self.getvalue())
                    super().close()
            stream = Stream(content)
        else:
            class Stream(io.StringIO):
                def fileno(self):
                    return 0
                def close(self):
                    if not self.closed and writable:
                        owner.put(name, self.getvalue().encode(encoding))
                    super().close()
            stream = Stream(content.decode(encoding, errors))
        if "a" in mode:
            stream.seek(0, 2)
        return stream

    def sync(self, _):
        self.fsyncs += 1

    def os(self):
        path = SimpleNamespace(**{name: getattr(posixpath, name) for name in dir(posixpath)
                                  if not name.startswith("__")})
        path.isdir = lambda value: str(value) in self.directories
        path.isfile = lambda value: str(value) in self.files
        path.exists = lambda value: path.isdir(value) or path.isfile(value)
        return SimpleNamespace(path=path, makedirs=self.mkdir, fsync=self.sync,
                               replace=lambda src, dst: self.put(dst, self.files.pop(str(src))))


class MemoryPath:
    def __init__(self, owner, value):
        self.owner = owner
        self.value = str(PurePosixPath(value))

    def __str__(self):
        return self.value

    def __fspath__(self):
        return self.value

    def __eq__(self, other):
        return isinstance(other, MemoryPath) and self.owner is other.owner and self.value == other.value

    def expanduser(self):
        return self

    def __truediv__(self, suffix):
        return self.owner.path(PurePosixPath(self.value) / str(suffix))

    @property
    def name(self):
        return PurePosixPath(self.value).name

    @property
    def parent(self):
        return self.owner.path(PurePosixPath(self.value).parent)

    @property
    def parents(self):
        return tuple(self.owner.path(parent) for parent in PurePosixPath(self.value).parents)

    @property
    def parts(self):
        return PurePosixPath(self.value).parts

    def relative_to(self, root):
        return self.owner.path(PurePosixPath(self.value).relative_to(str(root)))

    def as_posix(self):
        return self.value

    def is_relative_to(self, root):
        return PurePosixPath(self.value).is_relative_to(str(root))

    def resolve(self, strict=False):
        if strict and not self.exists():
            raise FileNotFoundError(self.value)
        return self

    def exists(self):
        return self.is_dir() or self.is_file()

    def is_dir(self):
        return self.value in self.owner.directories

    def is_file(self):
        return self.value in self.owner.files

    def lstat(self):
        if not self.exists():
            raise FileNotFoundError(self.value)
        mode = stat.S_IFDIR if self.is_dir() else stat.S_IFREG
        return SimpleNamespace(st_mode=mode, st_nlink=1, st_file_attributes=0)

    def iterdir(self):
        names = self.owner.directories | set(self.owner.files)
        return iter(self.owner.path(name) for name in sorted(names)
                    if name != self.value and posixpath.dirname(name) == self.value)

    def read_bytes(self):
        return self.owner.files[self.value]

    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)

    def mkdir(self, **kwargs):
        self.owner.mkdir(self.value, **kwargs)

    def open(self, *args, **kwargs):
        return self.owner.open(self.value, *args, **kwargs)


def environment(case):
    fs = MemoryFiles()
    runtime = SimpleNamespace(
        worktree_directory=lambda *args: fs.path(case["sandbox"]),
        run_directory=lambda *args: fs.path(case["run"]),
        private_file_path=fs.path,
    )
    rd = definitions("tools/sie/runtime_data.py", {"re": re, "os": fs.os(), "json": json,
                     "Path": fs.path, "stat": stat, "_safe_path": fs.path,
                     "private_file_path": fs.path},
                     {"DataBoundaryError", "validate_run_id", "_file_in_parent", "write_json"})
    runtime.DataBoundaryError = rd["DataBoundaryError"]
    runtime.validate_run_id = rd["validate_run_id"]
    archive = definitions("tools/sie/archive.py",
                          {"json": json, "math": math, "os": fs.os(), "open": fs.open},
                          {"_score_record", "_version_record", "_load_versions", "lineage"}, ("LINEAGE",))
    business = definitions("tools/sie/business_tree.py",
                           {"Path": fs.path, "hashlib": hashlib, "stat": stat, "os": fs.os()},
                           {"_linked", "_entry", "_excluded", "_cache_only_directory",
                            "manifest", "_manifest_matches", "matches"},
                           ("EXCLUDED", "CACHE_DIRECTORIES"))
    modules = {"tools.sie.runtime_data": runtime,
               "tools.sie": SimpleNamespace(archive=SimpleNamespace(**archive),
                                            business_tree=SimpleNamespace(**business))}
    def importing(name, *args, **kwargs):
        if name not in modules:
            raise AssertionError("Unexpected production import: " + name)
        return modules[name]
    globals_base = {"__builtins__": dict(vars(builtins), __import__=importing),
                    "json": json, "os": fs.os(), "open": fs.open, "Path": fs.path}
    calibrate = definitions("tools/sie/calibrate.py", dict(globals_base),
                            {"CalibrationError", "scoring_root", "read_events", "check_sandbox_baseline"})
    state = definitions("tools/sie/state.py", {"json": json, "os": fs.os(), "open": fs.open,
                        "dataclass": dataclass, "fields": fields, "asdict": asdict, "__name__": __name__},
                        {"RunState", "load_state"}, ("STATE_FILE",))
    events = definitions("tools/sie/events.py",
                         {"json": json, "os": fs.os(), "open": fs.open, "RunState": state["RunState"],
                          "replace": replace, "write_json": rd["write_json"]},
                         {"append_event", "_apply", "replay"}, ("EVENTS_FILE", "_DIRECT"))
    return fs, runtime, globals_base, calibrate, state, events


def scoring_case(name):
    case = fixture()
    fs, runtime, base, cal, state, events = environment(case)
    fs.mkdir(case["sandbox"])
    fs.put(case["sandbox"] + "/.git", "synthetic worktree metadata")
    archive = case["run"] + "/archive"
    snapshot = archive + "/versions/v1/snapshot"
    for rel, value in case["files"].items():
        fs.put(snapshot + "/" + rel, value)
        fs.put(case["sandbox"] + "/" + rel, value)
    versions = copy.deepcopy(case["versions"][:1])
    if name in ("latest-match", "stale-match"):
        versions = copy.deepcopy(case["versions"])
        for rel, value in case["files"].items():
            fs.put(archive + "/versions/v2/snapshot/" + rel,
                   case["new_content"] if rel == "module.py" else value)
        if name == "latest-match":
            fs.put(case["sandbox"] + "/module.py", case["new_content"])
    if name == "pending-edit":
        fs.put(case["sandbox"] + "/module.py", case["new_content"])
    elif name == "added-file":
        fs.put(case["sandbox"] + "/" + case["extra_file"], case["extra_text"])
    elif name == "deleted-file":
        del fs.files[case["sandbox"] + "/notes.md"]
    elif name == "added-directory":
        fs.mkdir(case["sandbox"] + "/" + case["extra_directory"])
    elif name == "missing-snapshot":
        fs.directories.remove(snapshot)
    elif name == "bad-version":
        versions[0]["vid"] = case["bad_version"]
    elif name == "duplicate-version":
        versions.append(copy.deepcopy(versions[0]))
    elif name == "non-list-lineage":
        versions = {"unexpected": True}
    if name != "no-lineage":
        fs.put(archive + "/lineage.json",
               case["malformed_lineage"] if name == "malformed-lineage" else json.dumps(versions))
    return case, fs, cal


def check_scoring(name, allowed):
    case, fs, cal = scoring_case(name)
    try:
        result = cal["scoring_root"](case["target"], case["run_id"])
    except cal["CalibrationError"]:
        assert not allowed, "accepted matching business tree was refused"
        return {"refused": True}
    assert allowed, "unaccepted or unverified tree was selected for grading"
    assert result == case["sandbox"], "Git baseline must use the validated worktree"
    assert fs.path(result + "/.git").is_file(), "Git baseline metadata was lost"
    git_calls = []
    def git(argv, **kwargs):
        git_calls.append(kwargs["cwd"])
        return SimpleNamespace(returncode=0, stdout=case["files"]["module.py"])
    cal["subprocess"] = SimpleNamespace(run=git)
    defects = [{"file_rel": "module.py", "replace": case["files"]["module.py"]}]
    assert cal["check_sandbox_baseline"](result, defects) == 1
    assert git_calls == [case["sandbox"]], "baseline checked a snapshot without Git metadata"
    return {"refused": False, "baseline_checked": True}


def test_scoring_preserves_required_empty_dirs_and_ignores_only_cache_ancestors():
    case, fs, cal = scoring_case('latest-match')
    snapshot = case['run'] + '/archive/versions/v2/snapshot'
    required = case['extra_directory']
    fs.mkdir(snapshot + '/' + required)
    with unittest.TestCase().assertRaises(cal['CalibrationError']):
        cal['scoring_root'](case['target'], case['run_id'])
    fs.put(case['sandbox'] + '/' + required + '/node_modules/cache.bin', case['extra_text'])
    fs.put(case['sandbox'] + '/extra-cache-parent/.pytest_cache/cache.bin', case['extra_text'])
    assert cal['scoring_root'](case['target'], case['run_id']) == case['sandbox']
    fs.put(case['sandbox'] + '/extra-cache-parent/business.py', case['extra_text'])
    with unittest.TestCase().assertRaises(cal['CalibrationError']):
        cal['scoring_root'](case['target'], case['run_id'])


def check_counter(fragment):
    case = fixture()
    fs, runtime, base, cal, state, events = environment(case)
    path = case["run"] + "/events.jsonl"
    lines = [json.dumps(case["round_event"]), fragment, json.dumps(case["accept_event"])]
    fs.put(path, "\n".join(lines))
    report = cal["read_events"](case["target"], case["run_id"])
    assert report["malformed_records"] == 1
    assert report["rounds_seen"] == 1 and report["accepted"] == 1
    return {"malformed_records": report["malformed_records"]}


def check_mutation(code, killed):
    case = fixture()
    fs = MemoryFiles()
    source = case["sandbox"] + "/module.py"
    original = case["files"]["module.py"]
    fs.put(source, original)
    exits = iter((0, code))
    scope = definitions("tools/sie/probes/exec_probe.py",
                        {"open": fs.open, "_has_tests": lambda root: True,
                         "_pick_src": lambda root: source, "_run_pytest": lambda root: next(exits),
                         "_timeout_s": lambda: 600}, {"run_exec_probe"}, ("TIMEOUT_CODE",))
    report = scope["run_exec_probe"](case["sandbox"])
    assert report["mutation_killed"] is killed, "mutation verdict must distinguish infrastructure failure"
    assert fs.files[source] == original.encode(), "mutated source was not restored"
    assert (report["unavailable_reason"] is None) is killed, "missing or spurious failure reason"
    return {"code": code, "killed": killed, "restored": True}


def check_append(name, tail):
    case = fixture()
    fs, runtime, base, cal, state, events = environment(case)
    path = case["run"] + "/events.jsonl"
    prefix = (json.dumps(case["init_event"]) + "\n").encode()
    fs.put(path, prefix + tail)
    events["append_event"](case["run"], case["accept_event"])
    replayed = events["replay"](case["run"])
    assert replayed.phase == "ARCHIVE" and replayed.parent_vid == "v1", "complete appended event was lost"
    assert fs.files[path].startswith(prefix + tail), "existing event bytes were changed"
    assert fs.fsyncs == 1, "append must retain fsync"
    return {"phase": replayed.phase, "parent_vid": replayed.parent_vid}


def check_status(name):
    case = fixture()
    fs, runtime, base, cal, state, events = environment(case)
    args = SimpleNamespace(cmd="init", target=case["target"], run_id=case["run_id"])
    class Parser:
        def __init__(self, *args, **kwargs):
            pass
        def add_subparsers(self, **kwargs):
            return self
        def add_parser(self, *args, **kwargs):
            return self
        def add_argument(self, *args, **kwargs):
            pass
        def parse_args(self, argv):
            return args
    namespace = dict(base, sys=sys, argparse=SimpleNamespace(ArgumentParser=Parser),
                     _run_dir=lambda *unused: case["run"], load_state=state["load_state"],
                     archive=SimpleNamespace(pareto_front=lambda path: []),
                     gate_human=SimpleNamespace(pending=lambda path: []))
    cli = definitions("tools/sie/cli.py", namespace, {"_main", "main"})
    if name != "before-init":
        with contextlib.redirect_stdout(io.StringIO()):
            assert cli["main"]([]) == 0
    if name == "saved-state":
        fs.put(case["run"] + "/state.json", json.dumps({
            "run_id": case["run_id"], "phase": "ARCHIVE", "round": 1,
            "parent_vid": "v1", "tier": "A"}))
    args.cmd = "status"
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
        code = cli["main"]([])
    assert code == 0, "status failed after successful init"
    report = json.loads(output.getvalue())
    if name == "saved-state":
        assert report["phase"] == "ARCHIVE"
    else:
        assert report["status"] == "uninitialized"
    return {"code": code, "status": report.get("status", report.get("phase"))}


def run_controls():
    case = fixture()
    rows = []
    checks = (
        [("scoring", name, lambda name=name, allowed=allowed: check_scoring(name, allowed))
         for name, allowed in case["scoring"]]
        + [("counter", str(index), lambda fragment=fragment: check_counter(fragment))
           for index, fragment in enumerate(case["invalid_events"])]
        + [("mutation", str(code), lambda code=code, killed=killed: check_mutation(code, killed))
           for code, killed in case["mutation"]]
        + [("append", name, lambda name=name, tail=tail: check_append(name, tail))
           for name, tail in case["append_tails"]]
        + [("status", name, lambda name=name: check_status(name)) for name in case["status"]]
    )
    for group, name, operation in checks:
        try:
            details = operation()
            rows.append({"group": group, "case": name, "satisfied": True, "details": details})
        except Exception as exc:
            rows.append({"group": group, "case": name, "satisfied": False,
                         "error_type": type(exc).__name__, "error": str(exc)})
    return rows


class Review11BehaviorTests(unittest.TestCase):
    def test_generated_behavior_contracts(self):
        for row in run_controls():
            with self.subTest(group=row["group"], case=row["case"]):
                self.assertTrue(row["satisfied"], row)
