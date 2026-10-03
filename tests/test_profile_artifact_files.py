"""Keep separately profiled synthetic artifact files in distinct private runs."""
import json
from pathlib import Path

from tools.make_fixtures import synthetic_artifact
from tools.sie import profile, runtime_data


def test_sibling_artifacts_have_distinct_private_holdouts(tmp_path):
    reports = []
    for name in ("first.json", "second.json"):
        artifact = tmp_path / name
        artifact.write_text(json.dumps(synthetic_artifact(30)), encoding="utf-8")
        reports.append(profile.run_profile(str(artifact), "synthetic", include_exec_probe=False))

    paths = [Path(report["anchors_holdout_ref"]["path"]) for report in reports]
    assert paths[0] != paths[1]
    private = runtime_data.private_root()
    assert all(path.is_relative_to(private) and path.is_file() for path in paths)
    assert all(report["tier"] == "B" and report["anchors_holdout_ref"]["count"] == 9
               for report in reports)
