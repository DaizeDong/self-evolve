# Patch admission

Implementation: `tools/sie/patch.py`, `tools/sie/sandbox.py`, and `tools/sie/immutable.py`.

`apply_patch(sandbox_root, file_rel, new_content, allow=None, enforce_immutable=False)`
checks a proposed file before writing it. A rejected file is not written. An accepted
file returns `{"status": "APPLIED", "reason": "ok"}`; acceptance here only admits
the file for later grading.

## Ordered checks

1. With `enforce_immutable=True`, reject paths covered by the immutable adjudication
   code list. The selfboot supervisor separately checks its frozen hashes.
2. Resolve the proposed destination with `canonical_in_sandbox`. Reject traversal,
   an outside symlink destination, a sibling with the same path prefix, or another drive.
3. For Python files, enforce the import allowlist and baseline dangerous-call checks.
4. Run the fuller AST check, then create parent directories and write UTF-8 text.

The import allowlist permits modules that contain useful filesystem APIs. Allowing
an import does not approve every capability in that module.

## Filesystem checks

With `sandbox_root`, both `import_gate` and `scan_ast_dangerous` use the same
resolved-call checks. They follow imports and simple assignment aliases, including
bound pathlib methods. Recognized filesystem calls must have paths that can be
resolved from literals, simple aliases, pathlib constructors, literal joins, or
parent expressions. Relative I/O paths are resolved from the sandbox working
directory used by the grader.

The supported checks cover built-in and io open calls, os file operations, shutil
copy/move/delete operations, glob patterns, explicit tempfile directories, logging
file handlers, and pathlib I/O methods. Copy, move, rename, and link operations
check both path arguments. Pathlib glob/rglob checks the receiver and pattern.
Default tempfile locations, dynamic paths, argument expansion, and unproven file
descriptors are rejected for the recognized call forms. Unsupported os, shutil,
tempfile, io, glob, and logging configuration capabilities are rejected; explicitly
listed pure path or in-memory helpers remain allowed. Dynamic getattr on recognized
filesystem modules and pathlib objects is rejected.

`scan_ast_dangerous(source, *, allow_imports=None, sandbox_root=None, target_path=None)`
returns a list of reasons. `import_gate(source, allow=None, *, sandbox_root=None,
file_rel=None)` returns an accepted flag and reason. Omitting `sandbox_root`
does not establish filesystem confinement.

## Limits

This gate is static admission. It does not isolate a process or prove arbitrary
Python behavior safe. Container-based callable aliases, indirect calls through
other code, runtime changes to paths, races, and ambient process permissions
remain outside its guarantee. A passing gate must not be reported as proof of
operating-system filesystem or network isolation. Execution requires separately
verified controls for the deployment environment.

Generated regression cases exercise the scan, import gate, and complete
`apply_patch` entry point. The cases include accepted local operations and
rejected outside, dynamic, descriptor, configuration, and pattern forms; the
candidate payloads are written only when admitted and are never executed by
these tests.
