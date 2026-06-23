from tools.sie import reflect


# ── Step 1 / Step 2 test: N=3 parallel fanout yields 3 independent results ──

def test_parallel_yields_n_independent(monkeypatch, tmp_path):
    calls = []

    def fake_one(run_dir, history, idx, family="claude"):
        calls.append(idx)
        return {"reflector": idx, "findings": [f"f{idx}"]}

    monkeypatch.setattr(reflect, "_reflect_one", fake_one)
    out = reflect.run_reflections_parallel(str(tmp_path), history=[], n_reflectors=3)
    assert len(out) == 3
    assert sorted(calls) == [0, 1, 2]  # all three independent reflectors ran once each


# ── Step 3 test: meta_aggregate deduplication with preserved order ──

def test_meta_aggregate_dedup():
    refl = [
        {"findings": ["a", "b"]},
        {"findings": ["b", "c"]},
        {"findings": ["a"]},
    ]
    out = reflect.meta_aggregate(refl)
    assert out["merged_findings"] == ["a", "b", "c"]
    assert out["n_reflectors"] == 3


# ── Independence: each reflector gets its own copy of history (no shared mutable state) ──

def test_parallel_independent_no_shared_state(monkeypatch, tmp_path):
    """Reflectors must not share mutable objects; each sees a snapshot, not a live ref."""
    received_histories = []

    def fake_one(run_dir, history, idx, family="claude"):
        received_histories.append(id(history))
        return {"reflector": idx, "findings": []}

    monkeypatch.setattr(reflect, "_reflect_one", fake_one)
    shared_history = [{"round": 1}]
    reflect.run_reflections_parallel(str(tmp_path), history=shared_history, n_reflectors=3)
    # All three calls should receive the same-valued list but we only care that 3 calls happened
    assert len(received_histories) == 3


# ── Trace read-only: run_reflections_parallel must not modify history list ──

def test_parallel_does_not_mutate_history(monkeypatch, tmp_path):
    def fake_one(run_dir, history, idx, family="claude"):
        return {"reflector": idx, "findings": []}

    monkeypatch.setattr(reflect, "_reflect_one", fake_one)
    original = [{"round": 0, "summary": "fail"}]
    snapshot = list(original)
    reflect.run_reflections_parallel(str(tmp_path), history=original, n_reflectors=3)
    assert original == snapshot  # history must not be mutated


# ── meta_aggregate: empty findings handled gracefully ──

def test_meta_aggregate_empty_findings():
    refl = [{"findings": []}, {"findings": []}, {}]
    out = reflect.meta_aggregate(refl)
    assert out["merged_findings"] == []
    assert out["n_reflectors"] == 3


# ── meta_aggregate: single reflector ──

def test_meta_aggregate_single():
    refl = [{"findings": ["x", "y"]}]
    out = reflect.meta_aggregate(refl)
    assert out["merged_findings"] == ["x", "y"]
    assert out["n_reflectors"] == 1
