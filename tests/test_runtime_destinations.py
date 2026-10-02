"""Generated regression coverage for physical and effective PRIVATE destinations."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools.make_fixtures import runtime_destination_samples
from tools.sie import runtime_data


class RuntimeDestinationTests(unittest.TestCase):
    def test_physical_repository_and_all_destination_routes(self):
        recipe = runtime_destination_samples()
        sample = recipe["sample"]
        for case in recipe["cases"]:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                home, private, public = (root / name for name in ("home", "private", "public"))
                for path in (home, private, public):
                    path.mkdir()
                visibility = home / ".pii-guard/visibility.json"
                visibility.parent.mkdir()
                visibility.write_text(json.dumps({
                    "_refreshed": sample["fresh"], sample["slug"]: "PRIVATE", sample["nested_slug"]: "PUBLIC",
                }), encoding="utf-8")
                empty_config = home / "empty.gitconfig"
                empty_config.write_text("", encoding="utf-8")
                environment = {key: value for key, value in os.environ.items()
                               if key.upper() in {"SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "TEMP", "TMP"}}
                environment.update(HOME=str(home), USERPROFILE=str(home),
                                   GIT_CONFIG_GLOBAL=str(empty_config), GIT_CONFIG_NOSYSTEM="1",
                                   GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="file", GIT_OPTIONAL_LOCKS="0")
                with mock.patch.dict(os.environ, environment, clear=True):
                    def git(repo, *arguments):
                        subprocess.run(["git", "-C", str(repo), *arguments], check=True,
                                       capture_output=True, text=True, encoding="utf-8", timeout=15)
                    for repo, origin in ((private, sample["origin"]), (public, sample["nested_origin"])):
                        git(repo, "init", "-q")
                        git(repo, "config", "remote.origin.url", origin)
                    target, allowed = private, case in {"private", "private_secondary_remote", "private_path_with_irrelevant_gitdir"}
                    overrides = {}
                    if case in {"public", "borrowed_gitdir", "borrowed_origin_override", "borrowed_url_override"}:
                        target = public
                    if case == "borrowed_gitdir":
                        overrides.update(GIT_DIR=str(private / ".git"), GIT_WORK_TREE=str(public))
                    elif case == "borrowed_origin_override":
                        overrides.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="remote.origin.url", GIT_CONFIG_VALUE_0=sample["origin"])
                    elif case in {"public_push", "unknown_push"}:
                        git(private, "config", "remote.origin.pushurl", recipe["unknown_origin"] if case == "unknown_push" else sample["nested_origin"])
                    elif case == "public_push_override":
                        overrides.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="remote.origin.pushurl", GIT_CONFIG_VALUE_0=sample["nested_origin"])
                    elif case in {"public_fetch_rewrite", "public_push_rewrite"}:
                        option = "insteadOf" if case == "public_fetch_rewrite" else "pushInsteadOf"
                        git(private, "config", "url." + sample["nested_origin"] + "." + option, sample["origin"])
                    elif case == "borrowed_url_override":
                        overrides.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="url." + sample["origin"] + ".insteadOf", GIT_CONFIG_VALUE_0=sample["nested_origin"])
                    elif case in {"public_secondary_remote", "private_secondary_remote"}:
                        git(private, "config", "remote.backup.url", sample["nested_origin"] if case == "public_secondary_remote" else sample["origin"])
                    elif case == "private_path_with_irrelevant_gitdir":
                        overrides.update(GIT_DIR=str(public / ".git"), GIT_WORK_TREE=str(public))
                    with mock.patch.dict(os.environ, overrides):
                        requested = target / "data"
                        if allowed:
                            self.assertEqual(runtime_data.verify_directory(requested), (requested, target))
                        else:
                            with self.assertRaises(runtime_data.DataBoundaryError):
                                runtime_data.verify_directory(requested)
                        self.assertFalse(requested.exists(), "verification must not create runtime output")


if __name__ == "__main__":
    unittest.main()
