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
import os
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
