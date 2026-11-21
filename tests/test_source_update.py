from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eye_care.source_update import WEB, SourceUpdateService, UpdateError, github_asset, source_name


class SourceReleaseTests(unittest.TestCase):
    def release(self, version):
        tag = "v" + version
        name = source_name(version)
        return {"tag_name": tag, "draft": False, "prerelease": False, "assets": [{
            "name": name, "state": "uploaded", "size": 123, "digest": "sha256:" + "a"*64,
            "browser_download_url": f"{WEB}/download/{tag}/{name}"}]}

    def test_official_tag_and_digest_are_bound_to_the_download(self):
        meta = self.release("1.4.1")
        name = source_name("1.4.1")
        self.assertEqual(github_asset(meta, "v1.4.1", name)["asset_sha256"], "a"*64)
        for field, value in (("digest", ""), ("browser_download_url", f"{WEB}/download/v9.0.0/{name}")):
            bad = self.release("1.4.1")
            bad["assets"][0][field] = value
            with self.assertRaises(UpdateError):
                github_asset(bad, "v1.4.1", name)

    def test_stable_version_works_before_and_after_legacy_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = SourceUpdateService(install_dir=Path(tmp), data_dir=Path(tmp), current_version="1.4.0")
            for response, expected in (({"tag_name":"latest"}, False), (self.release("1.4.0"), False),
                                       (self.release("1.4.1"), True)):
                with patch.object(service, "_request_json", return_value=response):
                    self.assertEqual(service.check_update(force=True)["downloadable"], expected)
