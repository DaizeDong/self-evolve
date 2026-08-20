#!/usr/bin/env python3
# pii-guard:scanner-file -- this file must contain the shapes it detects; see SCANNER_MARKER
"""Tests for the v2 policy layer: token kinds, the jurisdiction matrix, derivability,
loader self-attestation, and the exemption exit.

READ THIS BEFORE ADDING A TEST HERE
-----------------------------------
Nearly every assertion below has a TWIN pointing the other way, and the twin is the point.
A test that only checks "the loader raises on a damaged file" is passed by a loader that
raises on everything; a test that only checks "linkage does not gate in history" is passed by
a guard that has stopped gating. So each relaxation is paired with the case that must still
block, and each fail-closed assertion is paired with a healthy input that must still pass.

Every identifier here is synthetic.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pii_guard as g  # noqa: E402


# ------------------------------------------------------------------ helpers
def write_denylist(tmp_path, tokens, fmt=2, count=None, canary=g.CANARY_TOKEN, extra=None):
    """A v2 denylist file. `tokens` is a list of (value, kind) or plain strings."""
    items = []
    for t in tokens:
        if isinstance(t, tuple):
            items.append({"value": t[0], "kind": t[1]})
        else:
            items.append({"value": t, "kind": "secret"})
    if canary and not any(i["value"] == canary for i in items):
        items.append({"value": canary, "kind": "secret"})
    doc = {"tokens": items}
    if fmt is not None:
        doc["format"] = fmt
    if canary:
        doc["canary"] = canary
    doc["count"] = len(items) if count is None else count
    if extra:
        doc.update(extra)
    # NOT named denylist.json: an assertion that looks for the word "denylist" in an error
    # message would then match the PATH in that message and pass no matter what the code did.
    p = tmp_path / "policy-fixture.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


def load(path, monkeypatch, root=None):
    monkeypatch.setenv("PII_DENYLIST", path)
    return g.load_policy(root)


def sev_of(text, pol, domain):
    out = []
    g.scan_text(text, "x", set(), pol, out, domain=domain)
    return {(k, v): s for _, k, v, s in out}


# ================================================================== derivability
def test_a_companion_of_a_PUBLIC_repo_is_derived_and_does_not_gate(tmp_path, monkeypatch):
    """The whole point of the second idea. `example-skill` is public and every public repo in
    this fleet documents the `<skill>-config` convention, so the companion name is something
    any reader can write down unaided. Enforcing it costs history rewrites and buys nothing."""
    vis = tmp_path / "vis.json"
    vis.write_text(json.dumps({
        "owner/example-skill": "PUBLIC",
        "owner/example-skill-config": "PRIVATE",
    }), encoding="utf-8")
    monkeypatch.setattr(g, "_run", lambda *a, **k: "git@github.com:owner/other-repo.git\n")
    toks = g._cross_repo_tokens_typed(".", vis_path=str(vis))
    assert [t.value for t in toks] == ["example-skill-config"]
    assert toks[0].kind == "derived"


def test_a_companion_of_a_PRIVATE_repo_is_linkage_and_still_gates(tmp_path, monkeypatch):
    """The twin. Direction is load-bearing: if the parent is not public, nothing published
    points at this name, so it is not derivable from anything and keeps full force."""
    vis = tmp_path / "vis.json"
    vis.write_text(json.dumps({
        "owner/hidden-venture": "PRIVATE",
        "owner/hidden-venture-config": "PRIVATE",
    }), encoding="utf-8")
    monkeypatch.setattr(g, "_run", lambda *a, **k: "git@github.com:owner/other-repo.git\n")
    toks = g._cross_repo_tokens_typed(".", vis_path=str(vis))
    assert [(t.value, t.kind) for t in toks] == [("hidden-venture-config", "linkage")]


def test_derivability_is_scoped_to_the_SAME_owner(tmp_path, monkeypatch):
    """A public repo under a different owner does not license our private name. The convention
    is per-account; borrowing another account's public name to excuse ours would be a hole."""
    vis = tmp_path / "vis.json"
    vis.write_text(json.dumps({
        "someone-else/example-skill": "PUBLIC",
        "owner/example-skill-config": "PRIVATE",
    }), encoding="utf-8")
    monkeypatch.setattr(g, "_run", lambda *a, **k: "git@github.com:owner/other-repo.git\n")
    toks = g._cross_repo_tokens_typed(".", vis_path=str(vis))
    assert [(t.value, t.kind) for t in toks] == [("example-skill-config", "linkage")]


def test_a_private_repo_with_no_parent_at_all_is_linkage(tmp_path, monkeypatch):
    vis = tmp_path / "vis.json"
    vis.write_text(json.dumps({"owner/quiet-ledger-service": "PRIVATE"}), encoding="utf-8")
    monkeypatch.setattr(g, "_run", lambda *a, **k: "git@github.com:owner/other-repo.git\n")
    toks = g._cross_repo_tokens_typed(".", vis_path=str(vis))
    assert [(t.value, t.kind) for t in toks] == [("quiet-ledger-service", "linkage")]


@pytest.mark.parametrize("suffix", list(g.CONVENTION_SUFFIXES))
def test_every_documented_suffix_derives(suffix, tmp_path, monkeypatch):
    vis = tmp_path / "vis.json"
    vis.write_text(json.dumps({
        "owner/example-skill": "PUBLIC",
        "owner/example-skill%s" % suffix: "PRIVATE",
    }), encoding="utf-8")
    monkeypatch.setattr(g, "_run", lambda *a, **k: "git@github.com:owner/other-repo.git\n")
    toks = g._cross_repo_tokens_typed(".", vis_path=str(vis))
    # some suffixes do not clear the distinctiveness filter on their own; when they are admitted
    # at all, they must be admitted as derived
    for t in toks:
        assert t.kind == "derived", (suffix, t.value, t.kind)


def test_an_undocumented_suffix_does_not_derive(tmp_path, monkeypatch):
    """Only the conventions we actually publish make a name derivable. `-backup` is not one of
    them, so nothing published points from the public name to this one."""
    vis = tmp_path / "vis.json"
    vis.write_text(json.dumps({
        "owner/example-skill": "PUBLIC",
        "owner/example-skill-backup-store": "PRIVATE",
    }), encoding="utf-8")
    monkeypatch.setattr(g, "_run", lambda *a, **k: "git@github.com:owner/other-repo.git\n")
    toks = g._cross_repo_tokens_typed(".", vis_path=str(vis))
    assert [(t.value, t.kind) for t in toks] == [("example-skill-backup-store", "linkage")]


# ================================================================== the jurisdiction matrix
@pytest.mark.parametrize("domain", list(g.DOMAINS))
def test_secret_blocks_in_every_domain(domain):
    assert g.severity_for("secret", domain) == "BLOCK"


@pytest.mark.parametrize("domain", ["tree", "staged", "range"])
def test_linkage_blocks_in_live_domains(domain):
    """The relaxation is ONLY about the past. Adding a linkage token today is still a leak, and
    the fix is still one edit away, which is exactly why it should still be blocked."""
    assert g.severity_for("linkage", domain) == "BLOCK"


def test_linkage_is_debt_in_history_not_a_block():
    assert g.severity_for("linkage", "history") == "DEBT"


@pytest.mark.parametrize("domain", list(g.DOMAINS))
def test_derived_never_blocks_but_is_never_silent(domain):
    assert g.severity_for("derived", domain) == "WARN"


def test_an_unknown_kind_raises_rather_than_defaulting():
    """Defaulting an unknown kind to anything hides a version mismatch. Guessing 'secret' hides
    a guard that is newer than it thinks; guessing weaker hides a real token."""
    with pytest.raises(g.PolicyError):
        g.severity_for("banana", "tree")


def test_end_to_end_severity_of_a_linkage_hit(tmp_path, monkeypatch):
    pol = g.Policy()
    pol.tokens = [g.Token("hidden-venture-config", "linkage", source="cross-repo")]
    live = sev_of("we sync into hidden-venture-config", pol, "tree")
    past = sev_of("we sync into hidden-venture-config", pol, "history")
    assert list(live.values()) == ["BLOCK"]
    assert list(past.values()) == ["DEBT"]


def test_a_secret_hit_is_BLOCK_in_history_too():
    """The twin of the test above. Retroactive relief is a property of the KIND, not a general
    softening of history."""
    pol = g.Policy.of(["zzsecrettokenalpha"])
    past = sev_of("the zzsecrettokenalpha account", pol, "history")
    assert list(past.values()) == ["BLOCK"]


def test_associative_needs_company_to_gate():
    pol = g.Policy()
    pol.tokens = [g.Token("acmecorp", "associative"), g.Token("zzsecrettok", "secret")]
    alone = sev_of("we partnered with AcmeCorp last year", pol, "tree")
    assert alone[("PRIVATE-DENYLIST/ASSOCIATIVE", "acmecorp")] == "WARN"
    together = sev_of("AcmeCorp, see zzsecrettok", pol, "tree")
    assert together[("PRIVATE-DENYLIST/ASSOCIATIVE", "acmecorp")] == "BLOCK"


# ================================================================== loader self-attestation
def test_a_healthy_v2_file_loads_cleanly(tmp_path, monkeypatch):
    """THE NEGATIVE CONTROL FOR EVERY TEST BELOW. Without it, a loader that raised on all input
    would score a perfect fail-closed record."""
    p = write_denylist(tmp_path, [("zztokenone", "secret"), ("zztokentwo", "linkage")])
    pol = load(p, monkeypatch)
    # the canary is NOT among them: it is an attestation that the file arrived intact, not a
    # string to hunt for. Keeping it in the token set would make this very file a finding.
    assert sorted(t.value for t in pol.tokens) == ["zztokenone", "zztokentwo"]
    assert pol.denylist_present is True
    assert {t.kind for t in pol.tokens} == {"secret", "linkage"}


def test_missing_canary_raises(tmp_path, monkeypatch):
    p = write_denylist(tmp_path, ["zztokenone"])
    doc = json.loads(io.open(p, encoding="utf-8").read())
    doc["tokens"] = [t for t in doc["tokens"] if t["value"] != g.CANARY_TOKEN]
    doc["count"] = len(doc["tokens"])
    io.open(p, "w", encoding="utf-8").write(json.dumps(doc))
    with pytest.raises(g.PolicyError):
        load(p, monkeypatch)


def test_count_mismatch_raises(tmp_path, monkeypatch):
    """Deleting entries from a JSON array leaves valid JSON. This assertion is the only thing
    between a half-deleted policy and a green light."""
    p = write_denylist(tmp_path, ["zztokenone", "zztokentwo"], count=99)
    with pytest.raises(g.PolicyError):
        load(p, monkeypatch)


def test_truncated_json_raises(tmp_path, monkeypatch):
    p = write_denylist(tmp_path, ["zztokenone"])
    raw = io.open(p, encoding="utf-8").read()
    io.open(p, "w", encoding="utf-8").write(raw[:len(raw) // 2])
    with pytest.raises(g.PolicyError):
        load(p, monkeypatch)


def test_renamed_tokens_key_raises(tmp_path, monkeypatch):
    p = write_denylist(tmp_path, ["zztokenone"])
    doc = json.loads(io.open(p, encoding="utf-8").read())
    doc["denylist"] = doc.pop("tokens")
    io.open(p, "w", encoding="utf-8").write(json.dumps(doc))
    with pytest.raises(g.PolicyError):
        load(p, monkeypatch)


def test_utf16_encoded_file_raises(tmp_path, monkeypatch):
    p = write_denylist(tmp_path, ["zztokenone"])
    raw = io.open(p, encoding="utf-8").read()
    open(p, "wb").write(raw.encode("utf-16"))
    with pytest.raises(g.PolicyError):
        load(p, monkeypatch)


def test_empty_token_list_raises(tmp_path, monkeypatch):
    """An empty policy file and an absent one are different situations, and only one of them is
    reported honestly by saying nothing."""
    p = str(tmp_path / "empty.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps({"format": 2, "tokens": [], "count": 0}))
    with pytest.raises(g.PolicyError):
        load(p, monkeypatch)


def test_a_future_format_raises_rather_than_silently_hardening(tmp_path, monkeypatch):
    p = write_denylist(tmp_path, ["zztokenone"], fmt=99)
    with pytest.raises(g.PolicyError):
        load(p, monkeypatch)


def test_an_unknown_kind_in_the_file_raises(tmp_path, monkeypatch):
    p = write_denylist(tmp_path, [("zztokenone", "secret")])
    doc = json.loads(io.open(p, encoding="utf-8").read())
    doc["tokens"][0]["kind"] = "totally-unknown"
    io.open(p, "w", encoding="utf-8").write(json.dumps(doc))
    with pytest.raises(g.PolicyError):
        load(p, monkeypatch)


def test_absent_file_is_a_legitimate_state_and_is_announced(tmp_path, monkeypatch):
    """CI has no such file and neither does a contributor. That must PASS, and it must say so:
    the difference between 'checked and clean' and 'this layer was not present' is the whole
    argument of this codebase."""
    monkeypatch.setenv("PII_DENYLIST", str(tmp_path / "nope.json"))
    pol = g.load_policy(None)
    assert pol.tokens == []
    assert pol.denylist_present is False


def test_v1_flat_list_still_loads(tmp_path, monkeypatch):
    """Back-compatibility is not politeness here. 18 repos carry a vendored copy of this file,
    and they are upgraded by a script that someone has to remember to run."""
    p = str(tmp_path / "v1.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps({"tokens": ["zzalpha", "zzbeta"]}))
    pol = load(p, monkeypatch)
    assert sorted(t.value for t in pol.tokens) == ["zzalpha", "zzbeta"]
    assert all(t.kind == "secret" for t in pol.tokens)


def test_v1_bare_array_still_loads(tmp_path, monkeypatch):
    p = str(tmp_path / "v1b.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps(["zzalpha"]))
    pol = load(p, monkeypatch)
    assert [t.value for t in pol.tokens] == ["zzalpha"]


# ================================================================== the matcher probe
def test_a_matcher_that_never_matches_is_caught(monkeypatch):
    """The failure mode this exists for: a comparison that silently answers 'no' to everything
    cannot be detected by observing that it answered 'no'. The machine-wide pre-commit hook
    learned this with its case-folding probe; this is the same move one layer down."""
    monkeypatch.setattr(g, "_deny_hit", lambda tok, low: False)
    with pytest.raises(g.PolicyError):
        g._probe_matcher()


def test_a_matcher_that_always_matches_is_also_caught(monkeypatch):
    monkeypatch.setattr(g, "_deny_hit", lambda tok, low: True)
    with pytest.raises(g.PolicyError):
        g._probe_matcher()


def test_the_real_matcher_passes_its_own_probe():
    g._probe_matcher()          # the negative control: it must not be a permanent alarm


# ================================================================== exemptions and the receipt
def _exempt(tmp_path, monkeypatch, payload):
    home = tmp_path / "home"
    (home / ".pii-guard").mkdir(parents=True)
    (home / ".pii-guard" / "denylist-exempt.json").write_text(json.dumps(payload),
                                                              encoding="utf-8")
    monkeypatch.setattr(g.os.path, "expanduser",
                        lambda p: p.replace("~", str(home)) if p.startswith("~") else p)
    monkeypatch.setattr(g, "_repo_slug", lambda root: ("owner/scanned-repo", "scanned-repo"))
    notes = []
    return g.load_grants(".", notes), notes


def test_a_valid_history_only_grant_is_loaded(tmp_path, monkeypatch):
    grants, notes = _exempt(tmp_path, monkeypatch, {"owner/scanned-repo": [
        {"token": "hidden-venture-config", "scope": "history-only",
         "exposure": "accepted-public", "reason": "written before that repo existed"}]})
    assert len(grants) == 1 and grants[0].scope == "history-only"
    assert notes == []


def test_a_grant_without_an_exposure_is_rejected_and_reported(tmp_path, monkeypatch):
    """Rejected AND reported. A silently dropped grant is the worst outcome: the operator has
    been through the compliant motions and believes the exemption is in place."""
    grants, notes = _exempt(tmp_path, monkeypatch, {"owner/scanned-repo": [
        {"token": "hidden-venture-config", "scope": "history-only", "reason": "because"}]})
    assert grants == []
    assert any("exposure" in n for n in notes)


def test_scope_all_needs_its_own_sentence(tmp_path, monkeypatch):
    grants, notes = _exempt(tmp_path, monkeypatch, {"owner/scanned-repo": [
        {"token": "zztok", "scope": "all", "exposure": "false-positive", "reason": "x"}]})
    assert grants == []
    assert any("all_scope_reason" in n for n in notes)


def test_scope_all_is_accepted_when_justified(tmp_path, monkeypatch):
    grants, _ = _exempt(tmp_path, monkeypatch, {"owner/scanned-repo": [
        {"token": "zztok", "scope": "all", "exposure": "false-positive", "reason": "x",
         "all_scope_reason": "the token is a common English word in this repo"}]})
    assert len(grants) == 1 and grants[0].scope == "all"


def test_a_block_keyed_on_a_bare_repo_name_is_reported_as_inert(tmp_path, monkeypatch):
    """The most likely way to be wrong here, and the one that used to be completely silent: the
    file looks right, applies to nothing, and nothing says so."""
    grants, notes = _exempt(tmp_path, monkeypatch, {"scanned-repo": [
        {"token": "zztok", "scope": "history-only", "exposure": "legacy", "reason": "x"}]})
    assert grants == []
    assert any("owner/name" in n for n in notes)


def test_the_receipt_counts_grants_that_never_fired(tmp_path, monkeypatch):
    grants, _ = _exempt(tmp_path, monkeypatch, {"owner/scanned-repo": [
        {"token": "a-token-nothing-will-hit", "scope": "history-only",
         "exposure": "false-positive", "reason": "x"}]})
    pol = g.Policy()
    pol.grants = grants
    pol.tokens = [g.Token("zzother", "secret")]
    out = []
    g.scan_text("zzother appears here", "x", set(), pol, out, domain="tree")
    r = pol.receipt()
    assert r and "1 declared" in r and "0 matched" in r and "1 never fired" in r


def test_a_history_only_grant_relaxes_history_but_not_the_tree(tmp_path, monkeypatch):
    """The twin that keeps the exit honest. An exemption for the past is not an exemption for
    what you are writing right now."""
    grants, _ = _exempt(tmp_path, monkeypatch, {"owner/scanned-repo": [
        {"token": "zzaccepted", "scope": "history-only", "exposure": "accepted-public",
         "reason": "already disclosed"}]})
    pol = g.Policy()
    pol.grants = grants
    pol.tokens = [g.Token("zzaccepted", "secret")]
    assert list(sev_of("zzaccepted here", pol, "history").values()) == ["WARN"]
    pol2 = g.Policy()
    pol2.grants = list(grants)
    pol2.tokens = [g.Token("zzaccepted", "secret")]
    assert list(sev_of("zzaccepted here", pol2, "tree").values()) == ["BLOCK"]


# ================================================================== the nonce
def test_the_nonce_is_stable_and_repo_scoped():
    a = g._nonce_for("owner/repo-one", "zztok")
    b = g._nonce_for("owner/repo-two", "zztok")
    assert a == g._nonce_for("owner/repo-one", "zztok")     # stateless and reproducible
    assert a != b                                            # a slip for one repo is not a slip
    assert len(a) == 8


def test_the_audit_log_never_carries_the_token_in_the_clear():
    """An append-only log of real private strings is a PII document with a long life. The log
    records a digest so the entry is comparable but not readable."""
    d = g._token_digest("zzsomethingprivate")
    assert "zzsomethingprivate" not in d and len(d) == 16


# ================================================================== gaps found by mutation testing
# Each test below exists because a deliberate break in pii_guard.py SURVIVED the suite: the code
# was wrong and every test still passed. That is the only evidence that a test suite is thin which
# is worth anything, so the mutants that found them are recorded in bench/mutation.py and run in CI.

def test_an_empty_v1_file_raises_even_with_no_canary_to_check(tmp_path, monkeypatch):
    """The v2 file is also caught by the canary assertion, which MASKED this one: the empty-list
    check could be deleted entirely and the suite stayed green. A v1-format file has no canary,
    so only the empty check stands between it and a silently disabled layer."""
    p = str(tmp_path / "v1empty.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps({"tokens": []}))
    with pytest.raises(g.PolicyError):
        load(p, monkeypatch)


def test_load_policy_ITSELF_refuses_when_the_matcher_is_broken(tmp_path, monkeypatch):
    """The probe had tests, but they all called _probe_matcher directly. Removing the CALL from
    load_policy therefore changed nothing observable: the probe existed and was never run."""
    p = write_denylist(tmp_path, ["zztokenone"])
    monkeypatch.setattr(g, "_deny_hit", lambda tok, low: False)
    monkeypatch.setenv("PII_DENYLIST", p)
    with pytest.raises(g.PolicyError):
        g.load_policy(None)


def test_malformed_json_raises_from_read_json_itself(tmp_path, monkeypatch):
    """Pinned at the lowest level, so a caller that grows its own try/except cannot re-open the
    fail-open by accident."""
    p = tmp_path / "bad.json"
    p.write_text("{ not json at all", encoding="utf-8")
    with pytest.raises(g.PolicyError):
        g._read_json(str(p))


def test_grant_for_respects_the_domain_boundary_on_its_own(tmp_path, monkeypatch):
    """scan_text re-checks the scope, which masked a grant_for that handed back a history-only
    grant in every domain. Two layers agreeing is fine; two layers where only one is tested is
    how the untested one rots."""
    pol = g.Policy()
    pol.grants = [g.Grant("zztok", "history-only", "accepted-public", "x")]
    assert pol.grant_for("zztok", "history") is not None
    assert pol.grant_for("zztok", "tree") is None
    assert pol.grant_for("zztok", "staged") is None
    pol2 = g.Policy()
    pol2.grants = [g.Grant("zztok", "all", "false-positive", "x")]
    assert pol2.grant_for("zztok", "tree") is not None      # the twin: scope=all does reach live


def test_a_renamed_tokens_key_is_named_in_the_error(tmp_path, monkeypatch):
    """A second mutation survivor. Deleting the dedicated `tokens`-is-missing check left the
    generic type check to catch it, so the file still failed, but with a message that talked
    about types instead of naming the key that was actually wrong. The operator staring at a
    typo needs to be told which key they typed."""
    p = write_denylist(tmp_path, ["zztokenone"])
    doc = json.loads(io.open(p, encoding="utf-8").read())
    doc["tokenz"] = doc.pop("tokens")          # a typo, the realistic version of this mistake
    io.open(p, "w", encoding="utf-8").write(json.dumps(doc))
    with pytest.raises(g.PolicyError) as ei:
        load(p, monkeypatch)
    assert "tokenz" in str(ei.value), str(ei.value)


def test_the_receipt_counts_a_grant_that_DID_fire(tmp_path, monkeypatch):
    """The twin of the never-fired test, and another mutation survivor: with `used` never set,
    the receipt reported every grant as inert, which reads as an alarm and is pure noise. A
    counter is only meaningful if it can move in both directions."""
    grants, _ = _exempt(tmp_path, monkeypatch, {"owner/scanned-repo": [
        {"token": "zzaccepted", "scope": "history-only", "exposure": "accepted-public",
         "reason": "already disclosed"}]})
    pol = g.Policy()
    pol.grants = grants
    pol.tokens = [g.Token("zzaccepted", "secret")]
    out = []
    g.scan_text("zzaccepted appears here", "x", set(), pol, out, domain="history")
    r = pol.receipt()
    assert "1 declared" in r and "1 matched" in r and "0 never fired" in r


def test_the_canary_is_never_treated_as_a_token_to_search_for(tmp_path, monkeypatch):
    """pii_guard.py has to contain the canary string in order to check for it, and pii_guard.py
    is vendored into every public repo and scanned there. If the canary were policy, the guard
    would flag itself in eighteen places on the day the file was migrated."""
    p = write_denylist(tmp_path, ["zztokenone"])
    pol = load(p, monkeypatch)
    assert g.CANARY_TOKEN not in [t.value for t in pol.tokens]
    out = []
    g.scan_text("a line mentioning %s here" % g.CANARY_TOKEN, "x", set(), pol, out, domain="tree")
    assert out == []


# ================================================================== round 2: adversarial findings
# Everything below pins a defect that survived the first version of the redesign and was found by
# pointing attackers at it. Each was reproduced by hand before it was written down.

B = chr(92)


def _hits(text, allow=(), tokens=(), domain="tree"):
    out = []
    g.scan_text(text, "x", set(allow), g.Policy.of(tokens), out, domain=domain)
    return [(k, v) for _, k, v, _s in out]


def test_a_windows_home_path_with_DOUBLED_backslashes_is_caught():
    """Every JSON config and every non-raw source line writes it this way. The single-backslash
    form was caught and this one was missed, in the category the audit found leaking most."""
    kinds = {k for k, _ in _hits('{"home": "C:%sUsers%sjanedoe%swork"}' % (B + B, B + B, B + B))}
    assert "USER-PATH" in kinds


def test_the_single_backslash_form_still_works():
    assert "USER-PATH" in {k for k, _ in _hits("C:%sUsers%sjanedoe%sx" % (B, B, B))}


def test_a_generic_account_in_the_doubled_form_is_still_not_a_person():
    assert not _hits('{"home": "C:%sUsers%srunner%swork"}' % (B + B, B + B, B + B))


def test_zip_the_archive_format_is_not_a_postcode():
    assert not _hits("the zip archive is 45231 bytes")


def test_zip_the_postcode_still_fires():
    """The twin. Fixing the archive meaning must not cost the postal one."""
    assert "ZIP" in {k for k, _ in _hits("zip code 08540 for returns")}
    assert "ZIP" in {k for k, _ in _hits("ZIP 08540")}
    assert "ZIP" in {k for k, _ in _hits("ship to NJ 08540")}


def test_a_tensor_shape_is_not_a_phone_number():
    """This machine's pre-commit hook runs in every repo on it, including forks of training
    frameworks, so this false positive is a blocked commit in somebody else's project."""
    assert not _hits("conv kernel 512-256-1024 stack")
    assert not _hits("hidden dim 512-256-1024")


def test_a_phone_number_near_ml_words_still_fires_when_it_is_shaped_like_one():
    """Context yields only for the hyphen-only form. Parentheses, a +1, dots or spaces are shapes
    a tensor shape never takes, so they are never excused."""
    assert "PHONE" in {k for k, _ in _hits("kernel size, then call (201) 867-5309 for data")}
    assert "PHONE" in {k for k, _ in _hits("layer dims, tel +1 201-867-5309")}


def test_a_bare_hyphen_triple_with_no_dimension_word_is_still_a_finding():
    assert "PHONE" in {k for k, _ in _hits("reach me on 201-867-5309")}


def test_a_generic_pii_allow_entry_is_not_an_off_switch():
    """`.pii-allow` lives INSIDE the repo. An unanchored substring test made one common word an
    in-repo off switch for an entire class. Measured: both of these silenced everything."""
    path = "C:%sUsers%sjanedoe%ssecret.txt" % (B, B, B)
    assert "USER-PATH" in {k for k, _ in _hits(path, allow={"users"})}
    assert "USER-PATH" in {k for k, _ in _hits(path, allow={"a"})}


def test_a_specific_pii_allow_entry_still_exempts():
    """The twin that keeps the escape hatch open. Removing the hatch is not a fix."""
    assert not _hits('RUNNER = "~/.claude/scripts/self.ps1"',
                     allow={".claude/scripts/self.ps1"})
    # short, but a dotted directory name rather than an English word
    assert not _hits("config lives under ~/.claude/settings.json", allow={".claude"})


def test_scanner_exemption_is_keyed_on_PATH_not_basename():
    """`git mv secrets.md docs/pii_guard.py` used to buy a file, anywhere in the repo, that
    skipped every structural check."""
    assert g.is_scanner_path("tools/pii_guard.py")
    assert not g.is_scanner_path("docs/pii_guard.py")
    assert g.is_scanner_path(".pii-allow")          # and NOT mangled by lstrip("./")


def test_a_copy_elsewhere_proves_itself_with_the_marker():
    """skill-smith ships a copy of the guard as a template asset at a non-standard path. Identity,
    not location: a renamed secrets file cannot produce the marker."""
    assert g.is_scanner_content("assets/pii-guard/pii_guard.py", "# " + g.SCANNER_MARKER + "\n...")
    assert not g.is_scanner_content("docs/pii_guard.py", "contact jane.doe@gmail.com\n")


@pytest.mark.parametrize("enc", ["utf-16", "cp1252"])
def test_text_that_is_not_utf8_is_still_read(enc):
    """A UTF-16 file was invisible in every domain at once: the tree skipped it on a decode error
    and git marks it binary in diffs. Not UTF-8 is not not-text."""
    text, got = g._decode_best("contact jane.doe@gmail.com".encode(enc))
    assert text is not None and "jane.doe" in text, got


def test_genuinely_binary_content_is_refused_rather_than_force_decoded():
    """The twin. UTF-16 and cp1252 decode almost anything, so without a text check a PNG came back
    as `utf-16` and counted as EXAMINED, which is the opposite of the property being added."""
    png = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A] * 200)
    assert g._decode_best(png) == (None, None)


def test_the_prefilter_returns_exactly_what_the_naive_loop_returns():
    """The prefilter is an optimisation, and an optimisation that changes answers is a bug with a
    benchmark attached. Alternation is leftmost-first, so if it were used to READ the matches
    instead of just to decide whether to look, a longer token would shadow a shorter one -- and if
    the longer were `derived` while the shorter were `secret`, that would silently downgrade a real
    finding."""
    toks = [g.Token("zzalpha", "secret"), g.Token("zzalphabeta", "derived"),
            g.Token("zz-9137", "secret"), g.Token("zzgamma", "linkage")]
    pol = g.Policy()
    pol.tokens = toks
    samples = ["nothing here at all", "zzalpha", "zzalphabeta", "a zzalpha and zzalphabeta",
               "zz-9137 inside", "xxzzalphaxx", "ZZALPHA upper", "", "zzgamma zzalpha zz-9137"]
    for text in samples:
        low = text.lower()
        naive = sorted(t.value for t in toks if g._deny_hit(t.value, low))
        out = []
        g.scan_text(text, "x", set(), pol, out, domain="tree")
        got = sorted(v.split(" (")[0] for _w, lab, v, _s in out if "DENYLIST" in lab)
        assert naive == got, (text, naive, got)


def test_a_derived_verdict_exhibits_its_witness(tmp_path, monkeypatch):
    """A declassification that cannot show its own derivation is an assertion. The witness names
    the public parent, so a reader can check the claim instead of trusting it."""
    vis = tmp_path / "vis.json"
    vis.write_text(json.dumps({"owner/example-skill": "PUBLIC",
                               "owner/example-skill-config": "PRIVATE"}), encoding="utf-8")
    monkeypatch.setattr(g, "_run", lambda *a, **k: "git@github.com:owner/other.git\n")
    tok = g._cross_repo_tokens_typed(".", vis_path=str(vis))[0]
    assert tok.kind == "derived"
    assert tok.witness and "example-skill" in tok.witness and "PUBLIC" in tok.witness


def test_a_linkage_token_has_no_witness_to_show():
    assert g.Token("hidden-venture-config", "linkage").witness is None


# ================================================================== round 2, part 2
# These pin behaviours that only the scenario corpus covered. The corpus is the better evidence
# (it drives the real CLI end to end) but it is far too slow to run under mutation testing, and a
# behaviour that only a slow suite protects is a behaviour the fast suite will silently break.
# Fourteen mutants survived until these existed.

import subprocess  # noqa: E402

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pii_guard.py")


class Repo(object):
    """A throwaway git repo with an isolated config, so the machine's real hooks and identity
    rules never fire inside a test."""

    def __init__(self, root):
        self.root = str(root)
        self.cfg = os.path.join(self.root, "..", "gitconfig")
        with io.open(self.cfg, "w", encoding="utf-8") as f:
            f.write("[user]\n\tname = Fixture\n\temail = fixture@users.noreply.github.com\n"
                    "[init]\n\tdefaultBranch = master\n[core]\n\thooksPath = %s\n"
                    % os.path.join(self.root, "..", "nohooks").replace(chr(92), "/"))
        self.env = dict(os.environ)
        self.env["GIT_CONFIG_GLOBAL"] = self.cfg
        self.env["GIT_CONFIG_SYSTEM"] = os.path.join(self.root, "..", "nosys")
        self.git("init", "-q")
        self.git("remote", "add", "origin",
                 "https://github.com/exampleowner/scanned-repo.git")

    def git(self, *args, **kw):
        p = subprocess.run(["git"] + list(args), cwd=self.root, env=self.env,
                           capture_output=True, text=True)
        if p.returncode != 0 and not kw.get("allow_fail"):
            raise RuntimeError("git %s: %s" % (" ".join(args), p.stderr))
        return p

    def write(self, rel, text, mode="w"):
        p = os.path.join(self.root, rel)
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        if "b" in mode:
            open(p, "wb").write(text)
        else:
            io.open(p, "w", encoding="utf-8", newline="\n").write(text)

    def commit(self, msg="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(d)


def _labels(findings):
    return {lab for _w, lab, _v, _s in findings}


def test_a_real_address_in_a_FILE_NAME_is_a_finding(repo):
    """Only file CONTENT was ever scanned. A filename is as public as the bytes inside it."""
    repo.write("contacts/jane.doe@gmail.com.md", "nothing in here\n")
    repo.commit()
    out = g.scan_tree(repo.root, set(), g.Policy.of([]))
    # EMAIL rather than PERSONAL-MAILBOX, because the `.md` suffix makes the domain
    # `gmail.com.md` and the consumer-provider rule matches the exact domain. Either label is a
    # BLOCK, and pinning the label here would be pinning an accident of the file extension.
    assert out and all(sev == "BLOCK" for _w, _l, _v, sev in out), out
    # ...and with no extension in the way it is recognised as exactly what it is
    repo.write("contacts/jane.doe@gmail.com", "nothing in here\n")
    repo.commit()
    assert "PERSONAL-MAILBOX" in _labels(g.scan_tree(repo.root, set(), g.Policy.of([])))


def test_an_ordinary_filename_is_not_a_finding(repo):
    repo.write("docs/release-notes-2026.md", "ordinary\n")
    repo.commit()
    assert g.scan_tree(repo.root, set(), g.Policy.of([])) == []


def _merge_in_and_out(repo, token):
    repo.write("f.md", "base\n")
    repo.commit("base")
    repo.git("checkout", "-qb", "side")
    repo.write("f.md", "side\n")
    repo.commit("side")
    repo.git("checkout", "-q", "master")
    repo.write("f.md", "main\n")
    repo.commit("main")
    repo.git("merge", "side", "--no-commit", allow_fail=True)
    repo.write("f.md", "resolved with %s\n" % token)      # from neither parent
    repo.commit("merge one")
    repo.git("checkout", "-qb", "side2", "HEAD~1")
    repo.write("g.md", "other\n")
    repo.commit("side two")
    repo.git("checkout", "-q", "master")
    repo.git("merge", "side2", "--no-commit", allow_fail=True)
    repo.write("f.md", "resolved\n")                      # and out again
    repo.commit("merge two")


def test_content_that_exists_only_in_a_merge_is_still_found(repo):
    """`git log --all -p` prints nothing for a merge, so a conflict resolution is absent from the
    diff stream; a second merge removing it keeps it out of every ordinary commit's diff too. The
    blob is in the object store and will be pushed. Both earlier versions printed clean."""
    tok = "zzmergeonlytoken"
    _merge_in_and_out(repo, tok)
    assert tok not in repo.git("log", "--all", "-p").stdout        # the premise, checked
    out = g.scan_history(repo.root, set(), g.Policy.of([tok]))
    assert out, "the object graph walk missed a blob that is in the repository"


def test_an_ordinary_merge_does_not_become_a_finding(repo):
    """The twin: the object walk must not turn clean history into findings."""
    _merge_in_and_out(repo, "nothing private here")
    assert g.scan_history(repo.root, set(), g.Policy.of(["zzmergeonlytoken"])) == []


def test_a_merge_resolution_is_scanned_in_the_push_range(repo):
    tok = "zzmergerangetoken"
    repo.write("f.md", "base\n")
    repo.commit("base")
    repo.git("checkout", "-qb", "side")
    repo.write("f.md", "side\n")
    repo.commit("side")
    repo.git("checkout", "-q", "master")
    repo.write("f.md", "main\n")
    repo.commit("main")
    repo.git("merge", "side", "--no-commit", allow_fail=True)
    repo.write("f.md", "resolved with %s\n" % tok)
    repo.commit("merge")
    out = g.scan_range(repo.root, set(), g.Policy.of([tok]), "HEAD^1..HEAD")
    assert out, "the machine-wide pre-push gate is blind to conflict resolutions"


def test_an_oversize_blob_is_recorded_rather_than_silently_skipped(repo, monkeypatch):
    """A silent size cap is a hole with a performance justification attached."""
    monkeypatch.setattr(g, "MAX_BLOB_BYTES", 64)
    repo.write("big.md", "x" * 4096)
    repo.commit()
    stats = g._blank_history_stats()
    g.scan_history(repo.root, set(), g.Policy.of([]), stats=stats)
    assert stats["blobs_oversize"], "the cap left no trace"


def _cli(repo, *args):
    env = dict(repo.env)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, GUARD, "--repo", repo.root] + list(args),
                       cwd=repo.root, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def test_a_run_that_skipped_something_does_not_call_itself_clean(repo, monkeypatch):
    """The distinction the whole codebase is about: checked and found nothing, versus did not
    look."""
    monkeypatch.delenv("PII_DENYLIST", raising=False)
    repo.env.pop("PII_DENYLIST", None)
    repo.write("keep.md", "ordinary\n")
    repo.write("blob.bin", bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A] * 200), "wb")
    repo.commit()
    rc, out = _cli(repo, "--tree")
    assert rc == 0
    assert "pii_guard: clean" not in out, out


def test_a_clean_run_over_everything_DOES_call_itself_clean(repo, monkeypatch):
    """The twin. Without it, never printing the word would score perfectly."""
    monkeypatch.delenv("PII_DENYLIST", raising=False)
    repo.env.pop("PII_DENYLIST", None)
    repo.write("keep.md", "ordinary\n")
    repo.commit()
    rc, out = _cli(repo, "--tree")
    assert rc == 0 and "pii_guard: clean" in out, out


def _grant(repo, tmp_path, home_name, token, content):
    home = str(tmp_path / home_name)
    os.makedirs(os.path.join(home, ".pii-guard"), exist_ok=True)
    dl = os.path.join(home, "denylist.json")
    io.open(dl, "w", encoding="utf-8").write(json.dumps(
        {"format": 2, "canary": g.CANARY_TOKEN, "count": 2,
         "tokens": [{"value": token, "kind": "secret"},
                    {"value": g.CANARY_TOKEN, "kind": "secret"}]}))
    env = dict(repo.env)
    env["PII_DENYLIST"] = dl
    env["USERPROFILE"] = env["HOME"] = home
    repo.write("keep.md", content)
    repo.commit()
    nonce = g._nonce_for("exampleowner/scanned-repo", token)
    p = subprocess.run([sys.executable, GUARD, "grant", "--repo", repo.root,
                        "--token", token, "--exposure", "false-positive",
                        "--reason", "testing", "--nonce", nonce],
                       cwd=repo.root, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p, home


def test_grant_refuses_when_the_token_produces_no_finding(repo, tmp_path):
    """The nonce is offline-computable, so it is a typo barrier and not proof. The proof is the
    scan: an exemption for a finding nobody has hit is a pre-emptive silence."""
    p, _home = _grant(repo, tmp_path, "home_a", "zzgranttesttoken", "nothing private here\n")
    assert p.returncode != 0
    assert "no finding" in (p.stdout + p.stderr)


def test_grant_accepts_when_the_token_really_is_live(repo, tmp_path):
    """The twin, and the one that keeps the exit reachable."""
    p, home = _grant(repo, tmp_path, "home_b", "zzgranttesttoken",
                     "we reference zzgranttesttoken here\n")
    assert p.returncode == 0, p.stdout + p.stderr
    assert os.path.exists(os.path.join(home, ".pii-guard", "grant-log.jsonl"))
    logged = io.open(os.path.join(home, ".pii-guard", "grant-log.jsonl"),
                     encoding="utf-8").read()
    assert "zzgranttesttoken" not in logged        # the log records a digest, never the token


def test_a_derived_finding_prints_its_witness():
    pol = g.Policy()
    pol.tokens = [g.Token("example-skill-config", "derived", source="cross-repo",
                          witness="owner/example-skill is PUBLIC")]
    out = []
    g.scan_text("we write to example-skill-config", "x", set(), pol, out, domain="tree")
    assert out and "(from owner/example-skill is PUBLIC)" in out[0][2]


def test_a_short_repo_name_does_not_exempt_its_unrelated_siblings(tmp_path, monkeypatch):
    vis = tmp_path / "vis2.json"
    vis.write_text(json.dumps({"owner/ab": "PUBLIC", "owner/ab-config": "PRIVATE",
                               "owner/ab-hidden-thing": "PRIVATE"}), encoding="utf-8")
    monkeypatch.setattr(g, "_run", lambda *a, **k: "git@github.com:owner/ab.git\n")
    vals = [t.value for t in g._cross_repo_tokens_typed(".", vis_path=str(vis))]
    assert "ab-hidden-thing" in vals          # an unrelated private sibling
    assert "ab-config" not in vals            # the twin: this repo's OWN companion


def test_a_single_hyphen_data_companion_is_admitted(tmp_path, monkeypatch):
    vis = tmp_path / "vis3.json"
    vis.write_text(json.dumps({"owner/pubtool": "PUBLIC", "owner/pubtool-data": "PRIVATE"}),
                   encoding="utf-8")
    monkeypatch.setattr(g, "_run", lambda *a, **k: "git@github.com:owner/other.git\n")
    toks = g._cross_repo_tokens_typed(".", vis_path=str(vis))
    assert [(t.value, t.kind) for t in toks] == [("pubtool-data", "derived")]


def test_an_unknown_visibility_state_is_reported(tmp_path, monkeypatch):
    vis = tmp_path / "vis4.json"
    vis.write_text(json.dumps({"owner/x-y-z": "ARCHIVED"}), encoding="utf-8")
    monkeypatch.setattr(g, "_run", lambda *a, **k: "git@github.com:owner/other.git\n")
    notes = []
    g._cross_repo_tokens_typed(".", vis_path=str(vis), notes=notes)
    assert any("visibility state" in n for n in notes)


def test_an_absent_visibility_map_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "_run", lambda *a, **k: "git@github.com:owner/other.git\n")
    notes = []
    g._cross_repo_tokens_typed(".", vis_path=str(tmp_path / "nope.json"), notes=notes)
    assert any("no visibility map" in n for n in notes)


def test_a_legacy_shaped_policy_file_is_announced(tmp_path, monkeypatch):
    p = str(tmp_path / "legacy.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps({"tokens": ["zzalpha"]}))
    monkeypatch.setenv("PII_DENYLIST", p)
    pol = g.load_policy(None)
    assert any("legacy format" in n for n in pol.notes), pol.notes


def test_a_canary_only_policy_file_is_refused(tmp_path, monkeypatch):
    p = str(tmp_path / "canaryonly.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps(
        {"format": 2, "canary": g.CANARY_TOKEN, "count": 1,
         "tokens": [{"value": g.CANARY_TOKEN, "kind": "secret"}]}))
    with pytest.raises(g.PolicyError):
        load(p, monkeypatch)


def test_a_legacy_BARE_ARRAY_policy_file_is_also_announced(tmp_path, monkeypatch):
    """Two code paths reach the same warning and only one was tested, so the untested one could be
    deleted and the suite stayed green. A bare JSON array is the oldest shape of this file."""
    p = str(tmp_path / "legacy_array.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps(["zzalpha", "zzbeta"]))
    monkeypatch.setenv("PII_DENYLIST", p)
    pol = g.load_policy(None)
    assert any("legacy format" in n for n in pol.notes), pol.notes


def test_a_tracked_path_with_a_leading_space_is_still_scanned(repo):
    """`git ls-files -z` makes the separator unambiguous, so trimming each entry is not just
    unnecessary, it corrupts paths that legitimately begin or end with whitespace. The file then
    fails to open and is recorded as unreadable -- honest, and still a miss.

    Found by the self-evolve proposer: `tracked_files` documented that stripping was wrong while
    `scan_tree` still stripped. A comment disagreeing with the code under it is precisely what an
    automated reader is good at noticing."""
    repo.write(" leading space.md", "contact jane.doe@gmail.com\n")
    repo.commit()
    stats = {}
    out = g.scan_tree(repo.root, set(), g.Policy.of([]), stats=stats)
    assert stats.get("scanned") == 1, stats
    assert not stats.get("unreadable"), stats
    assert "PERSONAL-MAILBOX" in _labels(out)


def _stage_edit(repo, rel):
    repo.write("seed.md", "seed\n")
    repo.commit("seed")
    repo.write(rel, "# fixture line mentioning jane.doe@gmail.com\n")
    repo.git("add", "-A")
    return g.scan_staged(repo.root, set(), g.Policy.of([]))


def test_editing_the_vendored_v2_test_file_is_not_blocked_by_its_own_fixtures(repo):
    """`test_pii_guard_v2.py` went into SCANNER_FILES and not into the diff-domain exclusion, so
    staging an edit to the vendored copy was blocked by the test's own synthetic mailbox. Verified
    2026-08-20 with a matched control. Found by the self-evolve proposer.

    The exclusion is now DERIVED from SCANNER_PATHS, so the two lists cannot drift again."""
    assert _stage_edit(repo, "tools/test_pii_guard_v2.py") == []


def test_the_other_two_scanner_files_are_still_exempt_in_the_diff_domains(repo):
    assert _stage_edit(repo, "tools/pii_guard.py") == []


def test_a_scanner_BASENAME_elsewhere_is_NOT_exempt_in_the_diff_domains(repo):
    """The exclusion used to be a `*basename` glob, so any file called pii_guard.py anywhere was
    dropped from the staged and range scans. Same shadow the tree domain had, same fix."""
    out = _stage_edit(repo, "docs/pii_guard.py")
    assert out and any(lab == "PERSONAL-MAILBOX" for _w, lab, _v, _s in out), out


def test_the_exclusion_covers_every_scanner_path():
    """Derived, not maintained by hand. A list that has to be kept in step with another list is a
    list that will fall out of step with it, which is exactly what happened."""
    for p in g.SCANNER_PATHS:
        assert (":(exclude)" + p) in g.HISTORY_EXCLUDE


@pytest.mark.parametrize("path,expect_finding", [
    ("~/.claude-plugin/plugin.json", False),        # the public manifest convention
    ("~/.claude-plugin", False),
    ("~/.claude-plugins-private/keys.json", True),  # NOT the convention, merely starts like it
    ("~/.claude/skills/example-skill", False),      # a shallow install dir, also a convention
    ("~/.claude/scripts/relay.py", True),           # a deep path into a private tool
])
def test_the_public_dotpath_convention_needs_a_word_boundary(path, expect_finding):
    """Without `\b` after `-plugin`, any dotdir whose name STARTS with `.claude-plugin` counted
    as the public manifest convention. Proposed by the self-evolve proposer."""
    got = "PRIVATE-PATH" in {k for k, _ in _hits('P = "%s"' % path)}
    assert got is expect_finding, (path, got)
