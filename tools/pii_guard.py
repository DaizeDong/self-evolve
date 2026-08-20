#!/usr/bin/env python3
# pii-guard:scanner-file -- this file must contain the shapes it detects; see SCANNER_MARKER
"""pii_guard -- keep real-world identifiers out of a public repo. Structural, allowlist-based.

WHY THIS EXISTS (read before changing it)
-----------------------------------------
These repos are authored by an agent that is simultaneously looking at the operator's real private
data. When it needs an example, the nearest example is that real data. In 2026-07 that produced real
PII in several public repos across a range of categories -- contact details, a home location, an
employer name, a health-provider name, a social handle, and the operator's private machine paths
(a home dir / a hardcoded ~/.<tool> script path) baked into the CODE of a public tool -- plus the
operator's real email stamped on the author line of nearly every commit. (The categories are named
here only to show the guard's coverage; the specifics belong to the operator and are deliberately
kept out of this file.)

Each of those was "fixed" at the time by editing the offending FILE. The working tree went clean and
the commit that introduced it stayed on GitHub forever. That is the failure this guard exists to make
structurally impossible:

  1. A DENYLIST CANNOT WORK. It is written by the same author who leaks, so it only ever blocks what
     that author already thought of. The 2026-07 leak was a vendor the denylist had never heard of.
     Worse: a denylist of real identifiers IS a PII document -- committing it to the public repo is
     itself the leak. So this guard is an ALLOWLIST: it flags every real-world-shaped identifier that
     is not from the declared synthetic namespace, including vendors nobody anticipated. It contains
     no private data and is safe to publish.

  2. HISTORY IS PART OF THE ARTIFACT. Scanning only `git ls-files` is why every previous "fix" left
     the leak live in an old commit. `--history` scans every blob, every commit message, and every
     author/committer line reachable from any ref.

  3. THE GATE MUST BE AT THE PUSH BOUNDARY. A test only fails if someone remembers to run it, and a
     `pytest && git push` chain can mask the failure. The pre-push hook fails closed.

ESCAPE HATCH
------------
Real third-party identifiers are sometimes the legitimate content of a repo (a vendor's public
sender address that a parser must recognize). Put those in a repo-local `.pii-allow`, one literal per
line with a `# reason`. That is an allowlist entry with a written justification -- reviewable in the
diff, unlike a silent regex tweak.

OPTIONAL PRIVATE LAYER (rebuilt 2026-08-20; see THE POLICY LAYER below for the full argument)
----------------------
If `~/.pii-denylist.json` exists it is read at runtime for extra literals (the operator's own real
tokens). It never lives in any repo. Absent -> skipped and SAID OUT LOUD, structural checks still
run everywhere (CI, contributors, other machines).

That layer used to be a flat list of strings with one punishment, and it had two faults that were
not bugs but consequences of the shape:

  RETROACTIVE VIOLATIONS. Private repo names were added to the list automatically, so creating a
  repo turned prose written before it existed into a finding, in history, where the only remedy on
  offer was a rewrite. Fixed by giving tokens a KIND and letting the scan DOMAIN decide the force:
  irreversible identifiers keep full jurisdiction, topology gates live content and is reported as
  debt in history. No dated ledger is involved, because the question is never asked.

  AUTOMATIC GROWTH. The single most common act here, giving a public skill a private companion
  named `<skill>-config`, added a token -- for a string any reader can reconstruct from the public
  name plus a convention these repos publish themselves. Fixed by admitting such names as
  `derived`: reported, never gating. Measured on the live map: 11 of 18 (61%) stop being
  enforcement material.

The loader now also proves it worked before anything is called clean: a canary it asserts is
present, a count it compares, and a probe that the matcher can still say yes. Anything it cannot
verify raises and exits 2, because an unverifiable policy is an absent scan wearing a green light.

USAGE
  python pii_guard.py --tree               # fast: git-tracked working tree (pre-commit)
  python pii_guard.py --tree --history     # full: + every blob/message/author in history (pre-push)
  python pii_guard.py --tree --history --repo /path/to/repo
  python pii_guard.py grant --token X --scope history-only --exposure accepted-public \
      --reason "..." --nonce <printed at the block>
Exit 0 = no blocking findings. Note that 0 does NOT mean silence: HISTORY-DEBT and WARN lines are
         printed on a passing run and the summary refuses to say "clean" while any are outstanding.
         The hooks print the guard's output unconditionally for exactly this reason.
     1 = a blocking finding (prints file:line and what tripped it).
     2 = the scan could NOT be performed: git unusable, not a work tree, or the private policy
         could not be trusted. Never confuse 2 with 0: see _run and PolicyError for the two
         fail-opens this replaced.
Stdlib only.
"""
import argparse
import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------- the synthetic namespace (ALLOW)
# The ONLY identifiers a public repo may contain. Everything else that LOOKS like a real-world
# identifier is a finding. Extend deliberately -- every addition widens what can leak.
ALLOWED_EMAIL_DOMAINS = {
    "example.com", "example.org", "example.net", "example.edu",
    "acme.com", "acme.io", "acme.test",
    "test.com", "localhost", "domain.com",
    "users.noreply.github.com", "noreply.github.com", "github.com",
    "anthropic.com",                      # noreply@anthropic.com in generated commit trailers
}
# A mailbox at a consumer mail provider is a PERSON'S ADDRESS. It is never legitimate fixture data
# and it must never appear anywhere -- not in the tree, not in an old commit, not in a commit
# message. This is the one email rule that is enforced against HISTORY as well (see scan_text).
PERSONAL_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
    "yahoo.com", "ymail.com", "aol.com", "icloud.com", "me.com", "mac.com",
    "proton.me", "protonmail.com", "pm.me", "tutanota.com", "zoho.com", "gmx.com", "mail.com",
    "qq.com", "foxmail.com", "163.com", "126.com", "sina.com", "yeah.net",
}
# ...but a consumer domain is not automatically a PERSON. Docs legitimately write
# `--user x@gmail.com` and configs `"user": "user1@gmail.com"` -- the provider is the point, the
# mailbox is a blank. Only these local parts count as blanks; a NAMED mailbox at a consumer provider
# (`firstname.lastname@gmail.com`) is a person and is always a finding. Keep this list short: every
# entry is a hole a real address could hide in.
PLACEHOLDER_LOCAL_PARTS = {"x", "y", "z", "a", "b", "u", "me", "you", "user", "user1", "user2",
                           "test", "foo", "bar", "someone", "example", "your-email", "youremail"}
ALLOWED_EMAIL_SUFFIXES = (".test", ".invalid", ".example", ".local", ".internal", ".localdomain",
                          ".example.com", ".example.org", ".example.net")   # mail.example.com etc
# A domain that announces itself as an example: `example-employer.com`, `example-ct-subaru.com`.
# RFC 2606 only reserves `example.com`, so fixtures that need many distinct senders need a
# convention -- this is it, and it is declared here rather than case-by-case in a denylist.
ALLOWED_EMAIL_DOMAIN_RE = re.compile(r"^example[-.]", re.I)
# NANP reserves the 555 exchange for fiction. Accept it in EITHER position: fixtures write both
# `(555) 867-5309` (555 as area code) and `201-555-0100` (555 as exchange).
ALLOWED_PHONE_555 = "555"
ALLOWED_ZIPS = {"10001", "00000", "12345", "90210"}
# Author identity: a public commit must never carry a real mailbox. GitHub's own web/Actions
# committer (`noreply@github.com`) is not a person's address and is accepted.
ALLOWED_AUTHOR_EMAIL_RE = re.compile(r"(@users\.noreply\.github\.com|^noreply@github\.com)$", re.I)

# ---------------------------------------------------------------- structural detectors
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,}\b")
# NANP: optional +1, area code 2-9, exchange 2-9. Rejects version strings / ids (needs separators
# or parens) to keep the false-positive rate survivable.
PHONE_RE = re.compile(r"(?<![\w.\-])(?:\+?1[\s.\-])?\(?([2-9]\d{2})\)?[\s.\-]([2-9]\d{2})[\s.\-](\d{4})(?![\w.\-])")
# A hyphen-only triple is ALSO how machine learning code writes a shape. `conv kernel 512-256-1024`
# matches the NANP pattern exactly: area 2-9, exchange 2-9, four digits. This machine's pre-commit
# hook runs in EVERY repo on it, including a dozen forks of training frameworks, so that false
# positive is not hypothetical -- it is a blocked commit in somebody else's project, which is the
# precise event that ends with --no-verify and a gate that guards nothing anywhere.
#
# So the hyphen-only form yields when a dimension word is nearby. Every other form is untouched:
# parentheses, a +1 prefix, dots or spaces as separators are all shapes a tensor shape never takes,
# and they keep firing regardless of context. Note the boundary classes now also exclude `-`, so a
# longer chain like 128-512-256-1024 no longer matches a window inside itself.
DIMENSION_CONTEXT_RE = re.compile(
    r"\b(?:kernel|layer|layers|dim|dims|dimension|shape|size|sizes|conv|hidden|channel|channels|"
    r"stride|padding|batch|seq|embed|embedding|filter|filters|units|neurons|heads|width|height|"
    r"resolution|mlp|ffn|vocab|window|patch|grid|tile|block|blocks|stage|stages)\b", re.I)
PHONE_CONTEXT_WINDOW = 40
# A bare 5-digit number is unusable as a signal (dates, ids, hashes). Only flag a ZIP where the text
# says it is one -- which is the shape a real home ZIP arrives in ("ship to <state> <zip>").
#
# The bare word `zip` also means the archive format, and "the zip archive is 45231 bytes" was a
# false positive on ordinary technical prose. The postal anchors are kept as they were; the bare
# `zip` anchor now declines when the next word is about compression. Recall is unchanged for the
# shape that actually leaked ("ship to <state> <zip>") and for a plain "ZIP 10001".
ZIP_RE = re.compile(
    r"(?:\bzip\s*code\b|\bzipcode\b|\bpostal\s*code\b|邮编"
    r"|\bship(?:ping)?\s+to\b|\bdeliver\s+to\b"
    r"|\bzip\b(?!\s*(?:archive|file|files|format|compress|compressed|compression|extract|"
    r"extraction|bomb|entry|entries|member|members|64|utility|tool|stream|reader|writer)))"
    r"[^\n]{0,24}?\b([0-9]{5})\b", re.I)

# ---- machine paths ----------------------------------------------------------------------------
# A public repo must never carry the operator's real home directory. This is the SAME kind of
# structural, allowlist-shaped check as EMAIL/PHONE -- a home path has a fixed shape -- and it is the
# class the 2026-07 audit found leaking most: a hardcoded `~/.claude/scripts/<private-script>` and
# `C:\Users\<name>\...` in the CODE and docs of public tool repos, which the guard had no detector
# for and waved straight through. Two shapes, both enforced against tree AND history (a breach):
#
# HARD (USER-PATH): a real account name in a home path -> reveals the operator's username; never
#   legitimate. `C:\Users\<name>`, `/home/<name>`, `/Users/<name>` for a non-generic <name>.
# The separator run is `\\{1,4}` and not a single backslash, which was a real miss: a Windows
# home path is written with DOUBLED backslashes everywhere it passes through a string literal --
# every settings.json, every non-raw Python or JS source line, every JSON config. Measured
# 2026-08-20: the single-backslash form was caught and `C:\\\\Users\\\\<name>\\\\...` was missed
# entirely, in the category the 2026-07 audit found leaking MOST. Four allows for one more
# level of escaping (a path inside a JSON string inside another JSON string, which is how a
# config gets embedded in a workflow file).
USER_PATH_RE = re.compile(r"(?:[A-Za-z]:\\{1,4}Users\\{1,4}|/(?:home|Users)/)([A-Za-z0-9][\w.\-]{0,31})")
GENERIC_USERS = {"public", "default", "defaultuser", "administrator", "admin", "user", "users",
                 "shared", "guest", "root", "runner", "runneradmin", "vscode", "distiller", "vagrant",
                 "ubuntu", "ec2-user", "circleci", "travis", "jenkins", "you", "youruser", "username",
                 "name", "someone", "example", "test", "me", "home", "app", "docker", "node",
                 "foo", "bar", "baz", "alice", "bob", "yourname", "your-name"}
# SOFT (PRIVATE-PATH): a HOME-ANCHORED reference into a private-tool dir -- `~/.claude/scripts`,
#   `$HOME/.agent-center`, `%USERPROFILE%\.secrets`. The ANCHOR is the whole discriminator: a leak is
#   a hardcoded home path (`os.path.expanduser("~/.claude/scripts/x")`), whereas a bare `.claude.json`
#   in a .gitignore or a `.claude-plugin/plugin.json` manifest has NO anchor and is a PUBLIC Claude
#   Code convention. A repo's OWN `.<name>-config` companion is a false positive on itself -- cross-repo
#   config references are P1.5's job -- so `-config` is deliberately NOT matched here. The dir NAMES are
#   public tool conventions (no private data), safe to publish.
# Only dirs that are the OPERATOR's private machine state, never a public tool convention. Excluded on
# purpose: `.codex` / `.claude.json` (a tool's own documented config), `.pii-guard` (this guard's own
# mechanism), `.llmcall` / `.memory-doctor` (a tool's own runtime dir -- a self-reference in its repo).
PRIVATE_DOTDIRS = ("claude", "agent-center", "secrets", "pw-auth")
PRIVATE_PATH_RE = re.compile(
    r"(?:~|\$HOME|\$env:USERPROFILE|\$env:HOME|%USERPROFILE%)[\\/](\.(?:"
    + "|".join(PRIVATE_DOTDIRS) + r")\b[\w./\\-]*)", re.I)
# Public Claude Code conventions sharing the .claude prefix that are NOT a private-dir reference: the
# config file (~/.claude.json), the plugin manifest (.claude-plugin/), and the SHALLOW install dirs
# `~/.claude/{skills,plugins,agents,commands}[/<name>]` (a repo naming its OWN install location). A
# DEEPER path -- `~/.claude/skills/<name>/scripts/<file>` -- is a hardcoded path into a tool's
# internals (exactly how llmcall leaked another tool's relay.py) and stays a finding; a legitimate
# self-reference goes in .pii-allow with a reason.
PUBLIC_DOTPATH_RE = re.compile(
    r"^\.claude(?:\.json\b|-plugin|[\\/](?:skills|plugins|agents|commands)(?:[\\/][\w.\-]+)?[\\/]?$)",
    re.I)

# Python decorators read as emails to the regex: a diff line `+@pytest.mark.xfail` scans as
# `+@pytest.mark.xfail`, and `def n@pytest.mark.skip` as `n@pytest.mark.skip`. Match on the DOMAIN
# side -- the local part is whatever character happened to precede the `@`.
NOT_A_DOMAIN_RE = re.compile(r"^(pytest|mark|fixture|param|parametrize|patch|mock|staticmethod|"
                             r"classmethod|property|dataclass|app|router|task)\b", re.I)

SKIP_DIR = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".pytest_cache"}
# The guard and its tests MUST contain the shapes they detect -- a test proving a real-looking phone
# number is caught has to contain a real-looking phone number. So the STRUCTURAL checks are skipped
# on them. The PRIVATE DENYLIST is NOT: without that, "name it test_pii_guard.py" would be a hole
# straight through the gate. (`.pii-allow` is the allowlist itself; scanning it just re-finds it.)
SCANNER_FILES = {"pii_guard.py", "test_pii_guard.py", "test_pii_guard_v2.py", ".pii-allow"}
# ...but matching that set by BASENAME was a hole straight through the gate, which is the very
# thing the comment above warns about and then did not prevent. `git mv secrets.md
# docs/pii_guard.py` bought a file, anywhere in the repo, that skipped every structural check.
# The exemption is for THESE files at THEIR vendored locations, so it is keyed on the repo-relative
# path. install.py puts them exactly here and nowhere else.
SCANNER_PATHS = {"tools/pii_guard.py", "tools/test_pii_guard.py", "tools/test_pii_guard_v2.py",
                 ".pii-allow"}


# The guard's own files carry this marker, and a basename match OUTSIDE the vendored paths is
# honoured only when the marker is present. That is the difference between exempting a file because
# of what it IS and exempting it because of what it is CALLED: `git mv secrets.md docs/pii_guard.py`
# gets nothing, while a legitimate vendored copy at a non-standard path (skill-smith ships one as a
# template asset) keeps working without anyone maintaining a list of blessed locations.
SCANNER_MARKER = "pii-guard:scanner-file"


def _norm_rel(rel):
    # NOT lstrip("./"): lstrip takes a SET of characters, so ".pii-allow" came back as
    # "pii-allow" and the repo's own allowlist stopped being recognised as a scanner file --
    # it was then scanned, and the paths quoted in its own justification comments became findings.
    rel = rel.replace(chr(92), "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


def is_scanner_path(rel):
    """True for the guard's own files at their vendored paths. Deny-only, never skip-all."""
    return _norm_rel(rel) in SCANNER_PATHS


# The marker is the FORWARD mechanism: from now on, a copy of a scanner file at a non-standard
# path says so. But history is full of blobs written before the marker existed, and recognising a
# file only by the marker made every one of them a fresh finding on the day the rule changed --
# content that had not moved, verdict that had. That is precisely the retroactive violation the
# rest of this redesign exists to remove, and it showed up within an hour of the object-graph
# history scan landing: a repo that vendors the guard as a template asset went from clean to 25
# blocking findings, all of them synthetic fixtures inside old copies of this very file.
#
# So identity is also established INTRINSICALLY, by things only these files contain. A renamed
# secrets file does not acquire `ALLOWED_EMAIL_DOMAINS` by being renamed.
SCANNER_SIGNATURES = (SCANNER_MARKER, "ALLOWED_EMAIL_DOMAINS = {", "import pii_guard as g")


def is_scanner_content(rel, text):
    """True for a copy of a scanner file living somewhere else, proven by its own content."""
    if text is None or os.path.basename(_norm_rel(rel)) not in SCANNER_FILES:
        return False
    return any(sig in text for sig in SCANNER_SIGNATURES)
# Same reason, for the history pass: exclude the scanner blobs from the diff scan. Commit MESSAGES
# are scanned separately and unconditionally -- they are not covered by a pathspec.
HISTORY_EXCLUDE = [":(exclude)*pii_guard.py", ":(exclude)*test_pii_guard.py", ":(exclude)*.pii-allow"]
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".ico", ".woff", ".woff2",
              ".sqlite3", ".db", ".bundle", ".pack", ".webp", ".mp4", ".xlsx"}


class GitError(RuntimeError):
    """A git invocation this scan depends on did not succeed.

    Raised, never swallowed. See _run for why an exception and not an empty string.
    """


def _run(args, cwd, allow_fail=False):
    """Run a git command and return its stdout.

    THIS USED TO FAIL OPEN, and it was the whole tool's single point of failure. The old body was
    `return p.stdout if p.returncode == 0 else ""`. Every caller reads that empty string as an
    ANSWER: no tracked files, no history, no staged diff. scan_tree's loop then iterated zero times,
    findings stayed empty, and main() printed "pii_guard: clean (tree)" and exited 0 having read not
    one byte. Everything that can break git produced that result -- a directory that is not a repo,
    an extracted git-archive with no .git, git absent from PATH, an index.lock, a permission error,
    a dubious-ownership refusal. The vendored CI workflow's entire job is running this command, so a
    workflow that scanned nothing reported success, on 18 public repos where this is the authority.

    So: a nonzero exit RAISES, carrying git's own stderr. A clean report now requires that the scan
    actually happened.

    allow_fail=True is ONLY for the calls where failure is an ordinary state of a healthy repo, not
    a broken environment. Those get None -- deliberately distinct from "", which still means "git
    succeeded and the output was genuinely empty" (an empty diff, a repo with no matching files).
    Callers must not blanket-convert: see the note on each one.
    """
    # encoding="utf-8" is NOT decoration. Without it text=True decodes with the locale codepage,
    # which on Windows is cp1252/cp936 while git emits UTF-8, and errors="replace" then turns every
    # non-ASCII byte into U+FFFD in SILENCE. The visible damage was `git rev-parse --show-toplevel`
    # in a repo whose path contains non-ASCII: the toplevel came back mojibake, the `git ls-files`
    # that followed got cwd=<a path that does not exist>, and the scan died. Before this function
    # was made to fail closed that same mojibake produced a clean report over zero files, which is
    # the fail-open it was hardened against -- so the decoding, not just the exit code, is load
    # bearing. dash_guard's runner already did this; this one was the outlier.
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except (OSError, ValueError) as e:
        if allow_fail:
            return None
        raise GitError("cannot execute `%s` in %s: %s\n"
                       "  (is git installed and on PATH?)" % (" ".join(args), cwd, e)) from None
    if p.returncode != 0:
        if allow_fail:
            return None
        raise GitError("`%s` exited %d in %s\n  %s"
                       % (" ".join(args), p.returncode, cwd,
                          (p.stderr or "").strip().replace("\n", "\n  ") or "(no stderr)"))
    return p.stdout


def _has_commits(root):
    """True if HEAD resolves. A repo with no commits yet is legitimate, and every `git log` in it
    exits 128 -- that is the one git failure here that is a STATE, not a breakage."""
    return _run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], root, allow_fail=True) is not None


def _repo_root(start):
    """The repo containing `start`. Raises rather than falling back to `start` itself.

    The old `return out or start` meant a non-repo directory silently became its own "root", and the
    ls-files that followed failed into an empty list. Refusing here is the honest answer: this tool
    scans what git enumerates, so with no repo there is nothing to scan and "clean" would mean
    "not examined".
    """
    out = _run(["git", "rev-parse", "--show-toplevel"], start).strip()
    if not out:
        raise GitError("git named no toplevel for %s (is it a work tree?)" % start)
    return out


def _repo_slug(root):
    """The origin remote parsed to (owner/name, name), both lowercased; ('', '') if there is no origin.

    Two callers need to identify the current repo from its origin URL: the per-repo denylist
    exemption (keyed on owner/name) and the P1.5 self-exclusion (keyed on name). Kept in one place so
    the parse cannot drift between them. NOTE: `git filter-repo` strips the origin remote, so inside a
    freshly-filtered bare clone this returns ('', '') -- self-exclusion then cannot fire and a repo's
    OWN `<name>-config` companion false-positives; re-add origin before scanning such a clone.
    """
    # allow_fail: a repo with no origin is ordinary (a local-only repo, a filter-repo'd clone), and
    # the documented contract of this function is already ('', '') in that case.
    url = (_run(["git", "remote", "get-url", "origin"], root, allow_fail=True) or "")
    url = url.strip().lower().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    parts = [p for p in url.replace(":", "/").split("/") if p]
    key = "/".join(parts[-2:]) if len(parts) >= 2 else ""
    name = parts[-1] if parts else ""
    return key, name


# ================================================================= THE POLICY LAYER (v2)
# Everything from here to `build_policy` replaces what used to be "a flat list of strings the
# operator typed". The redesign is two orthogonal ideas; the rest is bookkeeping.
#
# IDEA 1 -- A TOKEN'S JURISDICTION DEPENDS ON WHAT KIND OF THING IT IS.
# The old layer put three different animals in one cage and gave them one punishment:
#   a real personal identifier   irreversible, no legitimate public use, must never have existed
#   a private repo NAME          reveals topology, and CRUCIALLY it HAS A DATE OF BIRTH
#   a real proper noun           has legitimate public uses; only private in context
# Applying "block everywhere including all of history" to the second class is what produced
# retroactive violations: a sentence written BEFORE a repo existed became a finding on the day
# that repo was created, and the only remedy on offer was rewriting history over a name. So a
# token now carries a `kind`, and the scan DOMAIN decides the force:
#
#     kind          tree/staged/range        history
#     secret        BLOCK                    BLOCK
#     linkage       BLOCK                    DEBT   (reported and counted, does not gate)
#     derived       WARN                     WARN
#     associative   BLOCK if co-occurring    DEBT/WARN
#
# Note what this buys with no dated bookkeeping at all: content written before a token existed
# can only ever be a linkage or derived hit in HISTORY, and neither gates there. No first-seen
# ledger, no clock comparison, no human adjudicating which old lines deserve amnesty. The
# ledger approach fails the moment its cache is rebuilt; this cannot, because it never asks
# the question. (Same jurisdiction split as GitHub push protection, which blocks new content
# and routes pre-existing findings to an alert surface, and as clean-as-you-code gating.)
#
# `secret` is the DEFAULT for anything unlabelled. A slip of the finger lands on the strict
# side; only an explicit declaration relaxes anything.
#
# IDEA 2 -- A TOKEN THAT ANYONE CAN DERIVE FROM PUBLIC FACTS IS NOT A SECRET.
# The old layer added every private repo name automatically, so the denylist grew each time a
# repo was created, and each new entry retroactively condemned old prose. But this fleet names
# a private companion `<public-repo>-config`, and that convention is DOCUMENTED IN THE PUBLIC
# REPOS THEMSELVES. Given the public name, anyone can write down the private one. Its marginal
# information is zero, and treating it as a secret means paying a history rewrite for a string
# that discloses nothing. So:
#
#     derivable(t)  <=>  exists a PUBLIC repo p under the same owner, and a documented
#                        suffix c, such that t == p + c
#
# Derivable names are admitted as `derived` (reported, never gating). Everything else keeps
# full `linkage` force. This is what stops the automatic growth at the source: the single most
# common act on this machine, giving a public skill a private companion, now adds nothing.
# Measured against the live visibility map on 2026-08-20: 11 of 18 cross-repo tokens (61%)
# are derivable and stop being enforcement material.
#
# The direction matters and is preserved: if the PARENT is private too, the child name is NOT
# derivable from anything public, and it stays `linkage`.
POLICY_FORMAT_SUPPORTED = 2
KINDS = ("secret", "linkage", "derived", "associative")
DEFAULT_KIND = "secret"
# A canary the loader asserts is present. It lives in the SYNTHETIC namespace on purpose: if it
# ever leaked it would be harmless, and it can be written down here, in a public file.
CANARY_TOKEN = "zz-pii-canary-do-not-remove"
# A probe string that is NOT read from any file, used to prove the matcher itself executes.
# TWO probes, because _deny_hit has two branches and one probe only exercises one of them. A token
# containing a digit takes the raw-substring path; a purely alphabetic one takes the word-bounded
# regex path -- which is the branch most of the private layer actually uses, and which was unprobed.
MATCHER_PROBE = "zzmatcherprobe-9137"
MATCHER_PROBE_ALPHA = "zzmatcherprobealpha"
# The documented naming conventions for a private companion of a public repo. Adding a suffix
# here widens what counts as derivable, so it is a deliberate, reviewable act.
CONVENTION_SUFFIXES = ("-config", "-data", "-private", "-secrets")
SEVERITIES = ("BLOCK", "DEBT", "WARN")
DOMAINS = ("tree", "staged", "range", "history")


_UNATTESTED_NOTE = (
    "pii_guard: WARNING %s is in the legacy format: no canary and no count, so this run CANNOT\n"
    "  tell a complete policy from a half-deleted one. Deleting entries from a JSON array leaves\n"
    "  valid JSON and the survivors keep working. Upgrade it with migrate_denylist.py.")


class PolicyError(RuntimeError):
    """The policy layer could not be loaded in a state worth trusting.

    Deliberately routed to exit code 2, the same code as "git was unusable", because it means
    the same thing: THE SCAN DID NOT REALLY HAPPEN. The old loader answered every one of these
    with `toks = []`, which is not an error value, it is an ANSWER -- and the answer it gives is
    "there are no private tokens", which is indistinguishable in the output from a healthy run
    over clean content. A truncated file, a renamed key, a file re-saved as UTF-16: each one
    silently deleted the entire second layer while the hook printed green.
    """


class Token(object):
    """A denylist entry, what KIND of thing it is, and (for `derived`) the WITNESS.

    Compares equal to its own string. That is not sugar: this value used to be a bare string
    everywhere, and several callers legitimately only care about the text. Keeping `token ==
    "foo"` true means adding the kind does not silently change the meaning of code that was
    already correct.
    """
    __slots__ = ("value", "kind", "source", "witness")

    def __init__(self, value, kind=DEFAULT_KIND, source="denylist", witness=None):
        self.value = value
        self.kind = kind
        self.source = source
        # For `derived`: the PUBLIC name this one was reconstructed from. A declassification that
        # cannot exhibit its own derivation is an assertion, and this whole layer stops being
        # auditable the moment `derived` means "the code said so".
        self.witness = witness

    def __eq__(self, other):
        return self.value == (other.value if isinstance(other, Token) else other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.value)

    def __str__(self):
        return self.value

    def __repr__(self):
        return "Token(%r, %r)" % (self.value, self.kind)


class Grant(object):
    """One exemption, read from OUTSIDE every work tree.

    scope=history-only exempts the token in the history domain only, which is the shape of
    almost every legitimate request ("this was written years ago, I have accepted it"). Full
    exemption needs scope=all AND a separate justification field, because those two words look
    alike and one of them turns the gate off for live content.
    """
    __slots__ = ("token", "scope", "exposure", "reason", "used")

    def __init__(self, token, scope, exposure, reason):
        self.token = token
        self.scope = scope
        self.exposure = exposure
        self.reason = reason
        self.used = False


EXPOSURES = ("rewritten", "accepted-public", "false-positive", "legacy")


def severity_for(kind, domain):
    """The jurisdiction matrix. One function, so the policy cannot drift between call sites."""
    if kind == "secret":
        return "BLOCK"
    if kind == "linkage":
        return "DEBT" if domain == "history" else "BLOCK"
    if kind == "derived":
        return "WARN"
    if kind == "associative":
        # resolved by the caller, which is the only place that knows about co-occurrence
        return "DEBT" if domain == "history" else "BLOCK"
    raise PolicyError("unknown token kind %r" % kind)


class Policy(object):
    """Loaded tokens plus the grants that may suppress them, plus a receipt.

    THE RECEIPT IS NOT DECORATION. A suppression that silently fails to apply is worse than no
    suppression at all, because the operator believes they have already been through the
    compliant process. So every run states how many grants were declared, how many actually
    fired, and how many could never fire. (ESLint's --report-unused-disable-directives is the
    mature version of this idea: any suppression the system holds, it must be able to account
    for.)
    """

    def __init__(self):
        self.tokens = []
        self.grants = []
        self._pf_key = None
        self._pf = []
        self.notes = []            # loader-level messages that must reach the operator
        self.denylist_present = False
        self.visibility_present = False

    def __bool__(self):
        return bool(self.tokens)

    __nonzero__ = __bool__         # py2-style guard; harmless and keeps the intent obvious

    def prefilter(self):
        """One combined pattern per matching MODE, used only to decide whether to bother.

        The per-line loop ran one regex per token over every line of every tracked file. With 56
        tokens and a 157-file repo that is 4 seconds in the tree scan alone, on a pre-commit hook,
        and slow hooks get bypassed for exactly the same reason noisy ones do.

        A single alternation answers "does ANY token appear here" in one pass. It is used strictly
        as a PREFILTER: on a hit the original per-token loop still runs, unchanged. That matters
        for correctness, not tidiness -- alternation is leftmost-first, so if one token is a
        substring of another the combined pattern reports only one of them, and if the longer one
        happens to be `derived` while the shorter is `secret`, answering from the alternation
        alone would silently DOWNGRADE a real finding. Prefilter, then confirm.

        Two patterns because _deny_hit has two modes and they must agree exactly: alphabetic
        tokens are word-bounded (a short name is a substring of ordinary English, and one
        denylisted given name once matched inside a CSS colour keyword), while digit-bearing ones
        are raw substrings, where a boundary would only cause misses.
        """
        key = tuple(t.value for t in self.tokens)
        if self._pf_key == key:
            return self._pf
        bounded, plain = [], []
        for v in set(key):
            if not v:
                continue
            (plain if (any(c.isdigit() for c in v) or not any(c.isalpha() for c in v))
             else bounded).append(v)
        pats = []
        # longest first: only affects WHICH alternative wins, and this is a prefilter, but it
        # keeps the behaviour predictable if anyone ever reads a match out of it
        if bounded:
            pats.append(re.compile(r"(?<![a-z0-9])(?:%s)(?![a-z0-9])"
                                   % "|".join(re.escape(v) for v in
                                              sorted(bounded, key=len, reverse=True))))
        if plain:
            pats.append(re.compile("|".join(re.escape(v) for v in
                                            sorted(plain, key=len, reverse=True))))
        self._pf_key, self._pf = key, pats
        return pats

    @classmethod
    def of(cls, tokens, kind=DEFAULT_KIND):
        """Build a Policy from a bare iterable of strings or Tokens.

        Exists so that a caller holding a plain list (a test, a one-off script) does not have to
        construct the whole loader. Everything it produces defaults to `secret`, which is the
        conservative reading of "somebody handed me a string and did not say what it was".
        """
        p = cls()
        for t in tokens or ():
            p.tokens.append(t if isinstance(t, Token) else Token(str(t).lower(), kind))
        p.denylist_present = bool(p.tokens)
        return p

    def grant_for(self, token_value, domain):
        for g in self.grants:
            if g.token != token_value:
                continue
            if g.scope == "all" or (g.scope == "history-only" and domain == "history"):
                g.used = True
                return g
            # a history-only grant seen in a live domain still counts as EXERCISED: the operator
            # did write it for this token, and reporting it as never-used would be a lie.
            g.used = True
        return None

    def receipt(self):
        if not self.grants:
            return None
        used = sum(1 for g in self.grants if g.used)
        return ("pii_guard: exemptions -- %d declared, %d matched a token in this run, "
                "%d never fired" % (len(self.grants), used, len(self.grants) - used))


def _read_json(path):
    """Read JSON, raising PolicyError on ANY failure. See PolicyError for why not `= []`."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise PolicyError("cannot read %s: %s" % (path, e)) from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise PolicyError(
            "%s is not UTF-8 (%s).\n"
            "  A editor that saved it as UTF-16 or with a codepage would empty this entire\n"
            "  layer, and the old loader answered that with a green light." % (path, e)) from None
    try:
        return json.loads(text)
    except ValueError as e:
        raise PolicyError("%s is not valid JSON: %s\n"
                          "  Half a file is not half a policy, it is no policy."
                          % (path, e)) from None


def load_repo_allow(root):
    """Repo-local `.pii-allow`: real literals this repo is ALLOWED to contain, each with a reason."""
    path = os.path.join(root, ".pii-allow")
    allow = set()
    if not os.path.isfile(path):
        return allow
    for line in open(path, encoding="utf-8", errors="replace"):
        lit = line.split("#", 1)[0].strip()
        if lit:
            allow.add(lit.lower())
    return allow


def _denylist_path():
    """Where the private token file lives. Never inside a repo; see load_policy."""
    p = os.environ.get("PII_DENYLIST")
    if p:
        return p
    return os.path.expanduser("~/.pii-denylist.json")


def _parse_denylist(path, notes=None):
    """Read the private token file into Tokens, or raise. Accepts v1 and v2 encodings.

    v1 (legacy):  ["tok", ...]                     or  {"tokens": ["tok", ...]}
    v2:           {"format": 2, "count": N, "canary": "...",
                   "tokens": [{"value": "...", "kind": "secret|linkage|derived|associative"}]}

    WHY THE v2 FILE CARRIES A CANARY AND A COUNT
    The v1 encoding cannot tell a healthy file from a damaged one. Delete half the array and
    what remains is still valid JSON, the surviving tokens still work, and nothing anywhere
    says a word. The canary answers "did I load THE file" and the count answers "did I load
    ALL of it". This is the same move already made one layer up, where the machine-wide
    pre-commit hook probes that its case-folding tool actually runs before trusting a
    comparison: a check whose failure mode is silent agreement has to prove it can disagree.
    """
    data = _read_json(path)

    if isinstance(data, list):                       # bare v1 list
        raw, fmt, declared_count, canary = data, 1, None, None
        if notes is not None:
            notes.append(_UNATTESTED_NOTE % path)
    elif isinstance(data, dict):
        fmt = data.get("format", 1)
        if not isinstance(fmt, int) or fmt > POLICY_FORMAT_SUPPORTED:
            # Deliberately NOT "treat everything as secret, that is safer". A silent strictness
            # upgrade would hide the fact that this copy of the guard is older than the policy
            # it is reading, which is the exact condition under which a vendored copy in one of
            # the other repos would be misreading it too.
            raise PolicyError(
                "%s declares format %r but this pii_guard understands up to %d.\n"
                "  This copy is older than the policy file. Re-run install.py --all so every\n"
                "  vendored copy is upgraded, rather than letting each repo guess."
                % (path, fmt, POLICY_FORMAT_SUPPORTED))
        if "tokens" not in data:
            raise PolicyError(
                "%s has no `tokens` key (found: %s).\n"
                "  The old loader read that as an empty denylist and printed a clean result."
                % (path, ", ".join(sorted(k for k in data)) or "nothing"))
        raw = data.get("tokens")
        declared_count = data.get("count")
        canary = data.get("canary") or (CANARY_TOKEN if fmt >= 2 else None)
        if notes is not None and canary is None and declared_count is None:
            notes.append(_UNATTESTED_NOTE % path)
    else:
        raise PolicyError("%s must contain a list or an object, found %s"
                          % (path, type(data).__name__))

    if not isinstance(raw, list):
        raise PolicyError("%s: `tokens` must be a list, found %s" % (path, type(raw).__name__))

    toks = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            value, kind = item, DEFAULT_KIND
        elif isinstance(item, dict):
            value = item.get("value")
            kind = item.get("kind", DEFAULT_KIND)
            if not isinstance(value, str):
                raise PolicyError("%s: token %d has no string `value`" % (path, i))
            if kind not in KINDS:
                raise PolicyError(
                    "%s: token %d has kind %r, which this guard does not know.\n"
                    "  Known kinds: %s. Refusing to guess -- guessing 'secret' would hide a\n"
                    "  version mismatch, and guessing anything weaker would hide a real token."
                    % (path, i, kind, ", ".join(KINDS)))
        else:
            raise PolicyError("%s: token %d is a %s, expected a string or an object"
                              % (path, i, type(item).__name__))
        value = value.strip().lower()
        if value:
            toks.append(Token(value, kind, source="denylist"))

    if not toks:
        raise PolicyError(
            "%s exists but yields zero tokens.\n"
            "  An empty policy file and a missing one are different situations and this one is\n"
            "  almost always damage. If you genuinely have no private tokens, delete the file:\n"
            "  absent is a state the guard reports out loud, empty is one it used to hide."
            % path)

    if canary:
        if not any(t.value == canary.lower() for t in toks):
            raise PolicyError(
                "%s does not contain its own canary %r.\n"
                "  Either the file was truncated, or a key was renamed, or this is not the file\n"
                "  you think it is. Any of those silently disables the whole private layer."
                % (path, canary))
        # The canary is an ATTESTATION, not policy. Leaving it in the token set would make every
        # file that legitimately writes it down a finding -- starting with this one, which has to
        # name it in order to check for it, and which is vendored into every public repo.
        toks_after_canary = [t for t in toks if t.value != canary.lower()]
    else:
        toks_after_canary = toks
    if declared_count is not None:
        if not isinstance(declared_count, int) or declared_count != len(toks):
            raise PolicyError(
                "%s declares count=%r but %d tokens loaded.\n"
                "  Removing entries from a JSON array leaves valid JSON, so this mismatch is the\n"
                "  only thing standing between a half-deleted policy and a green light."
                % (path, declared_count, len(toks)))
    # count is compared against the file's own entries, INCLUDING the canary, because it is a
    # statement about the file. The canary is dropped only after both assertions have run.
    if not toks_after_canary:
        # A file containing ONLY the canary passes every assertion above -- it is present, it is
        # intact, its count is right -- and then yields zero enforceable tokens once the canary is
        # held back. denylist_present goes True, so the "layer absent" note does not print either,
        # and the layer is gone in complete silence. Measured 2026-08-20.
        raise PolicyError(
            "%s contains its canary and nothing else, so the private layer would load with zero\n"
            "  enforceable tokens while reporting itself as present. If you meant to empty it,\n"
            "  delete the file: absent is a state this guard announces, empty is one it hid."
            % path)
    return toks_after_canary


def _probe_matcher():
    """Prove the matcher executes before trusting anything it says.

    A comparison whose failure mode is "nothing ever matches" cannot be validated by observing
    that nothing matched. The machine-wide pre-commit hook already learned this the hard way
    with its case-folding probe: with the tool off PATH both sides folded to the empty string,
    every identity compared equal, and the assertion passed for every input. So: feed the
    matcher a string that appears in no file, and require a hit. Costs microseconds.
    """
    for probe in (MATCHER_PROBE, MATCHER_PROBE_ALPHA):
        _probe_one(probe)
    # ...and the word boundary must actually BOUND. A bounded token must not match inside a longer
    # word, or the false-positive engine the boundary exists to prevent is back and silent.
    if _deny_hit(MATCHER_PROBE_ALPHA, "xx%sxx" % MATCHER_PROBE_ALPHA):
        raise PolicyError(
            "the denylist matcher ignored its word boundary: %r matched inside a longer word.\n"
            "  That is the false-positive engine the boundary exists to prevent."
            % MATCHER_PROBE_ALPHA)


def _probe_one(probe):
    if not _deny_hit(probe, "prefix %s suffix" % probe):
        raise PolicyError(
            "the denylist matcher failed its own probe: it did not find %r inside a string\n"
            "  that plainly contains it. Every 'clean' result from this process would be\n"
            "  meaningless. This is a code fault in _deny_hit, not a configuration problem."
            % probe)
    if _deny_hit(probe, "nothing to see here"):
        raise PolicyError(
            "the denylist matcher matched %r against text that does not contain it.\n"
            "  A matcher that says yes to everything is as useless as one that says no." % probe)


def load_private_denylist(root=None):
    """Back-compatible shim: the flat list of token strings, exemptions already applied.

    Kept because other tooling and the tests call it by this name. New code should use
    load_policy, which preserves the kinds this function has to throw away.
    """
    return [t.value for t in load_policy(root).tokens]


VISIBILITY_STATES = ("PUBLIC", "PRIVATE", "UNKNOWN")


def _load_visibility(vis_path=None, notes=None):
    """(public_names_by_owner, private_keys) from the visibility cache, or None if absent.

    Returning None for "absent" and RAISING for "present but unreadable" is the whole point.
    Absent is ordinary: CI has no cache, a contributor's clone has no cache, and the layer is
    documented as operator-only. Unreadable is damage, and the old code answered damage with
    an empty map -- which reads exactly like "you have no private repos".
    """
    path = vis_path or os.path.expanduser("~/.pii-guard/visibility.json")
    if not os.path.exists(path):
        # Absent is ORDINARY (CI, a contributor, a fresh machine) and it is also INVISIBLE unless
        # somebody says it. Without this note the cross-repo layer can be entirely missing -- a
        # failed refresh, a new machine, a repo not yet registered -- and the run still prints
        # `clean`, which is the exact ambiguity between "checked" and "not checked" that this
        # whole codebase exists to remove. It is a note, not an error: on a runner it is correct.
        if notes is not None:
            notes.append("pii_guard: NOTE no visibility map at %s -- the cross-repo layer "
                         "contributed nothing to this run." % path)
        return None
    vis = _read_json(path)
    if not isinstance(vis, dict):
        raise PolicyError("%s must be an object mapping owner/name to a visibility" % path)
    public, private, unknown = {}, [], set()
    for key, v in vis.items():
        if not isinstance(key, str) or "/" not in key:
            continue                       # `_refreshed`, `_verified` and friends
        state = (v.get("v") if isinstance(v, dict) else v)
        state = str(state).upper()
        owner, _, name = key.rpartition("/")
        owner, name = owner.strip().lower(), name.strip().lower()
        if state == "PUBLIC":
            public.setdefault(owner, set()).add(name)
        elif state == "PRIVATE":
            private.append((owner, name))
        elif state not in VISIBILITY_STATES:
            # An unrecognised state is dropped, and a silently dropped PRIVATE repo is a token
            # that quietly stops existing. The vocabulary here and the vocabulary
            # refresh_visibility.py writes have to agree, and the only way to notice when they
            # stop agreeing is to say so.
            unknown.add(state)
    if unknown and notes is not None:
        notes.append("pii_guard: WARNING %s uses visibility state(s) this guard does not know "
                     "(%s); those entries were skipped. Expected one of %s."
                     % (path, ", ".join(sorted(unknown)), "/".join(VISIBILITY_STATES)))
    return public, private


def derivation_witness(owner, name, public_by_owner):
    """The PUBLIC parent `name` is mechanically reconstructible from, or None.

    The convention that makes this work is not folklore: every public skill repo in this fleet
    ships a `tools/datadir.py` whose module docstring spells out `<skill>-config` as where the
    private companion lives. So the mapping from a public name to its private companion is
    already published, by us, in the repos being scanned. A token anyone can reconstruct from
    published material carries no marginal information, and enforcing it costs history rewrites
    in exchange for nothing.

    Direction is load-bearing. If the PARENT is not public, nothing published points at this name
    and it is not derivable, whatever it is suffixed with. The owner is load-bearing too: the
    convention is per-account, and borrowing somebody else's public name to excuse ours would be a
    hole with a plausible story attached.

    It returns the WITNESS rather than a boolean on purpose. A declassification that cannot
    exhibit its own derivation is an assertion, and the moment `derived` means "the code said so"
    this layer stops being auditable. There used to be an `is_derivable` boolean wrapper beside
    this; it went unused the moment findings started carrying the witness, and an unused predicate
    is a place where a future reader adds a second, drifting definition of the same rule.
    """
    pub = public_by_owner.get(owner) or set()
    for suf in CONVENTION_SUFFIXES:
        if name.endswith(suf) and name[:-len(suf)] in pub:
            return name[:-len(suf)]
    return None


def load_cross_repo_tokens(root, vis_path=None):
    """Operator-machine layer: the NAMES of the operator's OTHER PRIVATE repos, TYPED.

    A public repo that names one of the operator's private repos leaks fleet topology. That is
    real but it is not the same harm as a person's mailbox, and until now it was punished as if
    it were. Each name that survives the distinctiveness filter is now classified:

        derivable from a public sibling  ->  `derived`   reported, never gates
        everything else                  ->  `linkage`   gates live content, DEBT in history

    Absent visibility cache -> empty, exactly as before: the structural checks still run
    everywhere and this layer only ever augmented the operator's own machine.
    """
    return [t for t in _cross_repo_tokens_typed(root, vis_path)]


def _cross_repo_tokens_typed(root, vis_path=None, notes=None):
    loaded = _load_visibility(vis_path, notes)
    if loaded is None:
        return []
    public_by_owner, private = loaded
    _, self_name = _repo_slug(root)
    out, seen = [], set()
    for owner, name in private:
        # DISTINCTIVE slugs only. A private repo called `notes` would false-positive on the
        # English word, and a gate that cries wolf gets bypassed, at which point it guards
        # nothing anywhere. Require the companion suffix, or a multi-part slug that ordinary
        # prose almost never is.
        if not name or len(name) < 5:
            continue
        # SELF-EXCLUSION, precisely. This used to be `name.startswith(self_name + "-")`, a bare
        # prefix test, so a repo called `ab` silently exempted EVERY private repo whose name began
        # `ab-`. Measured 2026-08-20: from inside a repo named `ab`, the private `ab-hidden-thing`
        # produced no finding at all while an unrelated token in the same line did. The intent was
        # only ever "this repo's OWN companion", and that is a closed set: the repo name, or the
        # repo name plus one of the documented suffixes.
        if self_name and (name == self_name
                          or name in {self_name + suf for suf in CONVENTION_SUFFIXES}):
            continue
        # DISTINCTIVENESS. `-config` was hardcoded here while CONVENTION_SUFFIXES lists four, so
        # `<something>-data` with a single hyphen never entered the layer at all: the derivability
        # rule knew about a suffix the admission rule had never heard of.
        if not (name.endswith(CONVENTION_SUFFIXES)
                or (name.count("-") + name.count("_")) >= 2):
            continue
        if name in seen:
            continue
        seen.add(name)
        parent = derivation_witness(owner, name, public_by_owner)
        kind = "derived" if parent else "linkage"
        out.append(Token(name, kind, source="cross-repo",
                         witness=("%s/%s is PUBLIC" % (owner, parent)) if parent else None))
    return sorted(out, key=lambda t: t.value)


def _exempt_path():
    return os.path.expanduser("~/.pii-guard/denylist-exempt.json")


def load_grants(root, notes):
    """Per-repo exemptions, read from OUTSIDE every work tree.

    That location is not an accident and must not be 'improved'. An exemption granted from
    inside a repo would let an agent that is leaking into that repo write itself a permission
    slip in the same commit, and the reviewer would see one diff containing both the leak and
    its authorisation.

    Malformed entries are REPORTED, never silently skipped. The single most likely way to be
    wrong here is to key the block on a bare repo name instead of owner/name, which produces an
    exemption file that looks correct, applies to nothing, and says nothing.
    """
    path = _exempt_path()
    if not os.path.exists(path):
        return []
    data = _read_json(path)
    if not isinstance(data, dict):
        raise PolicyError("%s must be an object keyed on owner/name" % path)
    key, _ = _repo_slug(root)
    grants = []
    for block_key, entries in data.items():
        if block_key.startswith("_"):
            continue                                  # a comment key, by convention
        if "/" not in block_key:
            notes.append(
                "pii_guard: WARNING exemption block %r in %s is not shaped like owner/name, so "
                "it can never match any repo and every grant under it is inert."
                % (block_key, path))
            continue
        if block_key.strip().lower() != key:
            continue
        for i, e in enumerate(entries or []):
            if isinstance(e, str):
                # legacy shape. Honoured, but named, because it carries no stated exposure and
                # therefore nothing a later reviewer can weigh.
                grants.append(Grant(e.strip().lower(), "all", "legacy", "(legacy entry)"))
                notes.append(
                    "pii_guard: WARNING a legacy string exemption in %s is being honoured at "
                    "scope=all with no stated exposure and no reason. Full scope switches the gate "
                    "off for LIVE content, not just history. Rewrite it as an object with scope, "
                    "exposure and reason." % path)
                continue
            if not isinstance(e, dict):
                notes.append("pii_guard: WARNING exemption %d for %s is a %s, ignored"
                             % (i, block_key, type(e).__name__))
                continue
            tok = str(e.get("token", "")).strip().lower()
            scope = e.get("scope", "history-only")
            exposure = e.get("exposure")
            reason = str(e.get("reason", "")).strip()
            if not tok:
                notes.append("pii_guard: WARNING exemption %d for %s has no token, ignored"
                             % (i, block_key))
                continue
            if scope not in ("history-only", "all"):
                notes.append("pii_guard: WARNING exemption for %r has scope %r, ignored "
                             "(expected history-only or all)" % (tok, scope))
                continue
            if scope == "all" and not str(e.get("all_scope_reason", "")).strip():
                notes.append(
                    "pii_guard: WARNING exemption for %r asks for scope=all without an "
                    "all_scope_reason, ignored. Full scope switches the gate off for LIVE "
                    "content, so it takes its own sentence." % tok)
                continue
            if exposure not in EXPOSURES:
                notes.append(
                    "pii_guard: WARNING exemption for %r has exposure %r, ignored (expected "
                    "one of %s). Without it nobody can later judge whether this grant was "
                    "reasonable." % (tok, exposure, ", ".join(EXPOSURES)))
                continue
            if not reason:
                notes.append("pii_guard: WARNING exemption for %r has no reason, ignored" % tok)
                continue
            grants.append(Grant(tok, scope, exposure, reason))
    return grants


def load_policy(root=None, vis_path=None):
    """Assemble the whole second layer, and prove it is worth trusting before returning it.

    Order matters. The matcher probe runs FIRST, because a broken matcher would make every
    later assertion pass vacuously.
    """
    pol = Policy()
    _probe_matcher()

    path = _denylist_path()
    if path and os.path.exists(path):
        pol.denylist_present = True
        pol.tokens.extend(_parse_denylist(path, pol.notes))
    if root:
        cross = _cross_repo_tokens_typed(root, vis_path, pol.notes)
        pol.visibility_present = bool(cross) or os.path.exists(
            vis_path or os.path.expanduser("~/.pii-guard/visibility.json"))
        have = {t.value for t in pol.tokens}
        pol.tokens.extend(t for t in cross if t.value not in have)
        pol.grants = load_grants(root, pol.notes)
    return pol


_DENY_RE_CACHE = {}


def _deny_hit(tok, low_text):
    """Word-bounded match for alphabetic denylist tokens; plain substring for the rest.

    A short first name is a substring of ordinary English. A denylisted given name matched inside a
    CSS colour keyword in a minified JS bundle and turned a personal homepage red. False positives
    are not a nuisance here -- they are how a gate dies: it cries wolf on something harmless, someone
    reaches for --no-verify, and from then on it guards nothing. So bound alphabetic tokens; leave
    digit-bearing ones (phones, ZIPs, account slugs) as raw substrings, where a boundary would only
    cause misses.
    """
    if any(ch.isdigit() for ch in tok) or not any(ch.isalpha() for ch in tok):
        return tok in low_text
    rx = _DENY_RE_CACHE.get(tok)
    if rx is None:
        rx = _DENY_RE_CACHE[tok] = re.compile(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(tok))
    return bool(rx.search(low_text))


# A `.pii-allow` entry has to be SPECIFIC enough to be an exemption rather than an off switch.
# The path classes used to accept `any(a in hl for a in allow)`, an unanchored substring test, so a
# single line reading `users` -- or the letter `a` -- silently disabled every USER-PATH finding in
# that repo. Measured 2026-08-20: both did, in total silence. And `.pii-allow` lives INSIDE the
# repo, so that is an in-repo off switch for the one control that is supposed to be un-turn-off-able
# from inside, which is the shape the whole denylist-versus-allowlist argument rests on.
#
# Legitimate entries are path fragments with a reason attached (`.claude/scripts/self.ps1`). The
# rule is therefore: match the whole hit, or be a substring of at least MIN_ALLOW_FRAGMENT
# characters. Short entries still work for the exact-match classes (an email, a phone), where the
# comparison was never a substring test in the first place.
MIN_ALLOW_FRAGMENT = 8
MIN_ALLOW_PATHISH = 5
_PATHISH = "./" + chr(92)


def is_specific_allow(a):
    """Is this .pii-allow entry specific enough to be used as a SUBSTRING exemption?

    Two ways to qualify: be long, or be shaped like a path fragment. `.claude` is seven characters
    and would fail a pure length rule, but it is a dotted directory name with a written
    justification, not an English word that happens to appear inside a home path. `users` is five
    characters with no separator and, as a substring rule, switches off the entire USER-PATH class.
    """
    return len(a) >= MIN_ALLOW_FRAGMENT or (len(a) >= MIN_ALLOW_PATHISH
                                            and any(c in a for c in _PATHISH))


def vague_allow_entries(allow):
    """Entries too generic to be used as substrings. Reported, never silently ignored."""
    return sorted(a for a in allow if not is_specific_allow(a))


def _allowed_fragment(hl, allow):
    """True when `hl` is covered by a .pii-allow entry that is specific enough to mean it."""
    if hl in allow:
        return True
    return any(is_specific_allow(a) and a in hl for a in allow)


def email_ok(addr, allow):
    if addr.lower() in allow:
        return True
    dom = addr.rpartition("@")[2].lower()
    if NOT_A_DOMAIN_RE.match(dom):
        return True                       # a Python decorator, not an address
    return (dom in ALLOWED_EMAIL_DOMAINS
            or dom.endswith(ALLOWED_EMAIL_SUFFIXES)
            or bool(ALLOWED_EMAIL_DOMAIN_RE.match(dom)))


def scan_text(text, where, allow, pol, out, domain="tree", deny_only=False, strict=None):
    """Append findings for one chunk of text.

    A finding is (where, label, value, severity). Severity is decided by the JURISDICTION
    MATRIX in severity_for: what kind of thing the token is, crossed with which domain we are
    looking at. Structural findings are always BLOCK -- an email, a phone, a home path or a
    real account name in a public artifact has no benign reading in any domain.

    domain="tree" also turns on the STRICT synthetic-namespace rule. The split is the original
    design and it is right: the allowlist is a hygiene rule for content you are writing now, so
    the fixture namespace stays uniformly fake and a real identifier stands out instead of
    blending in. Applied retroactively to years of history it lights up on harmless old
    fixtures, the hook goes permanently red, and a permanently red hook is a bypassed hook.
    """
    if not isinstance(pol, Policy):
        pol = Policy.of(pol)
    if strict is not None:
        # historical keyword, kept because it names the same distinction from the other side
        domain = "tree" if strict else "history"
    strict = (domain == "tree")
    low = text.lower()

    deny_hits = []
    if pol.tokens:
        # PREFILTER, then confirm. One combined alternation answers "does any token appear at all"
        # in a single pass; only on a hit does the per-token loop run. Without it this loop was one
        # regex per token per LINE, which on a 157-file repo with 56 tokens cost four seconds in the
        # tree scan alone -- and a slow hook gets bypassed for the same reason a noisy one does.
        pf = pol.prefilter()
        if not pf or any(rx.search(low) for rx in pf):
            for tok in pol.tokens:
                if _deny_hit(tok.value, low):
                    deny_hits.append(tok)

    structural = []
    if not deny_only:
        for addr in set(EMAIL_RE.findall(text)):
            if addr.lower() in allow:
                continue
            local, _, dom = addr.lower().rpartition("@")
            if dom in PERSONAL_MAIL_DOMAINS and local not in PLACEHOLDER_LOCAL_PARTS:
                structural.append(("PERSONAL-MAILBOX", addr))   # a real person: never, anywhere
            elif strict and not email_ok(addr, allow):
                structural.append(("EMAIL", addr))              # not in the synthetic namespace
        for m in PHONE_RE.finditer(text):
            area, exch, last = m.group(1), m.group(2), m.group(3)
            num = "%s-%s-%s" % (area, exch, last)
            if ALLOWED_PHONE_555 in (area, exch) or num.lower() in allow:
                continue
            hit = m.group(0)
            hyphen_only = ("(" not in hit and "+" not in hit
                           and "." not in hit and " " not in hit)
            if hyphen_only:
                lo = max(0, m.start() - PHONE_CONTEXT_WINDOW)
                if DIMENSION_CONTEXT_RE.search(text[lo:m.end() + PHONE_CONTEXT_WINDOW]):
                    continue          # a tensor shape, not somebody's number
            structural.append(("PHONE", num))
        for z in set(ZIP_RE.findall(text)):
            if z not in ALLOWED_ZIPS and z not in allow:
                structural.append(("ZIP", z))
        for m in USER_PATH_RE.finditer(text):
            if m.group(1).lower() in GENERIC_USERS:
                continue                    # a standard / CI / placeholder account, not a person
            hit = m.group(0)
            if _allowed_fragment(hit.lower(), allow):
                continue
            structural.append(("USER-PATH", hit))               # a real account: never, anywhere
        for m in PRIVATE_PATH_RE.finditer(text):
            dotpath = m.group(1)
            dl = dotpath.lower()
            if PUBLIC_DOTPATH_RE.match(dl):
                continue                    # ~/.claude.json, .claude-plugin, shallow skills/<name>
            if _allowed_fragment(dl, allow):
                continue
            structural.append(("PRIVATE-PATH", m.group(0)))     # the full home-anchored path

    # An `associative` token is a real proper noun with legitimate public uses; it is only a
    # disclosure when it sits next to something else private. So it needs company in the same
    # chunk before it gates. Note the honest limitation, which is documented rather than papered
    # over: in the staged and range domains a "chunk" is ONE LINE, because that is how those
    # scanners feed text in, so co-occurrence there is line-local and this class will under-fire.
    # It reports a WARN in that case rather than nothing, so the miss is visible instead of silent.
    company = bool(structural) or any(t.kind != "associative" for t in deny_hits)

    for tok in deny_hits:
        sev = severity_for(tok.kind, domain)
        if tok.kind == "associative" and not company:
            sev = "WARN"
        g = pol.grant_for(tok.value, domain)
        if g is not None and g.scope == "all":
            sev = "WARN"
        elif g is not None and g.scope == "history-only" and domain == "history":
            sev = "WARN"
        label = "PRIVATE-DENYLIST" if tok.source == "denylist" else "CROSS-REPO"
        if tok.kind != "secret":
            label = "%s/%s" % (label, tok.kind.upper())
        shown = tok.value if not tok.witness else "%s (from %s)" % (tok.value, tok.witness)
        out.append((where, label, shown, sev))

    for label, value in structural:
        out.append((where, label, value, "BLOCK"))


def tracked_files(root):
    """Every git-tracked path. Raises GitError if git cannot enumerate them (see _run).

    Why -z: `git ls-files` without it renders any path containing a non-ASCII byte as a
    C-quoted escape string (quotes included, e.g. "ä¸­...md"). Those strings are
    not paths. They do not open, and every regex anchored on a real suffix misses them.
    Callers read this list as an ANSWER, so such a file got counted in the tracked total and
    then silently excluded from every per-file match. Measured 2026-08-19: a tracked
    metrics/<CJK>-live-runs.jsonl produced "clean (... 3 tracked files carry no real-run
    shape)" with rc=0, while byte-identical content under an ASCII name produced rc=1.
    -z makes git emit raw bytes with NUL separators, so the name round-trips.
    Note the previous body also .strip()ed each entry, which would have corrupted any path
    that legitimately begins or ends with whitespace. With -z the separator is unambiguous,
    so nothing needs trimming.
    """
    return [p for p in _run(["git", "ls-files", "-z"], root).split("\0") if p]


_NUL = bytes([0])
_BOM_LE = bytes([0xFF, 0xFE])
_BOM_BE = bytes([0xFE, 0xFF])


def _decode_best(data):
    """(text, encoding) for scanning purposes, or (None, None) if it is genuinely binary.

    A tracked file that is not valid UTF-8 used to be recorded as unreadable and then skipped,
    while the summary still said `clean`. But "not UTF-8" is not "not text": a file saved by a
    Windows editor as UTF-16 or in a legacy code page is perfectly readable prose, it is pushed to
    GitHub like anything else, and a mailbox inside it is exactly as public. Measured 2026-08-20:
    a UTF-16 file was invisible in every domain at once -- the tree skipped it on a decode error
    and git marks it binary in diffs, so staged and range saw nothing either.

    UTF-16 is detected by BOM or by the NUL density that interleaved ASCII produces; cp1252 is the
    last resort because it decodes almost anything, so it is tried only after the others fail.
    """
    if not data:
        return "", "empty"
    if data[:2] in (_BOM_LE, _BOM_BE) or data.count(_NUL) > len(data) // 8:
        for enc in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                text = data.decode(enc)
            except (UnicodeDecodeError, ValueError):
                continue
            if _looks_like_text(text):
                return text, enc
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    if _NUL in data:
        return None, None                 # embedded NULs and not UTF-16: a binary file
    try:
        text = data.decode("cp1252")
    except UnicodeDecodeError:
        return None, None
    return (text, "cp1252") if _looks_like_text(text) else (None, None)


def _looks_like_text(text):
    """Guard against a decoder that succeeds on anything.

    UTF-16 and cp1252 will both happily turn arbitrary bytes into a string. Without this, a PNG
    header came back as `utf-16` and got scanned as garbage -- harmless in itself, but it meant the
    run counted a binary file as EXAMINED, which is the opposite of the property this whole change
    is for. Something that decodes to control characters is not text and must be reported as
    unread, not quietly counted as read.
    """
    if not text:
        return True
    sample = text[:4096]
    # C0 control characters are the sharp signal. Real prose in any encoding contains tab, carriage
    # return and newline and essentially nothing else below 0x20; a file that does is a decoder
    # succeeding on bytes that were never text. A plain printable-ratio threshold was not enough:
    # a repeated PNG header decodes under cp1252 to 7 printable characters out of every 8, which
    # clears any reasonable ratio while being unambiguously binary.
    ctrl = sum(1 for ch in sample if (ord(ch) < 32 and ch not in "\t\r\n") or ord(ch) == 127)
    if ctrl > max(1, len(sample) // 100):
        return False
    good = sum(1 for ch in sample if ch.isprintable() or ch in "\t\r\n")
    return good >= len(sample) * 0.85


def scan_tree(root, allow, pol, files=None, stats=None):
    """Scan the tracked working tree.

    `stats` (optional dict) is filled with what was and was not examined. A skipped file is not a
    scanned file, and a report that cannot tell the difference is how "clean" comes to mean
    "nothing happened". The skips themselves are unchanged and still correct -- a PNG has no prose
    to leak -- they are simply no longer invisible.
    """
    out = []
    counts = {"enumerated": 0, "scanned": 0, "skipped_dir": 0, "skipped_binary_ext": 0,
              "unreadable": [], "recoded": []}
    for rel in (tracked_files(root) if files is None else files):
        rel = rel.strip()
        if not rel:
            continue
        counts["enumerated"] += 1
        if any(part in SKIP_DIR for part in rel.split("/")):
            counts["skipped_dir"] += 1
            continue
        if os.path.splitext(rel)[1].lower() in BINARY_EXT:
            counts["skipped_binary_ext"] += 1
            continue
        path = os.path.join(root, rel)
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as e:
            counts["unreadable"].append((rel, type(e).__name__))
            continue
        text, enc = _decode_best(raw)
        if text is None:
            counts["unreadable"].append((rel, "binary"))
            continue
        if enc not in ("utf-8", "empty"):
            counts["recoded"].append((rel, enc))
        counts["scanned"] += 1
        deny_only = is_scanner_path(rel) or is_scanner_content(rel, text)
        # THE PATH ITSELF. Only file CONTENT was ever scanned, so a real name, a real address or a
        # real account in a FILE OR DIRECTORY NAME was invisible in the tree domain entirely -- and
        # a filename is as public as the bytes inside it.
        scan_text(rel, "%s (path)" % rel, allow, pol, out, domain="tree")
        lines = text.splitlines(True)
        for i, line in enumerate(lines, 1):
            scan_text(line, "%s:%d" % (rel, i), allow, pol, out,
                      domain="tree", deny_only=deny_only)
    if stats is not None:
        stats.update(counts)
    return out


def _run_stdin(args, cwd, payload):
    """Like _run, but feeds stdin and returns BYTES. Blobs are not necessarily text."""
    try:
        p = subprocess.run(args, cwd=cwd, input=payload.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise GitError("cannot execute `%s` in %s: %s" % (" ".join(args), cwd, e)) from None
    if p.returncode != 0:
        raise GitError("`%s` exited %d in %s\n  %s"
                       % (" ".join(args), p.returncode, cwd,
                          (p.stderr or b"").decode("utf-8", "replace").strip()))
    return p.stdout


# A blob larger than this is enumerated but not scanned, and the skip is COUNTED and PRINTED. The
# cap exists because a repo can hold a very large artifact and regexing it would turn a pre-push
# hook into a hang, which is its own way of getting bypassed. A SILENT cap would be a hole with a
# performance justification attached, so it is never silent.
MAX_BLOB_BYTES = 8 * 1024 * 1024


def _blank_history_stats():
    return {"blobs_total": 0, "blobs_scanned": 0, "blobs_binary": 0, "blobs_recoded": [],
            "blobs_oversize": [], "commits": 0}


def _scan_object_graph(root, allow, pol, out, rev_args, stats, where_prefix):
    """Scan every BLOB reachable in `rev_args`, by walking the object graph.

    WHY NOT `git log -p` -- this is the entire point of the function
    ----------------------------------------------------------------
    The history scan used to read the diff stream. A diff stream is a RENDERING of history, and git
    prints no patch for a merge commit. So a line that first appears in a CONFLICT RESOLUTION,
    differing from both parents, which is exactly what resolving a conflict produces, is not in the
    stream at all. Add a second merge that removes it and it never appears in any ordinary commit's
    diff either.

    Measured 2026-08-20 on a six-commit fixture built that way: the token occurs 0 times in
    `git log --all -p`, once in the object store, and BOTH the old guard and the first version of
    this one printed `clean (tree+history)` with exit 0. The blob is in the repository, it is
    pushed, and GitHub will serve it from a commit URL indefinitely.

    Conflict resolution is not an exotic corner. It is the single most likely moment for a person or
    an agent to paste something in by hand.

    The object graph has no such gap by construction: the scan is defined over the set of objects
    git will actually transmit, rather than over a view of them. It is also FASTER than the diff
    stream (0.245s vs 0.332s on the largest repo in this fleet), because each blob is visited once
    instead of once per commit that touched it.
    """
    named = {}
    listing = _run(["git", "rev-list", "--objects"] + rev_args, root)
    for line in listing.splitlines():
        sha, _, path = line.partition(" ")
        if sha and sha not in named:
            named[sha] = path.strip()
    if not named:
        return

    # --batch-check first, so an enormous blob is never materialised only to be skipped.
    meta = _run_stdin(["git", "cat-file", "--batch-check", "--buffer"], root,
                      "\n".join(named) + "\n").decode("utf-8", "replace")
    wanted = []
    for line in meta.splitlines():
        parts = line.split()
        if len(parts) != 3 or parts[1] != "blob":
            continue
        sha, size = parts[0], int(parts[2])
        path = named.get(sha, "")
        stats["blobs_total"] += 1
        if os.path.splitext(path)[1].lower() in BINARY_EXT:
            continue
        if size > MAX_BLOB_BYTES:
            stats["blobs_oversize"].append((path or sha[:8], size))
            continue
        wanted.append(sha)
    if not wanted:
        return

    raw = _run_stdin(["git", "cat-file", "--batch", "--buffer"], root, "\n".join(wanted) + "\n")
    # `--batch` emits `<sha> <type> <size>\n<size bytes>\n`, repeated. Parsed by LENGTH, never by
    # splitting on newlines: blob content contains newlines, and a parser that guesses where a
    # record ends would resynchronise onto content and silently skip whatever came after it.
    i, n = 0, len(raw)
    while i < n:
        nl = raw.find(b"\n", i)
        if nl < 0:
            break
        header = raw[i:nl].decode("utf-8", "replace").split()
        i = nl + 1
        if len(header) != 3 or header[1] != "blob":
            break
        sha, size = header[0], int(header[2])
        body, i = raw[i:i + size], i + size + 1
        path = named.get(sha) or ("<unnamed blob %s>" % sha[:8])
        text, enc = _decode_best(body)
        if text is None:
            stats["blobs_binary"] += 1
            continue
        if enc not in ("utf-8", "empty"):
            stats["blobs_recoded"].append((path, enc))
        stats["blobs_scanned"] += 1
        # The guard's own files are DENY-ONLY here as in the tree, not skipped: they have to contain
        # the shapes they detect, but the private denylist must still fire on them, or renaming a
        # file would be a hole straight through the gate.
        deny_only = is_scanner_path(path) or is_scanner_content(path, text)
        scan_text(text, "%s%s" % (where_prefix, path), allow, pol, out,
                  domain="history", deny_only=deny_only)


def scan_history(root, allow, pol, stats=None):
    """Every blob, every commit message, every author/committer line reachable from any ref.

    This is the check whose absence let five 'fixed' leaks stay live on GitHub: the tree was clean
    and the commit that introduced the PII was never touched.
    """
    out = []
    if stats is None:
        stats = _blank_history_stats()
    if not _has_commits(root):
        # The one git failure in here that is a STATE, not a breakage. Say it out loud: a repo with
        # no commits gives an empty history scan, and an empty scan must never read as a clean one.
        print("pii_guard: NOTE %s has no commits yet -- the history scan examined nothing." % root,
              file=sys.stderr)
        return out
    for ident in set(_run(["git", "log", "--all", "--format=%ae%n%ce"], root).split()):
        if ident and not ALLOWED_AUTHOR_EMAIL_RE.search(ident):
            out.append(("<commit author/committer>", "AUTHOR-EMAIL", ident, "BLOCK"))
    # Commit MESSAGES: scanned unconditionally. A pathspec would silently drop every commit that
    # touched only excluded files -- and its message with it. (`Co-Authored-By: <real gmail>` is a
    # message-only leak; that is not hypothetical, it happened.)
    msgs = _run(["git", "log", "--all", "--format=%s%n%b"], root)
    stats["commits"] = len(_run(["git", "rev-list", "--all"], root).split())
    if msgs:
        scan_text(msgs, "<commit message>", allow, pol, out, domain="history")
    _scan_object_graph(root, allow, pol, out, ["--all"], stats, "<blob> ")
    return out


def _scan_merge_resolutions(root, allow, pol, out, rev_args, where):
    """Scan what a MERGE COMMIT introduced that came from neither parent.

    The push-range scan reads added lines out of `git log -p`, and git prints no patch for a merge.
    So the one place a person types content by hand during a merge produced a diff of nothing.

    `--cc` is the right tool: a combined diff shows only the lines differing from ALL parents,
    which is the definition of "the resolver wrote this". The prefix is one column per parent, so a
    line the resolution added is a run of '+' as wide as the parent count.

    WHY THIS IS NOT THE OBJECT-GRAPH FIX, which the history domain uses instead: the object graph
    reads whole blobs, and a whole blob contains lines that were already there. In the history
    domain that is right and harmless, because a pre-existing linkage hit lands in the DEBT bucket.
    In the push-range domain it would be a disaster -- editing line 99 of a file whose line 5 has
    long held an accepted token would re-block the push, and blocking somebody for content they did
    not touch is the deadlock this redesign exists to remove. So the range domain stays
    additions-only, and this closes the merge hole without widening the rule.
    """
    shas = [s for s in _run(["git", "rev-list", "--merges"] + rev_args, root).split() if s]
    for sha in shas:
        parents = _run(["git", "rev-list", "--parents", "-n", "1", sha], root).split()
        nparents = max(1, len(parents) - 1)
        text = _run(["git", "show", "--cc", "--text", "--format=%n", sha], root)
        for line in text.splitlines():
            head = line[:nparents]
            if len(head) == nparents and "+" in head and set(head) <= set("+ "):
                scan_text(line[nparents:], where, allow, pol, out, domain="range")


def scan_range(root, allow, pol, rev_range):
    """Scan ONLY the commits about to be published: their diffs, messages and author lines.

    This is what the machine-wide pre-push hook uses, and the scope is the whole point of it. A
    full-history scan is right for a repo you own and have cleaned. It is useless on a FORK of an
    upstream project: thousands of other people's mailboxes sit in that history, the guard would be
    permanently red, and a permanently red guard gets bypassed -- so the one place an agent is most
    likely to publish something (a PR to someone else's project) would end up the least guarded.

    Scanning the push range instead asks the only question that is actually yours to answer: is
    there private data in what YOU are adding?
    """
    out = []
    args = rev_range.split()
    msgs = _run(["git", "log", "--format=%s%n%b"] + args, root)
    if msgs:
        scan_text(msgs, "<commit message (being pushed)>", allow, pol, out, domain="range")
    for ident in set(_run(["git", "log", "--format=%ae%n%ce"] + args, root).split()):
        if ident and not ALLOWED_AUTHOR_EMAIL_RE.search(ident):
            out.append(("<commit author (being pushed)>", "AUTHOR-EMAIL", ident, "BLOCK"))
    diff = _run(["git", "log", "-p", "--text", "--format=%n"] + args + ["--"] + HISTORY_EXCLUDE, root)
    if diff:
        # ADDED lines only, matching scan_staged. Scanning the whole diff text also reads the
        # REMOVED lines, and a removed line is the opposite of a leak: it is the fix.
        #
        # That made a deadlock, hit for real on 2026-08-20. A public repo contained an identifier
        # that had become a denylist token after the fact. Deleting the line was the correct fix,
        # and the commit that deleted it could not be pushed, because its own diff still contained
        # the string on a "-" line. Leaving it was also blocked, since the pre-commit tree scan saw
        # it in the working tree. Every route was closed and the only remaining doors were
        # --no-verify or rewriting history over a one-line edit.
        #
        # History is still scanned in full by scan_history, which is the right place to ask "does
        # this string exist anywhere in the past". This function asks a narrower question: is there
        # private data in what you are ADDING.
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                scan_text(line[1:], "<diff (being pushed)>", allow, pol, out, domain="range")
    # git prints no patch for a merge commit, so everything above sees nothing at all for the one
    # moment a person types content by hand mid-merge. Combined diffs cover exactly that.
    _scan_merge_resolutions(root, allow, pol, out, args, "<merge resolution (being pushed)>")
    return out


def scan_staged(root, allow, pol):
    """Scan only what is staged -- the machine-wide pre-commit gate.

    This is the cheapest possible place to catch a leak, and the only one where the fix is still an
    EDIT. One commit later it is a history rewrite and a force-push; one push later it is public
    forever and everyone who cloned already has it. Every leak in the 2026-07 audit passed through
    this exact point, and there was nothing standing here.

    Breach classes only (strict=False): a consumer mailbox, a real phone, a home ZIP, a private
    token. Not the full synthetic-namespace rule -- this hook runs in every repo on the machine,
    including forks and research code, and a gate that nags there is a gate that gets bypassed.
    """
    out = []
    # --text: a repo can declare `*.md -diff` in .gitattributes, and git then refuses to produce a
    # patch for those files ("Binary files differ"). The content is still committed and still
    # pushed; only the scanner would have gone blind. --text forces the patch.
    diff = _run(["git", "diff", "--cached", "--unified=0", "--text", "--"] + HISTORY_EXCLUDE, root)
    for line in (diff or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            scan_text(line[1:], "<staged>", allow, pol, out, domain="staged")
    return out


def _nonce_for(repo_key, token):
    """A stateless proof that you actually hit this block, in this repo, for this token.

    It is not a secret and it is not access control. Its whole job is to stop an exemption from
    being written for a token nobody ever tripped over -- the difference between "I hit a wall
    and decided to accept it" and "I pre-emptively disabled something I had not seen".
    """
    import hashlib
    h = hashlib.sha256(("%s|%s" % (repo_key, token)).encode("utf-8")).hexdigest()
    return h[:8]


def _token_digest(token):
    """A truncated hash for the audit log. The log must never carry the token in the clear:
    a durable append-only file of real private strings is a PII document with a long life."""
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def do_grant(argv):
    """Write one exemption, with a reason, and leave a trail.

    THE HOOKS NEVER CALL THIS. detect-secrets shipped a hook that auto-updated its baseline and
    the baseline stopped being a record of audited findings and became an automatic amnesty
    machine. A suppression has to be an act someone performs, separately, on purpose.

    There is deliberately NO TTY requirement. Almost every commit on this machine is made by an
    agent through a non-interactive shell, so a TTY gate would set the cost of the compliant
    path to infinity while `--no-verify` stays ten characters -- and the whole reason this exit
    exists is that a gate with no exit gets bypassed. The control is not that an agent cannot
    sign its own slip; it is that the slip is written down where it will be read.

    WHAT THE NONCE IS AND IS NOT. It is sha256(repo|token) truncated, so anyone holding this file
    can compute it without ever running a scan. It is therefore a TYPO BARRIER -- it pins a grant
    to one token in one repo, so a copied command cannot silently exempt the wrong thing -- and it
    is NOT proof that you hit a block. Calling it proof would have been the more comfortable story
    and it would have been false.

    The actual precondition is checked instead of asserted: this command RUNS THE SCAN and refuses
    unless the token really is live in this repo right now. An exemption for a finding that does
    not exist is not an exemption, it is a pre-emptive silence, and it is the shape a stale grant
    file grows by.
    """
    ap = argparse.ArgumentParser(prog="pii_guard.py grant")
    ap.add_argument("--repo", default=".", help="a path inside the repo the grant applies to")
    ap.add_argument("--token", required=True)
    ap.add_argument("--scope", default="history-only", choices=["history-only", "all"])
    ap.add_argument("--exposure", required=True, choices=list(EXPOSURES))
    ap.add_argument("--reason", required=True)
    ap.add_argument("--all-scope-reason", default="")
    ap.add_argument("--nonce", default="")
    a = ap.parse_args(argv)

    root = _repo_root(os.path.abspath(a.repo))
    key, _ = _repo_slug(root)
    if not key:
        print("pii_guard grant: this repo has no origin remote, so there is no owner/name to key\n"
              "  the grant on. Add the remote first.", file=sys.stderr)
        return 2
    token = a.token.strip().lower()
    want = _nonce_for(key, token)
    if a.nonce.strip().lower() != want:
        print("pii_guard grant: --nonce does not match.\n"
              "  Run the scan, hit the block, and copy the nonce it prints for this token. A grant\n"
              "  for a finding nobody has seen is not an exemption, it is a pre-emptive silence.",
              file=sys.stderr)
        return 2
    # PROOF OF BLOCK, by measurement. Scan the repo with the current policy and require this token
    # to actually appear. Cheap (the scan is seconds) and it is the only part of this command that
    # cannot be satisfied by reading the source.
    probe_pol = load_policy(root)
    if not any(t.value == token for t in probe_pol.tokens):
        print("pii_guard grant: %r is not in the policy this machine loads, so it cannot be"
              % token, file=sys.stderr)
        print("  producing a finding anywhere. Nothing to exempt.", file=sys.stderr)
        return 2
    probe_allow = load_repo_allow(root)
    probe = []
    probe += scan_tree(root, probe_allow, probe_pol)
    if _has_commits(root):
        probe += scan_history(root, probe_allow, probe_pol)
    if not any(token in str(val).lower() for _w, _l, val, _s in probe):
        print("pii_guard grant: scanned this repo and %r produces no finding in it." % token,
              file=sys.stderr)
        print("  A grant for something nobody has hit is not an exemption, it is a pre-emptive\n"
              "  silence, and it is how a grant file fills up with entries nobody can justify.",
              file=sys.stderr)
        return 2
    if a.scope == "all" and not a.all_scope_reason.strip():
        print("pii_guard grant: scope=all switches the gate off for LIVE content, not just for\n"
              "  history. It needs --all-scope-reason of its own.", file=sys.stderr)
        return 2

    path = _exempt_path()
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    data = {}
    if os.path.exists(path):
        data = _read_json(path)
        if not isinstance(data, dict):
            print("pii_guard grant: %s is not an object" % path, file=sys.stderr)
            return 2
    entry = {"token": token, "scope": a.scope, "exposure": a.exposure,
             "reason": a.reason.strip(), "granted_utc": _utcnow(), "nonce": want}
    if a.all_scope_reason.strip():
        entry["all_scope_reason"] = a.all_scope_reason.strip()
    data.setdefault(key, []).append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)

    logp = os.path.join(os.path.expanduser("~/.pii-guard"), "grant-log.jsonl")
    with open(logp, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": _utcnow(), "repo": key, "token_sha256_16": _token_digest(token),
                            "scope": a.scope, "exposure": a.exposure,
                            "reason": entry["reason"]}, sort_keys=True) + "\n")
    print("pii_guard: exemption recorded for %s (scope=%s, exposure=%s)" % (key, a.scope, a.exposure))
    print("  file %s" % path)
    print("  log  %s   <- this is where it will be read back" % logp)
    return 0


def _utcnow():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "grant":
        return do_grant(sys.argv[2:])

    ap = argparse.ArgumentParser(description="Structural allowlist PII guard for public repos.")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--tree", action="store_true", help="scan the git-tracked working tree")
    ap.add_argument("--history", action="store_true", help="scan every commit: blobs, messages, authors")
    ap.add_argument("--range", dest="rev_range", default=None,
                    help="scan only the commits in this rev-range (e.g. 'abc..def', or "
                         "'<sha> --not --remotes'). Used by the machine-wide pre-push hook.")
    ap.add_argument("--staged", action="store_true",
                    help="scan only what is staged. Used by the machine-wide pre-commit hook: "
                         "catching it here means the fix is still an EDIT, not a history rewrite.")
    a = ap.parse_args()
    if not (a.tree or a.history or a.rev_range or a.staged):
        a.tree = True

    root = _repo_root(os.path.abspath(a.repo))
    allow = load_repo_allow(root)
    pol = load_policy(root)

    findings = []
    tree_stats, hist_stats = {}, _blank_history_stats()
    if a.tree:
        files = tracked_files(root)
        if not files:
            # A real repo can legitimately track zero files (a fresh `git init`), so this is not an
            # error -- but it is unusual, and it is indistinguishable in the OUTPUT from a scan that
            # was prevented. State it instead of printing "clean".
            print("pii_guard: WARNING %s is a git repo but tracks 0 files -- nothing was examined.\n"
                  "  A clean result here means 'there was nothing to scan', not 'the content is "
                  "clean'." % root, file=sys.stderr)
        findings += scan_tree(root, allow, pol, files=files, stats=tree_stats)
    if a.history:
        findings += scan_history(root, allow, pol, stats=hist_stats)
    if a.rev_range:
        findings += scan_range(root, allow, pol, a.rev_range)
    if a.staged:
        findings += scan_staged(root, allow, pol)

    # WHAT WAS NOT READ. Every one of these used to be either invisible or a line on stderr that
    # the summary then contradicted by saying "clean". They are collected here so the verdict below
    # can refuse the word.
    unexamined = []
    for rel, why in tree_stats.get("unreadable", []):
        unexamined.append(("unreadable", rel, why))
    for path, size in hist_stats.get("blobs_oversize", []):
        unexamined.append(("oversize blob", path, "%d bytes, over the %d cap"
                           % (size, MAX_BLOB_BYTES)))
    if unexamined:
        print("pii_guard: %d item(s) were NOT scanned:" % len(unexamined), file=sys.stderr)
        for kind, what, why in unexamined[:20]:
            print("  %-14s %-46s %s" % (kind, what, why), file=sys.stderr)
    recoded = list(tree_stats.get("recoded", [])) + list(hist_stats.get("blobs_recoded", []))
    if recoded:
        # Not a problem, but not nothing either: it says the repo contains text this guard would
        # have skipped entirely before, which is worth seeing at least once.
        print("pii_guard: %d file(s) were not UTF-8 and were decoded to scan them (%s)"
              % (len(recoded), ", ".join(sorted({e for _p, e in recoded}))), file=sys.stderr)

    # dedupe, keep the first location of each (label, value, severity)
    seen, uniq = set(), []
    for where, label, val, sev in findings:
        k = (label, val.lower(), sev)
        if k not in seen:
            seen.add(k)
            uniq.append((where, label, val, sev))

    blocks = [f for f in uniq if f[3] == "BLOCK"]
    debts = [f for f in uniq if f[3] == "DEBT"]
    warns = [f for f in uniq if f[3] == "WARN"]

    # Loader-level messages go out FIRST and always. A malformed exemption that silently
    # applies to nothing is the failure this replaces.
    vague = vague_allow_entries(allow)
    if vague:
        print("pii_guard: WARNING %d .pii-allow entr(ies) are too generic to be used as a "
              "substring exemption and were IGNORED: %s" % (len(vague), ", ".join(vague)),
              file=sys.stderr)
        print("  An entry like a bare common word is not an exemption, it is an off switch for a "
              "whole class, written inside the repo it protects.", file=sys.stderr)
    for n in pol.notes:
        print(n, file=sys.stderr)
    receipt = pol.receipt()
    if receipt:
        print(receipt, file=sys.stderr)

    # DEBT: a real finding whose harm is not irreversible and whose location is the past. It is
    # counted and printed on every run, and it FORBIDS the word "clean" below, because a summary
    # that says clean while carrying debt is how debt becomes invisible and then permanent.
    for where, label, val, _ in debts:
        print("  HISTORY-DEBT     %-20s %s  [%s]" % (label, val, where), file=sys.stderr)
    for where, label, val, _ in warns:
        print("  WARN             %-20s %s  [%s]" % (label, val, where), file=sys.stderr)

    if not blocks:
        scope = "+".join([s for s, on in (("tree", a.tree), ("history", a.history),
                                          ("push-range", bool(a.rev_range)),
                                          ("staged", a.staged)) if on])
        detail = ""
        if a.tree:
            detail = "  [%d file(s) scanned, %d skipped]" % (
                tree_stats.get("scanned", 0),
                tree_stats.get("enumerated", 0) - tree_stats.get("scanned", 0))
        layer = "" if pol.denylist_present else "  [private denylist: absent, layer not loaded]"
        if a.history:
            detail += "  [%d commit(s), %d blob(s) scanned]" % (hist_stats.get("commits", 0),
                                                                hist_stats.get("blobs_scanned", 0))
        if unexamined:
            # The word `clean` is reserved for a run that read everything it enumerated. This is
            # the whole distinction between "checked and found nothing" and "did not look".
            print("pii_guard: no blocking findings (%s)%s%s -- but %d item(s) above were NOT "
                  "examined, so this is not a clean bill of health."
                  % (scope, detail, layer, len(unexamined)))
            return 0
        if debts or warns:
            print("pii_guard: no blocking findings (%s)%s%s -- but %d HISTORY-DEBT and %d WARN "
                  "above are unresolved and will be reported again."
                  % (scope, detail, layer, len(debts), len(warns)))
        else:
            print("pii_guard: clean (%s)%s%s" % (scope, detail, layer))
        return 0

    print("pii_guard: %d blocking finding(s) -- a real-world identifier is not in the synthetic "
          "namespace\n" % len(blocks), file=sys.stderr)
    key, _ = _repo_slug(root)
    for where, label, val, _ in blocks:
        print("  %-22s %-20s %s" % (label, val, where), file=sys.stderr)
    print("\nFix it, do not silence it. If the identifier is legitimately part of this repo "
          "(a vendor's public address a parser must match), add it to .pii-allow WITH A REASON.",
          file=sys.stderr)
    # Every blocking token gets its exit named, with the exact command. A gate whose escape hatch
    # is undocumented has, in practice, no escape hatch: the reachable alternative is --no-verify,
    # which turns off every check at once and leaves no record.
    tokish = [(label, val) for _, label, val, _ in blocks if "DENYLIST" in label or "CROSS-REPO" in label]
    if tokish and key:
        print("\nIf one of these is a token you have decided to accept rather than remove:",
              file=sys.stderr)
        for label, val in tokish:
            print("  python pii_guard.py grant --token %s --scope history-only \\\n"
                  "      --exposure accepted-public --reason \"...\" --nonce %s"
                  % (val, _nonce_for(key, val)), file=sys.stderr)
    print("\nIf it is real private data and it already reached a commit, rewriting the commit is\n"
          "one option, but know what it does and does not achieve: a force push leaves the old\n"
          "objects reachable by direct commit URL for a long time, refs/pull/* is untouched by it,\n"
          "and forks and existing clones keep their copy. Treat the identifier as disclosed and\n"
          "rotate it where that is possible; rewriting is cleanup, not containment.", file=sys.stderr)
    return 1


def cli():
    """main() with the git-failure exit. Separate exit code so a caller can tell 'this repo has a
    leak' (1) from 'this scan never ran' (2). Every hook and the CI workflow treat any nonzero as a
    block, which is the right default: an unexamined tree is not a clean tree."""
    try:
        return main()
    except PolicyError as e:
        # Exit 2, the same code as an unusable git, and for the same reason: the scan did not
        # really happen. The private layer is the half of this guard that no CI run can
        # reconstruct, so a damaged one is not a degraded scan, it is an absent one.
        print("pii_guard: POLICY UNUSABLE -- the private layer could not be trusted, so this\n"
              "  result is NOT a clean bill of health.\n  %s"
              % str(e).replace("\n", "\n  "), file=sys.stderr)
        return 2
    except GitError as e:
        print("pii_guard: SCAN FAILED -- git could not be used, so NOTHING was examined.\n"
              "  %s\n"
              "  This is not a clean result. Do not treat it as one: fix git (or point --repo at a\n"
              "  real work tree) and re-run. If you are scanning an exported/archived tree, scan the\n"
              "  repository it came from instead -- an export has no history to check."
              % str(e).replace("\n", "\n  "), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(cli())
