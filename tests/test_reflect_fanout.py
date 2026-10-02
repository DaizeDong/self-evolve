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
        assert history[0]["details"]["notes"] == []
        history[0]["details"]["notes"].append(idx)
        received_histories.append(history)
        return {"reflector": idx, "findings": []}

    monkeypatch.setattr(reflect, "_reflect_one", fake_one)
    from tools.make_fixtures import source13_repair_inputs
    shared_history = source13_repair_inputs()["history"]
    reflect.run_reflections_parallel(str(tmp_path), history=shared_history, n_reflectors=3)
    assert len(received_histories) == 3
    assert len({id(history) for history in received_histories}) == 3
    assert len({id(history[0]["details"]) for history in received_histories}) == 3
    assert shared_history[0]["details"]["notes"] == []


# ── Trace read-only: run_reflections_parallel must not modify history list ──

def test_parallel_does_not_mutate_history(monkeypatch, tmp_path):
    import copy
    from tools.make_fixtures import source13_repair_inputs
    def fake_one(run_dir, history, idx, family="claude"):
        history[0]["details"]["notes"].append(idx)
        return {"reflector": idx, "findings": []}

    monkeypatch.setattr(reflect, "_reflect_one", fake_one)
    original = source13_repair_inputs()["history"]
    snapshot = copy.deepcopy(original)
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
