#!/usr/bin/env python3
"""pii_guard -- keep real-world identifiers out of a public repo. Structural, allowlist-based.

WHY THIS EXISTS (read before changing it)
-----------------------------------------
These repos are authored by an agent that is simultaneously looking at the operator's real private
data. When it needs an example, the nearest example is that real data. In 2026-07 that produced real
PII in several public repos across a range of categories -- contact details, a home location, an
employer name, a health-provider name, a social handle -- plus the operator's real email stamped on
the author line of nearly every commit. (The categories are named here only to show the guard's
coverage; the specifics belong to the operator and are deliberately kept out of this file.)

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

OPTIONAL PRIVATE LAYER
----------------------
If `~/.pii-denylist.json` exists it is read at runtime for extra literals (the operator's own real
tokens). It never lives in any repo. Absent -> skipped, structural checks still run everywhere (CI,
contributors, other machines).

USAGE
  python pii_guard.py --tree               # fast: git-tracked working tree (pre-commit)
  python pii_guard.py --tree --history     # full: + every blob/message/author in history (pre-push)
  python pii_guard.py --tree --history --repo /path/to/repo
Exit 0 = clean, 1 = leak found (prints file:line and what tripped it).
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
PHONE_RE = re.compile(r"(?<![\w.])(?:\+?1[\s.\-])?\(?([2-9]\d{2})\)?[\s.\-]([2-9]\d{2})[\s.\-](\d{4})(?![\w.])")
# A bare 5-digit number is unusable as a signal (dates, ids, hashes). Only flag a ZIP where the text
# says it is one -- which is the shape a real home ZIP arrives in ("ship to <state> <zip>").
ZIP_RE = re.compile(r"(?:\bZIP\b|\bzip\b|邮编|\bship(?:ping)?\s+to\b|\bdeliver\s+to\b)[^\n]{0,24}?\b([0-9]{5})\b")

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
SCANNER_FILES = {"pii_guard.py", "test_pii_guard.py", ".pii-allow"}
# Same reason, for the history pass: exclude the scanner blobs from the diff scan. Commit MESSAGES
# are scanned separately and unconditionally -- they are not covered by a pathspec.
HISTORY_EXCLUDE = [":(exclude)*pii_guard.py", ":(exclude)*test_pii_guard.py", ":(exclude)*.pii-allow"]
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".ico", ".woff", ".woff2",
              ".sqlite3", ".db", ".bundle", ".pack", ".webp", ".mp4", ".xlsx"}


def _run(args, cwd):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, errors="replace")
    return p.stdout if p.returncode == 0 else ""


def _repo_root(start):
    out = _run(["git", "rev-parse", "--show-toplevel"], start).strip()
    return out or start


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


def load_private_denylist(root=None):
    """Optional extra layer: the operator's own real tokens. Never lives in a repo.

    A few repos publish one of these tokens ON PURPOSE -- an academic homepage exists to show your
    contact address. Blocking edits to that line would be a false alarm on a repo the operator edits
    by hand, and a gate that cries wolf gets --no-verify'd, at which point it guards nothing
    anywhere. So a token can be exempted PER REPO in ~/.pii-guard/denylist-exempt.json:

        { "daizedong/some.github.io": ["<token>"] }   # the homepage's own contact line

    That file lives OUTSIDE every repo, on purpose. An exemption granted from inside a repo would let
    an agent that is leaking into that repo write itself a permission slip in the same commit.
    Structural checks are never exempted -- only these named tokens, only in that one repo.
    """
    toks = []
    for p in (os.environ.get("PII_DENYLIST"), os.path.expanduser("~/.pii-denylist.json")):
        if p and os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                raw = data.get("tokens") if isinstance(data, dict) else data
                toks = [str(t).lower() for t in (raw or []) if str(t).strip()]
            except (OSError, ValueError):
                toks = []
            break
    if not toks or not root:
        return toks
    try:
        with open(os.path.expanduser("~/.pii-guard/denylist-exempt.json"), encoding="utf-8") as f:
            exempt = json.load(f)
    except (OSError, ValueError):
        return toks
    url = _run(["git", "remote", "get-url", "origin"], root).strip().lower().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    parts = [p for p in url.replace(":", "/").split("/") if p]
    key = "/".join(parts[-2:]) if len(parts) >= 2 else ""
    drop = {str(t).lower() for t in (exempt.get(key) or [])}
    return [t for t in toks if t not in drop]


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


def email_ok(addr, allow):
    if addr.lower() in allow:
        return True
    dom = addr.rpartition("@")[2].lower()
    if NOT_A_DOMAIN_RE.match(dom):
        return True                       # a Python decorator, not an address
    return (dom in ALLOWED_EMAIL_DOMAINS
            or dom.endswith(ALLOWED_EMAIL_SUFFIXES)
            or bool(ALLOWED_EMAIL_DOMAIN_RE.match(dom)))


def scan_text(text, where, allow, deny, out, strict=True, deny_only=False):
    """strict=True  (the TREE): full synthetic-namespace allowlist. Nothing real-world-shaped gets in.
    strict=False (HISTORY): only the classes that must NEVER have been committed by anyone, ever.

    The split is deliberate. The allowlist is a HYGIENE rule for new content -- it keeps the fixture
    namespace uniformly fake so a real identifier stands out instead of blending in. Applying it
    retroactively to years of history would light up on harmless old fixtures (`newsletter@medium.com`),
    the hook would be permanently red, and a permanently red hook gets bypassed -- which is the same
    as having no hook. So history is checked for BREACHES: a person's mailbox, a phone, a home ZIP, a
    real author identity, a private token. Those are the things whose presence in an old commit is
    the actual harm.
    """
    low = text.lower()
    for tok in deny:
        if _deny_hit(tok, low):
            out.append((where, "PRIVATE-DENYLIST", tok))
    if deny_only:
        return                            # a scanner file: it must contain the shapes it detects
    for addr in set(EMAIL_RE.findall(text)):
        if addr.lower() in allow:
            continue
        local, _, dom = addr.lower().rpartition("@")
        if dom in PERSONAL_MAIL_DOMAINS and local not in PLACEHOLDER_LOCAL_PARTS:
            out.append((where, "PERSONAL-MAILBOX", addr))       # a real person: never, anywhere
        elif strict and not email_ok(addr, allow):
            out.append((where, "EMAIL", addr))                  # not in the synthetic namespace
    for area, exch, last in set(PHONE_RE.findall(text)):
        num = "%s-%s-%s" % (area, exch, last)
        if ALLOWED_PHONE_555 not in (area, exch) and num.lower() not in allow:
            out.append((where, "PHONE", num))
    for z in set(ZIP_RE.findall(text)):
        if z not in ALLOWED_ZIPS and z not in allow:
            out.append((where, "ZIP", z))


def scan_tree(root, allow, deny):
    out = []
    for rel in _run(["git", "ls-files"], root).splitlines():
        rel = rel.strip()
        if not rel or any(part in SKIP_DIR for part in rel.split("/")):
            continue
        if os.path.splitext(rel)[1].lower() in BINARY_EXT:
            continue
        path = os.path.join(root, rel)
        try:
            with open(path, encoding="utf-8", errors="strict") as f:
                lines = f.readlines()
        except (OSError, UnicodeDecodeError):
            continue                        # binary or unreadable: nothing textual to leak
        deny_only = os.path.basename(rel) in SCANNER_FILES
        for i, line in enumerate(lines, 1):
            scan_text(line, "%s:%d" % (rel, i), allow, deny, out, deny_only=deny_only)
    return out


def scan_history(root, allow, deny):
    """Every blob, every commit message, every author/committer line reachable from any ref.

    This is the check whose absence let five 'fixed' leaks stay live on GitHub: the tree was clean
    and the commit that introduced the PII was never touched.
    """
    out = []
    for ident in set(_run(["git", "log", "--all", "--format=%ae%n%ce"], root).split()):
        if ident and not ALLOWED_AUTHOR_EMAIL_RE.search(ident):
            out.append(("<commit author/committer>", "AUTHOR-EMAIL", ident))
    # Commit MESSAGES: scanned unconditionally. A pathspec would silently drop every commit that
    # touched only excluded files -- and its message with it. (`Co-Authored-By: <real gmail>` is a
    # message-only leak; that is not hypothetical, it happened.)
    msgs = _run(["git", "log", "--all", "--format=%s%n%b"], root)
    if msgs:
        scan_text(msgs, "<commit message>", allow, deny, out, strict=False)
    # BLOBS: every diff in history, minus the scanner files (which must contain the shapes they detect).
    blob = _run(["git", "log", "--all", "-p", "--format=%n", "--"] + HISTORY_EXCLUDE, root)
    if blob:
        scan_text(blob, "<git history>", allow, deny, out, strict=False)
    return out


def scan_range(root, allow, deny, rev_range):
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
        scan_text(msgs, "<commit message (being pushed)>", allow, deny, out, strict=False)
    for ident in set(_run(["git", "log", "--format=%ae%n%ce"] + args, root).split()):
        if ident and not ALLOWED_AUTHOR_EMAIL_RE.search(ident):
            out.append(("<commit author (being pushed)>", "AUTHOR-EMAIL", ident))
    diff = _run(["git", "log", "-p", "--format=%n"] + args + ["--"] + HISTORY_EXCLUDE, root)
    if diff:
        scan_text(diff, "<diff (being pushed)>", allow, deny, out, strict=False)
    return out


def scan_staged(root, allow, deny):
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
    diff = _run(["git", "diff", "--cached", "--unified=0", "--"] + HISTORY_EXCLUDE, root)
    for line in (diff or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            scan_text(line[1:], "<staged>", allow, deny, out, strict=False)
    return out


def main():
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
    allow, deny = load_repo_allow(root), load_private_denylist(root)

    findings = []
    if a.tree:
        findings += scan_tree(root, allow, deny)
    if a.history:
        findings += scan_history(root, allow, deny)
    if a.rev_range:
        findings += scan_range(root, allow, deny, a.rev_range)
    if a.staged:
        findings += scan_staged(root, allow, deny)

    if not findings:
        scope = "+".join([s for s, on in (("tree", a.tree), ("history", a.history),
                                          ("push-range", bool(a.rev_range))) if on])
        print("pii_guard: clean (%s)%s" % (scope, "" if deny else "  [no private denylist loaded]"))
        return 0

    # dedupe, keep first location of each (kind, value)
    seen, uniq = set(), []
    for where, kind, val in findings:
        k = (kind, val.lower())
        if k not in seen:
            seen.add(k)
            uniq.append((where, kind, val))

    print("pii_guard: %d finding(s) -- a real-world identifier is not in the synthetic namespace\n"
          % len(uniq), file=sys.stderr)
    for where, kind, val in uniq:
        print("  %-16s %-20s %s" % (kind, val, where), file=sys.stderr)
    print("\nFix it, do not silence it. If the identifier is legitimately part of this repo "
          "(a vendor's public address a parser must match), add it to .pii-allow WITH A REASON.\n"
          "If it is real private data and it already reached a commit, the COMMIT must be rewritten "
          "(git filter-repo) -- editing the file leaves the leak live in history.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
