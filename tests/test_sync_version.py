"""版本号同步工具单测（scripts/sync_version.py）。

version_info.txt 是构建期产物，由 version.py 生成。这里锁住格式解析、渲染内容、
以及"改 version.py 时不碰其它内容"三件事。纯逻辑 + tmpdir，Linux 可跑。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sync_version.py"
_spec = importlib.util.spec_from_file_location("sync_version", _SCRIPT)
sv = importlib.util.module_from_spec(_spec)
sys.modules["sync_version"] = sv
_spec.loader.exec_module(sv)


@contextlib.contextmanager
def _quiet():
    """吃掉 CLI 的 stdout/stderr，别把测试输出刷花；yield 出取 stdout 文本的函数。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        yield out.getvalue


class ParseVersionTests(unittest.TestCase):
    def test_pads_to_four_parts(self) -> None:
        self.assertEqual(sv.parse_version("1.4"), (1, 4, 0, 0))
        self.assertEqual(sv.parse_version("1.4.2"), (1, 4, 2, 0))
        self.assertEqual(sv.parse_version("1.4.2.7"), (1, 4, 2, 7))

    def test_strips_leading_v(self) -> None:
        self.assertEqual(sv.parse_version("v2.0.1"), (2, 0, 1, 0))
        self.assertEqual(sv.parse_version("V2.0.1"), (2, 0, 1, 0))

    def test_tolerates_surrounding_space(self) -> None:
        self.assertEqual(sv.parse_version("  1.4.0  "), (1, 4, 0, 0))

    def test_rejects_bad_formats(self) -> None:
        for bad in ["", "  ", "1", "1.", "1.4.0.1.2", "1.4.0-beta", "abc", "1.x.0", None]:
            with self.subTest(bad=bad):
                with self.assertRaises(sv.VersionError):
                    sv.parse_version(bad)

    def test_version_strings(self) -> None:
        parts = sv.parse_version("1.4")
        # 写进 version.py 的必须满三段：_parse_semver 只认 \d+\.\d+\.\d+，
        # 两段的 "1.4" 会被解析成 (0,0,0)，导致检查更新永远说有新版本。
        self.assertEqual(sv.app_version_str(parts), "1.4.0")
        self.assertEqual(sv.file_version_str(parts), "1.4.0.0")

    def test_app_version_is_parseable_by_update_checker(self) -> None:
        from eye_care.api.common import _parse_semver

        parts = sv.parse_version("1.4")
        self.assertEqual(_parse_semver(sv.app_version_str(parts)), (1, 4, 0))


class RenderVersionInfoTests(unittest.TestCase):
    def test_contains_both_version_forms(self) -> None:
        text = sv.render_version_info(sv.parse_version("2.5.1"))
        self.assertIn("filevers=(2, 5, 1, 0)", text)
        self.assertIn("prodvers=(2, 5, 1, 0)", text)
        self.assertIn("StringStruct(u'FileVersion', u'2.5.1.0')", text)
        self.assertIn("StringStruct(u'ProductVersion', u'2.5.1.0')", text)

    def test_marked_as_generated(self) -> None:
        text = sv.render_version_info(sv.parse_version("1.0.0"))
        self.assertTrue(text.startswith("# UTF-8"))   # PyInstaller 要求的编码声明在首行
        self.assertIn("请勿手改", text)

    def test_language_and_codepage_stay_paired(self) -> None:
        # 0804=简体中文 + 04b0=1200(Unicode)，与 VarStruct 的 [2052, 1200] 必须成对
        text = sv.render_version_info(sv.parse_version("1.0.0"))
        self.assertIn("u'080404b0'", text)
        self.assertIn("VarStruct(u'Translation', [2052, 1200])", text)

    def test_output_is_valid_python_literal_structure(self) -> None:
        # PyInstaller 会 eval 这个文件；至少保证括号配平、能被 Python 解析
        text = sv.render_version_info(sv.parse_version("9.8.7.6"))
        body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        import ast

        ast.parse(body, mode="eval")


class ReplaceAppVersionTests(unittest.TestCase):
    def test_replaces_only_the_assignment(self) -> None:
        src = '"""应用版本号，用于检查更新比较。"""\nAPP_VERSION = "1.3.0"\n'
        out = sv.replace_app_version(src, "1.4.0")
        self.assertEqual(out, '"""应用版本号，用于检查更新比较。"""\nAPP_VERSION = "1.4.0"\n')

    def test_keeps_surrounding_comments(self) -> None:
        src = '# 头部注释\nAPP_VERSION = "1.0.0"  # 尾注释\nOTHER = 1\n'
        out = sv.replace_app_version(src, "2.0.0")
        self.assertIn("# 头部注释", out)
        self.assertIn("# 尾注释", out)
        self.assertIn("OTHER = 1", out)
        self.assertIn('APP_VERSION = "2.0.0"', out)

    def test_handles_single_quotes(self) -> None:
        out = sv.replace_app_version("APP_VERSION = '1.0.0'\n", "1.1.0")
        self.assertIn('APP_VERSION = "1.1.0"', out)

    def test_raises_when_assignment_missing(self) -> None:
        with self.assertRaises(sv.VersionError):
            sv.replace_app_version("VERSION = '1.0.0'\n", "1.1.0")


class SyncRoundTripTests(unittest.TestCase):
    """在 tmpdir 上跑完整流程，不碰仓库里的真文件。"""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "eye_care").mkdir()
        self._version_py = root / "eye_care" / "version.py"
        self._version_info = root / "version_info.txt"
        self._version_py.write_text(
            '"""应用版本号，用于检查更新比较。"""\nAPP_VERSION = "1.3.0"\n', encoding="utf-8"
        )
        self._orig = (sv.VERSION_PY, sv.VERSION_INFO)
        sv.VERSION_PY, sv.VERSION_INFO = self._version_py, self._version_info

    def tearDown(self) -> None:
        sv.VERSION_PY, sv.VERSION_INFO = self._orig
        self._tmp.cleanup()

    def test_bump_writes_both_files(self) -> None:
        old, new = sv.sync("1.4")

        self.assertEqual((old, new), ("1.3.0", "1.4.0"))
        self.assertIn('APP_VERSION = "1.4.0"', self._version_py.read_text(encoding="utf-8"))
        self.assertIn("filevers=(1, 4, 0, 0)", self._version_info.read_text(encoding="utf-8"))

    def test_regenerate_without_argument_keeps_version(self) -> None:
        self._version_info.unlink(missing_ok=True)
        old, new = sv.sync(None)

        self.assertEqual((old, new), ("1.3.0", "1.3.0"))
        self.assertTrue(self._version_info.exists())
        self.assertIn("filevers=(1, 3, 0, 0)", self._version_info.read_text(encoding="utf-8"))

    def test_bad_version_writes_nothing(self) -> None:
        before = self._version_py.read_text(encoding="utf-8")
        with self.assertRaises(sv.VersionError):
            sv.sync("1.4.0-beta")

        self.assertEqual(self._version_py.read_text(encoding="utf-8"), before)
        self.assertFalse(self._version_info.exists())

    def test_cli_show_does_not_write(self) -> None:
        self._version_info.unlink(missing_ok=True)
        with _quiet() as out:
            rc = sv.main(["--show"])

        self.assertEqual(rc, 0)
        self.assertEqual(out().strip(), "1.3.0")
        self.assertFalse(self._version_info.exists())

    def test_cli_bad_version_returns_error_code(self) -> None:
        with _quiet():
            self.assertEqual(sv.main(["nope"]), 2)

    def test_generated_version_files_use_lf_on_windows_too(self) -> None:
        sv.sync("1.3.1")
        self.assertNotIn(b"\r\n", self._version_py.read_bytes())
        self.assertNotIn(b"\r\n", self._version_info.read_bytes())


class RepoStateTests(unittest.TestCase):
    """仓库里的两个文件必须是同步的——漏跑同步就在 CI/本地测试里暴露出来。"""

    def test_repo_version_info_matches_version_py(self) -> None:
        current = sv.read_app_version()
        expected = sv.render_version_info(sv.parse_version(current))
        actual = sv.VERSION_INFO.read_text(encoding="utf-8")

        self.assertEqual(
            actual.replace("\r\n", "\n"),
            expected.replace("\r\n", "\n"),
            "version_info.txt 与 version.py 不同步，请运行 python scripts/sync_version.py",
        )

    def test_repo_app_version_has_three_parts(self) -> None:
        self.assertRegex(sv.read_app_version(), r"^\d+\.\d+\.\d+$")

if __name__ == "__main__":
    unittest.main()
