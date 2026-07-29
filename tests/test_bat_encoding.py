"""守住 .bat 的纯 ASCII 约定（回归护栏）。

cmd.exe 按字节块读文件、却按字符数重新定位，含非 ASCII 字符的 .bat 会被解析错位：
行从中间截断、尾巴当命令执行。日文（CP932）环境实测报错::

    'ASCII縲・REM' は、内部コマンドまたは外部コマンド... として認識されていません。

那个碎片来自一行 **REM 注释**的中间——所以「中文只写在 echo 里」「不放进 () 块」
都不够，唯一可靠的规则是：这些 .bat 里一个非 ASCII 字节都不能有，注释也算。
中文界面一律放 scripts/menu.py（Python 按真正的 UTF-8 解码源码，没有此问题）。

护栏范围 = **项目里全部 .bat**（自动发现，新加的 .bat 自动纳入，不用改这里）。
"""
from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 自动发现：根目录 + scripts\ 下的所有 .bat。用 sorted 保证失败信息稳定可复现。
ASCII_ONLY_BATS = tuple(
    sorted(
        list(PROJECT_ROOT.glob("*.bat")) + list((PROJECT_ROOT / "scripts").glob("*.bat"))
    )
)


class BatEncodingTests(unittest.TestCase):
    def test_expected_bats_are_discovered(self) -> None:
        # 防止 glob 因目录结构变动而空转，护栏悄悄失效
        names = {p.name for p in ASCII_ONLY_BATS}
        for expected in ("menu.bat", "build_exe.bat", "clear_pycache.bat",
                         "install_deps.bat", "run_qml_shell.bat"):
            with self.subTest(bat=expected):
                self.assertIn(expected, names)

    def test_pure_ascii(self) -> None:
        for path in ASCII_ONLY_BATS:
            with self.subTest(bat=path.name):
                data = path.read_bytes()
                bad = [(i, b) for i, b in enumerate(data) if b > 127]
                if bad:
                    offset, byte = bad[0]
                    line = data[:offset].count(b"\n") + 1
                    self.fail(
                        f"{path.name} 第 {line} 行有非 ASCII 字节 0x{byte:02x}"
                        f"（共 {len(bad)} 处）。中文请移到 scripts/menu.py；"
                        f"cmd 解析含中文的 .bat 会错位，注释里也不行。"
                    )

    def test_no_bom(self) -> None:
        # BOM 会被 cmd 当成第一条命令的一部分，第一行直接报错
        for path in ASCII_ONLY_BATS:
            with self.subTest(bat=path.name):
                self.assertNotEqual(path.read_bytes()[:3], b"\xef\xbb\xbf")

    def test_menu_bat_hands_off_to_python_menu(self) -> None:
        # menu.bat 只该做转发；真正的界面在 scripts/menu.py 里
        text = (PROJECT_ROOT / "menu.bat").read_text(encoding="ascii")
        self.assertIn("scripts\\menu.py", text)
        self.assertTrue((PROJECT_ROOT / "scripts" / "menu.py").exists())

    def test_menu_bat_goto_targets_all_exist(self) -> None:
        import re

        text = (PROJECT_ROOT / "menu.bat").read_text(encoding="ascii")
        labels = {m.group(1).lower() for m in re.finditer(r"(?m)^:(\w+)", text)}
        targets = {m.group(1).lower() for m in re.finditer(r"goto\s+:?(\w+)", text)}
        self.assertEqual(targets - labels, set(), "menu.bat 有 goto 指向不存在的标签")


if __name__ == "__main__":
    unittest.main()
