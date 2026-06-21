"""Test anchors.split_visible_holdout: deterministic holdout splitting."""
from tools.sie import anchors


def _anchors(n):
    """Generate n test anchors with unique anchor_ids."""
    return [{"anchor_id": f"a{i:03d}", "span": "s", "claim": "c",
             "source_url": "https://x/y", "verified": True} for i in range(n)]


def test_holdout_fraction_size():
    """Test that holdout size matches round(frac * N)."""
    vis, hold = anchors.split_visible_holdout(_anchors(30), 0.3)
    assert len(hold) == 9 and len(vis) == 21
    assert len(vis) + len(hold) == 30


def test_split_is_deterministic():
    """Test that same seed produces identical holdout lists."""
    a = _anchors(30)
    v1, h1 = anchors.split_visible_holdout(a, 0.3, seed="run42")
    v2, h2 = anchors.split_visible_holdout(a, 0.3, seed="run42")
    assert [x["anchor_id"] for x in h1] == [x["anchor_id"] for x in h2]


def test_no_overlap_between_visible_and_holdout():
    """Test that visible and holdout sets are disjoint."""
    vis, hold = anchors.split_visible_holdout(_anchors(24), 0.3)
    vids = {x["anchor_id"] for x in vis}
    hids = {x["anchor_id"] for x in hold}
    assert vids.isdisjoint(hids)


def test_different_seed_changes_holdout():
    """Test that different seeds produce different holdout sets."""
    a = _anchors(30)
    _, h1 = anchors.split_visible_holdout(a, 0.3, seed="A")
    _, h2 = anchors.split_visible_holdout(a, 0.3, seed="B")
    assert [x["anchor_id"] for x in h1] != [x["anchor_id"] for x in h2]


def test_empty_anchors():
    """Test edge case: empty anchors list."""
    vis, hold = anchors.split_visible_holdout([], 0.3)
    assert vis == [] and hold == []


def test_frac_zero():
    """Test edge case: frac=0 produces all visible."""
    vis, hold = anchors.split_visible_holdout(_anchors(10), 0.0)
    assert len(hold) == 0 and len(vis) == 10


def test_frac_one():
    """Test edge case: frac=1 produces all holdout."""
    vis, hold = anchors.split_visible_holdout(_anchors(10), 1.0)
    assert len(hold) == 10 and len(vis) == 0


def test_visible_union_holdout_equals_all():
    """Test that visible ∪ holdout = entire anchor set."""
    anchors_list = _anchors(25)
    vis, hold = anchors.split_visible_holdout(anchors_list, 0.4)
    all_ids = {a["anchor_id"] for a in anchors_list}
    vis_ids = {a["anchor_id"] for a in vis}
    hold_ids = {a["anchor_id"] for a in hold}
    assert vis_ids | hold_ids == all_ids
