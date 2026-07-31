#!/usr/bin/env python3
"""Tests for pii_guard.

The acceptance criterion is not "does it pass on clean input". It is: **would it have caught every
leak that actually reached a public repo on 2026-07-13?** Each one is a regression test below,
reconstructed from the real artifact -- but written with SYNTHETIC values.

That substitution is not a compromise, it is the proof: the guard is structural. It does not know
the operator's phone number, it knows the shape of a phone number that is not 555. So a fake number
of the same shape exercises exactly the same code path, and this test file -- unlike the denylist it
replaces -- carries no PII and is safe to vendor into every public repo. A test suite that had to
embed the real leaks to test for them would just be the leak again, one directory over.

The one thing that CANNOT be structural is a proper noun nobody anticipated -- an ordinary word
that happens to be a private name in this operator's life. That is what the optional private layer
is for, and it is tested through the mechanism, never through its contents.

Run: python -m pytest test_pii_guard.py -q
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pii_guard as g  # noqa: E402


def scan(text, allow=(), deny=(), strict=True):
    out = []
    g.scan_text(text, "x", set(allow), list(deny), out, strict=strict)
    return [(k, v) for _, k, v in out]


def kinds(text, **kw):
    return {k for k, _ in scan(text, **kw)}


# ---------------------------------------------------------------- the 2026-07-13 leaks, by shape
# Every shape below reached a PUBLIC repo, and every one was "fixed" by editing the file -- leaving
# the commit that introduced it live on GitHub. These are the cases this guard exists for.

def test_catches_a_real_phone_used_as_a_redaction_fixture():
    """demand-mining: a redact() test used the operator's OWN phone as the 'sensitive input'."""
    leak = 'r = redact("ping me at jane.doe@acme.io or +1 (212) 867-5309 please")'
    assert ("PHONE", "212-867-5309") in scan(leak)


def test_catches_a_real_home_zip_in_a_scenario_fixture():
    """shopping-aggregator: 'ship to NJ <home ZIP>' in a public scenario fixture."""
    assert ("ZIP", "07030") in scan('"buy_intent": "headphones, ship to NJ 07030, budget ~$350"')


def test_catches_a_zip_in_every_phrasing_that_actually_appeared():
    for s in ["K-beauty -> ZIP 07030", "ship to 07030", "shipping to 07030", "deliver to 07030"]:
        assert "ZIP" in kinds(s), s


def test_catches_a_real_mailbox_in_a_config_committed_to_the_repo():
    """small-cap-deepdive: SEC EDGAR demands a contact email in the User-Agent, and the in-repo
    default config was committed with the operator's real one in it."""
    leak = '{"sec_user_agent": "small-cap-deepdive research realperson@gmail.com"}'
    assert ("PERSONAL-MAILBOX", "realperson@gmail.com") in scan(leak)


def test_catches_a_real_mailbox_in_a_commit_message_trailer():
    """Commit MESSAGES leak too -- a tree-only scanner never looks here."""
    assert ("PERSONAL-MAILBOX", "realperson@gmail.com") in scan(
        "Co-Authored-By: A Person <realperson@gmail.com>")


def test_catches_a_real_account_handle():
    """A live-run metric recorded a real social-account handle the skill posts from."""
    assert ("EMAIL", "realhandle@mastodon.social") in scan(
        "account_verify_credentials confirms realhandle@mastodon.social")


# ---------------------------------------------------------------- tree-strict vs history-breach
# The hook checks the tree strictly and history for breaches only. Get this split wrong in either
# direction and the guard fails: too loose on the tree and leaks blend into the fixtures; too strict
# on history and the hook is permanently red on harmless old fixtures -- so it gets bypassed, which
# is the same as not having it.

@pytest.mark.parametrize("dom", ["gmail.com", "outlook.com", "qq.com", "proton.me", "yahoo.com"])
def test_a_named_mailbox_at_a_consumer_provider_is_a_breach_even_in_old_history(dom):
    """A NAMED mailbox at a consumer provider is a PERSON. Never fixture data, never grandfathered."""
    assert "PERSONAL-MAILBOX" in kinds("contact john.smith@%s" % dom, strict=False)


@pytest.mark.parametrize("addr", ["x@gmail.com", "user1@gmail.com", "you@outlook.com"])
def test_a_blank_at_a_consumer_provider_is_not_a_person(addr):
    """Docs legitimately write `--user x@gmail.com`: the PROVIDER is the point, the mailbox is a
    blank. Flagging these would have forced a pointless history rewrite of two usage examples --
    and every needless rewrite spends credibility the next real one needs."""
    assert "PERSONAL-MAILBOX" not in kinds("run --user %s" % addr, strict=False)


def test_the_blank_list_cannot_swallow_a_real_name():
    """The escape hatch must stay narrow: every placeholder accepted is a hole a real address could
    hide in. A name-shaped mailbox must never pass as a blank."""
    for real in ("firstname.lastname@gmail.com", "jsmith2019@gmail.com", "realname@qq.com"):
        assert "PERSONAL-MAILBOX" in kinds(real, strict=False), real


def test_history_does_not_relitigate_harmless_old_fixture_domains():
    """`newsletter@medium.com` in a years-old golden fixture is not a breach. Flagging it forever
    would make the pre-push hook permanently red -- and a permanently red hook gets bypassed."""
    assert not kinds("newsletter@medium.com calendar@zoom.us", strict=False)


def test_but_the_tree_still_holds_those_to_the_synthetic_namespace():
    """In new content the rule stays absolute, so a real identifier cannot hide among the fixtures."""
    assert "EMAIL" in kinds("newsletter@medium.com", strict=True)


@pytest.mark.parametrize("txt,kind", [("+1 (212) 867-5309", "PHONE"),
                                      ("ship to NJ 07030", "ZIP")])
def test_phone_and_zip_are_breaches_in_history_too(txt, kind):
    assert kind in kinds(txt, strict=False)


def test_private_denylist_catches_a_vendor_no_structural_rule_could_predict():
    """A private proper noun -- a person and an organization -- can be ordinary English words. NO
    allowlist can know they are sensitive; that is the one job of the optional private layer, which
    lives outside every repo so the denylist itself never becomes the leak."""
    found = scan("[ACTION] Jane Roe (VendorCo): getting ready for your session",
                 deny=["jane roe", "vendorco"])
    assert {v for k, v in found if k == "PRIVATE-DENYLIST"} == {"jane roe", "vendorco"}


def test_a_denylisted_first_name_does_not_match_inside_an_ordinary_word():
    """A short given name is a substring of ordinary English. A denylisted name matched inside a CSS
    colour keyword in a minified JS bundle and turned a personal homepage red. False positives are
    not a nuisance here -- they are how a gate dies: it cries wolf on something harmless, someone
    reaches for --no-verify, and from then on it guards nothing. Alphabetic tokens are word-bounded;
    the real name is still caught."""
    assert not kinds("border:1px solid primrose; color:rosewood", deny=["rose"])
    assert "PRIVATE-DENYLIST" in kinds("meeting with Rose on Friday", deny=["rose"])


def test_a_digit_bearing_token_stays_a_raw_substring():
    """Phones/ZIPs/account slugs sit flush against punctuation (`"ship to 07030","x"`); a word
    boundary there would only cause misses."""
    assert "PRIVATE-DENYLIST" in kinds('detail":"ship to 07030","x"', deny=["07030"])


def test_pii_allow_cannot_silence_the_private_denylist():
    """The escape hatch exists for third-party CORPORATE identifiers. If it could also suppress the
    operator's OWN tokens, then appending their phone number to .pii-allow would be a one-line way to
    reopen the exact hole this whole thing exists to close. The denylist runs first and ignores
    .pii-allow entirely."""
    found = scan("call 201-555-0100 about jane roe", allow=["jane roe", "201-555-0100"],
                 deny=["jane roe"])
    assert ("PRIVATE-DENYLIST", "jane roe") in found


def test_author_email_rule_rejects_any_real_mailbox_and_accepts_noreply():
    """The deepest leak: the real Gmail was stamped on the AUTHOR line of ~every commit of 13 public
    repos. No file scan of any kind would ever have seen it."""
    ok = g.ALLOWED_AUTHOR_EMAIL_RE
    for real in ("realperson@gmail.com", "alt.account@gmail.com", "dev.alias@gmail.com",
                 "some-skill@local", "person@company.com"):
        assert not ok.search(real), real
    for good in ("12345678+Handle@users.noreply.github.com", "Handle@users.noreply.github.com",
                 "noreply@github.com"):
        assert ok.search(good), good


# ---------------------------------------------------------------- the allowlist must not overreach
# A guard that cries wolf on synthetic fixtures gets bypassed with --no-verify, and then it guards
# nothing. False positives are a security failure here, not a nuisance.

@pytest.mark.parametrize("addr", [
    "user1@example.com", "you@example.org", "jane.doe@acme.io",
    "recruiter@example-employer.com",             # the multi-distinct-sender fixture convention
    "leasing@example-property.com",
    "FAKE_REDTEAM_DB_CANARY_PASS@db.internal",    # a deliberate red-team canary
    "noreply@anthropic.com",                      # generated commit trailer
])
def test_synthetic_namespace_is_not_flagged(addr):
    assert "EMAIL" not in kinds("contact %s ok" % addr)


@pytest.mark.parametrize("num", ["+1 (555) 867-5309", "555-867-5309", "201-555-0100"])
def test_555_is_accepted_in_either_position(num):
    """Fixtures write 555 as the AREA code; others write it as the exchange. An early version of
    this guard only checked the exchange -- and flagged its own scrubbed fixture as a leak."""
    assert "PHONE" not in kinds("call %s" % num)


def test_python_decorators_are_not_email_addresses():
    """`git log -p` is full of `+@pytest.mark.xfail`, which the email regex happily matches."""
    assert "EMAIL" not in kinds("+@pytest.mark.parametrize(...)\n-@pytest.fixture\nn@pytest.mark.skip")


def test_a_bare_five_digit_number_is_not_a_zip():
    """Dates, ids, build numbers, hashes. Flag a ZIP only where the text says it is one -- otherwise
    the guard drowns in noise and gets switched off, which is the same as not having it."""
    assert "ZIP" not in kinds("order 07030 processed; build 12345; sha 90210")


def test_allowed_zip_placeholders_pass():
    assert "ZIP" not in kinds("ship to NY 10001")


def test_repo_allow_file_permits_a_justified_real_vendor_address():
    """A vendor's real public sender address IS the legitimate content of a parser fixture. It goes
    in .pii-allow WITH A REASON -- an allowlist entry that shows up in the diff and has to be argued
    for, which is the opposite of quietly widening a regex."""
    assert "EMAIL" in kinds("from CARFAX@event.carfax.com")
    assert "EMAIL" not in kinds("from CARFAX@event.carfax.com", allow=["carfax@event.carfax.com"])


# ---------------------------------------------------------------- the structural claim itself

def test_the_guard_and_its_tests_contain_no_private_data():
    """The whole argument for allowlist-over-denylist: a denylist of real identifiers IS a PII
    document, so vendoring it into a public repo is itself the leak. Checked against the operator's
    real list at runtime -- which lives outside every repo, so this test hardcodes nothing."""
    deny = g.load_private_denylist()
    if not deny:
        pytest.skip("no private denylist on this machine (expected in CI / for contributors)")
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("pii_guard.py", "test_pii_guard.py"):
        src = open(os.path.join(here, name), encoding="utf-8").read().lower()
        hits = [t for t in deny if t in src]
        assert not hits, "%s contains real private identifier(s): %s" % (name, hits)


def test_the_scanner_file_exemption_is_deny_only_not_skip_all():
    """The guard's own files are exempt from the STRUCTURAL checks -- they have to contain a
    real-looking phone number to prove a real-looking phone number is caught. But if the exemption
    skipped everything, `git mv secrets.txt tools/test_pii_guard.py` would be a hole straight
    through the gate. The private denylist must still fire."""
    out = []
    g.scan_text("call 212-867-5309 about jane roe", "tools/test_pii_guard.py",
                set(), ["jane roe"], out, deny_only=True)
    found = {k for _, k, _ in out}
    assert found == {"PRIVATE-DENYLIST"}, found     # denylist fires; structural checks do not


def test_structural_checks_still_run_without_the_private_denylist():
    """CI and other contributors have no such file. The guard must not quietly become a no-op."""
    out = []
    g.scan_text("ship to NJ 07030", "x", set(), [], out)      # empty denylist
    assert ("x", "ZIP", "07030") in out


# ---------------------------------------------------------------- machine paths (the 2026-07 gap)
# The class the audit found leaking MOST and the guard had NO detector for: the operator's real home
# directory baked into a public tool's CODE. `~/.claude/scripts/<script>` and `C:\Users\<name>\...`
# reached the tree AND history of public repos and sailed straight through the gate.

@pytest.mark.parametrize("path", [
    r"C:\Users\janedoe\Desktop\notes.txt",
    "/home/janedoe/.bashrc",
    "/Users/janedoe/Library/x",
])
def test_catches_a_real_username_home_path(path):
    assert "USER-PATH" in kinds(path)
    assert "USER-PATH" in kinds(path, strict=False)          # a breach: enforced in history too


@pytest.mark.parametrize("path", [
    "/home/runner/work/repo",             # CI runner
    r"C:\Users\Public\Desktop",           # standard Windows account
    r"C:\Users\Administrator\x",
    "/Users/shared/x",
    "/home/user/x", r"C:\Users\you\x",    # placeholders
])
def test_generic_and_placeholder_usernames_pass(path):
    assert "USER-PATH" not in kinds(path)


@pytest.mark.parametrize("path", [
    "_RUNNER = os.path.expanduser(r'~/.claude/scripts/agent.ps1')",   # the exact llmcall leak shape
    'relay = os.path.expanduser("~/.claude/scripts/notify.py")',
    'relay = "~/.claude/skills/other-tool/scripts/relay.py"',        # deep cross-tool path (llmcall leaked this)
    "reads ~/.secrets/token.cred",
    r"$HOME/.agent-center/state",
    r"%USERPROFILE%\.pw-auth\sephora.json",
    r'-File "$env:USERPROFILE\.claude\scripts\runner.ps1"',   # the PowerShell wrapper form ($env: anchor)
])
def test_catches_a_private_tool_home_path(path):
    assert "PRIVATE-PATH" in kinds(path)
    assert "PRIVATE-PATH" in kinds(path, strict=False)              # breach: history too


@pytest.mark.parametrize("path", [
    "~/.claude/skills/my-skill",   # a skill's OWN documented install location (public convention)
    "~/.claude/plugins/some-plugin",
    "junctions into ~/.claude/skills",
    "~/.claude.json",              # the Claude Code config FILE -- a public convention, not a private dir
    ".claude.json in .gitignore",  # a bare gitignore entry has no home anchor
    "the .claude-plugin/plugin.json manifest",
    "config lives in ~/.my-tool-config/data",   # a repo's OWN -config companion (P1.5's job, not this)
    "config in .some-tool-config/",             # bare -config, no anchor
])
def test_public_conventions_and_own_config_are_not_flagged(path):
    assert "PRIVATE-PATH" not in kinds(path)


def test_private_path_is_pii_allow_exemptable():
    """A repo may document its OWN private install path with a written reason (unlike ~/.claude/skills,
    a public convention that needs no entry)."""
    p = "reads ~/.claude/scripts/self.ps1"
    assert "PRIVATE-PATH" in kinds(p)
    assert "PRIVATE-PATH" not in kinds(p, allow=[".claude/scripts/self.ps1"])


@pytest.mark.parametrize("s", [
    "self.claude_client.messages.create()",   # attribute access, not a path
    "obj.codex = 1", "x = a.secrets_manager",
    "~/.config/app/settings", "~/.ssh/id_rsa", "~/.cache/pip",   # generic dotdirs, not private tools
    "the cost/health chain, codex first",     # the word 'codex' in prose, no path
])
def test_no_false_positive_on_attribute_access_or_generic_dotdirs(s):
    assert "PRIVATE-PATH" not in kinds(s)


# ---------------------------------------------------------------- P1.5 cross-repo fleet linkage
def test_cross_repo_tokens_from_visibility(tmp_path, monkeypatch):
    """A public repo naming another PRIVATE repo is the fleet-linkage leak. Built from visibility.json,
    self-excluding the current repo, distinctive slugs only, PRIVATE repos only."""
    vis = tmp_path / "visibility.json"
    # SYNTHETIC repo names -- this file is scanned by the guard, so it must not itself carry a real
    # private slug (that would be the leak, one directory over -- the same argument as the denylist).
    vis.write_text(json.dumps({
        "owner/acme-alpha-config": "PRIVATE",
        "owner/acme-beta-config": "PRIVATE",
        "owner/my-public-tool": "PUBLIC",          # a public repo name is itself public: not a token
        "owner/notes": "PRIVATE",                  # generic word, no separators: excluded
        "owner/data-augmentation": "PRIVATE",      # one hyphen + ordinary ML phrase: excluded (FP risk)
        "owner/self-repo": "PRIVATE",              # the CURRENT repo names itself: excluded
        "owner/self-repo-config": "PRIVATE",       # the current repo's OWN companion: self-reference, excluded
    }), encoding="utf-8")
    monkeypatch.setattr(g, "_run", lambda *a, **k: "git@github.com:owner/self-repo.git\n")
    toks = g.load_cross_repo_tokens(".", vis_path=str(vis))
    assert "acme-alpha-config" in toks and "acme-beta-config" in toks
    assert "my-public-tool" not in toks           # public
    assert "notes" not in toks                    # generic single word
    assert "data-augmentation" not in toks        # one-hyphen common term: would false-positive
    assert "self-repo" not in toks                # the current repo names itself
    assert "self-repo-config" not in toks         # the current repo's OWN companion: not a cross-repo leak


def test_cross_repo_token_is_caught_as_a_finding():
    """The private repo NAME appearing in another public repo's text is a finding."""
    assert "PRIVATE-DENYLIST" in kinds("depends on acme-alpha-config for the keys",
                                       deny=["acme-alpha-config"])


def test_cross_repo_absent_visibility_degrades_to_empty(tmp_path):
    """CI / a contributor's checkout has no visibility.json: the layer is empty, not an error."""
    assert g.load_cross_repo_tokens(".", vis_path=str(tmp_path / "no-such-visibility.json")) == []


# ---------------------------------------------------------------- the enumeration fail-open
# Until 2026-07-30 `_run` returned "" whenever git exited nonzero, and every caller read that as an
# ANSWER rather than as a failure: no tracked files, no history, no diff. scan_tree's loop then ran
# zero times and main() printed "pii_guard: clean (tree)" and exited 0 having opened no file at all.
# A directory that is not a repo, an extracted git-archive, git absent from PATH, an index.lock and
# a permission error all produced that identical green result -- including in the CI workflow, whose
# entire job is running this command on 18 public repos where it is the authority. A verifier hit it
# for real. These tests fail if that behaviour ever comes back.

def _guard_run(args, cwd, env_overrides=None):
    """Invoke the scanner the way a hook or CI does: as a process, judged by its exit code."""
    env = dict(os.environ)
    env.update(env_overrides or {})
    return subprocess.run([sys.executable, g.__file__] + args, cwd=str(cwd),
                          capture_output=True, text=True, env=env)


def _inside_a_repo(d):
    return subprocess.run(["git", "-C", str(d), "rev-parse", "--show-toplevel"],
                          capture_output=True).returncode == 0


def test_a_failed_git_call_raises_and_carries_gits_stderr():
    """The contract itself: nonzero exit is an exception, not an empty answer."""
    with pytest.raises(g.GitError) as ei:
        g._run(["git", "definitely-not-a-subcommand"], os.getcwd())
    assert "definitely-not-a-subcommand" in str(ei.value)


def test_allow_fail_returns_none_which_is_not_an_empty_answer():
    """The one legitimate use of a swallowed failure returns None. Empty STDOUT from a SUCCESSFUL
    git call must still be "", or 'no origin' and 'an empty diff' become the same thing."""
    assert g._run(["git", "definitely-not-a-subcommand"], os.getcwd(), allow_fail=True) is None


def test_a_successful_git_call_with_no_output_still_returns_empty_string(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    assert g._run(["git", "ls-files"], str(tmp_path)) == ""      # not None: git worked


def test_missing_git_is_a_failure_not_an_empty_file_list(tmp_path):
    with pytest.raises(g.GitError) as ei:
        g._run(["this-executable-does-not-exist-anywhere"], str(tmp_path))
    assert "cannot execute" in str(ei.value)


def test_tracked_files_raises_in_a_directory_that_is_not_a_repo(tmp_path):
    if _inside_a_repo(tmp_path):
        pytest.skip("temp dir is inside a git repo; the enumeration cannot fail here")
    with pytest.raises(g.GitError):
        g.tracked_files(str(tmp_path))


def test_a_non_repo_directory_exits_nonzero_and_never_prints_clean(tmp_path):
    """THE REGRESSION. Before the fix this exited 0 with 'pii_guard: clean (tree)'."""
    if _inside_a_repo(tmp_path):
        pytest.skip("temp dir is inside a git repo")
    p = _guard_run(["--tree", "--repo", "."], tmp_path)
    assert p.returncode != 0, "a directory with no repo reported success: %r" % p.stdout
    assert "clean" not in p.stdout
    assert "SCAN FAILED" in p.stderr


def test_an_exported_tree_with_no_git_dir_exits_nonzero(tmp_path):
    """A git-archive extraction: real content, real PII risk, no .git. It must refuse to grade it."""
    if _inside_a_repo(tmp_path):
        pytest.skip("temp dir is inside a git repo")
    (tmp_path / "README.md").write_text("exported content\n", encoding="utf-8")
    p = _guard_run(["--tree", "--repo", "."], tmp_path)
    assert p.returncode != 0 and "clean" not in p.stdout


def test_git_missing_from_path_exits_nonzero_with_a_readable_message(tmp_path):
    """Not a traceback and never a clean report. PATH is emptied; python is invoked absolutely."""
    empty = tmp_path / "nothing-on-path"
    empty.mkdir()
    p = _guard_run(["--tree", "--repo", "."], tmp_path,
                   {"PATH": str(empty), "GIT_EXEC_PATH": str(empty)})
    assert p.returncode != 0 and "clean" not in p.stdout
    assert "SCAN FAILED" in p.stderr and "Traceback" not in p.stderr


def test_a_repo_tracking_zero_files_says_so_instead_of_printing_only_clean(tmp_path):
    """Zero tracked files in a REAL repo is legitimate, so it stays exit 0 -- but it must not be
    reported in the same words as a scan that actually read something."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    p = _guard_run(["--tree", "--repo", "."], tmp_path)
    assert p.returncode == 0
    assert "tracks 0 files" in p.stderr
    assert "0 file(s) scanned" in p.stdout


def test_a_clean_report_states_how_much_was_examined(tmp_path):
    """'clean' with no count is the string that hid the fail-open for months."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "a.md").write_text("nothing private here\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.md"], check=True, capture_output=True)
    p = _guard_run(["--tree", "--repo", "."], tmp_path)
    assert p.returncode == 0 and "1 file(s) scanned" in p.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
