import math
from tools.sie import anchors


def _mk(n, host, cik, period):
    return [{"anchor_id": f"{host}{i}", "span": "x"*5,
             "source_url": f"https://{host}/path?CIK={cik}&type=10-K",
             "cik": cik, "period": period, "metric": f"m{i}", "verified": True}
            for i in range(n)]


def test_eight_same_source_anchors_downweighted_below_eight():
    eff = anchors.effective_independent_count(_mk(8, "sec.gov", "320193", "FY2024"))
    assert eff < 8          # 同源簇必须被降权
    # 单簇折算 = floor(1 + log2(8)) = floor(4) = 4
    assert eff == 4


def test_distinct_sources_count_full():
    a = (_mk(1, "sec.gov", "1", "FY2024") + _mk(1, "fmpcloud.io", "2", "FY2023")
         + _mk(1, "nasdaq.com", "3", "FY2022"))
    assert anchors.effective_independent_count(a) == 3


def test_unverified_anchors_excluded():
    a = _mk(4, "sec.gov", "1", "FY2024")
    for x in a:
        x["verified"] = False
    assert anchors.effective_independent_count(a) == 0


def test_mixed_clusters_sum_floored_per_cluster():
    # 簇1: 4 同源 -> floor(1+log2(4))=3 ; 簇2: 2 同源 -> floor(1+log2(2))=2
    a = _mk(4, "sec.gov", "1", "FY2024") + _mk(2, "fmpcloud.io", "2", "FY2023")
    assert anchors.effective_independent_count(a) == 5


def test_single_anchor_per_cluster():
    # 单锚簇: floor(1 + log2(1)) = floor(1) = 1
    a = _mk(1, "sec.gov", "1", "FY2024")
    assert anchors.effective_independent_count(a) == 1


def test_empty_anchors():
    assert anchors.effective_independent_count([]) == 0


def test_www_prefix_ignored():
    # www.sec.gov 和 sec.gov 属于同一簇
    a = [{"anchor_id": "1", "span": "x"*5,
          "source_url": "https://www.sec.gov/path",
          "cik": "1", "period": "FY2024", "metric": "m", "verified": True},
         {"anchor_id": "2", "span": "x"*5,
          "source_url": "https://sec.gov/path",
          "cik": "1", "period": "FY2024", "metric": "m", "verified": True}]
    eff = anchors.effective_independent_count(a)
    # 2 个同源 -> floor(1+log2(2)) = floor(1+1) = floor(2) = 2
    assert eff == 2
