# -*- coding: utf-8 -*-
"""Release hygiene: one version across every declaring file, clean packaging."""
from __future__ import annotations

import importlib.util
import json
import re
import unittest
import zipfile
from pathlib import Path

import build_backend

ROOT = Path(__file__).resolve().parents[1]


def _load_build_release():
    spec = importlib.util.spec_from_file_location(
        "build_release", ROOT / "scripts" / "build_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_release = _load_build_release()


def _pyproject_version() -> str:
    import tomllib

    return str(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])


class VersionConsistencyTest(unittest.TestCase):

    def test_every_declaration_matches_pyproject(self):
        # Raises SystemExit on mismatch; the assertion is that it does not.
        build_release._assert_version_consistency(ROOT)
        version = _pyproject_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertIn(f'version: "{version}"', (ROOT / "manifest.yaml").read_text(encoding="utf-8"))

    def test_runtime_version_matches_pyproject(self):
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        from author_persona_skill import __version__

        self.assertEqual(__version__, _pyproject_version())

    def test_version_source_file_is_not_burned_in_source_tree(self):
        text = (ROOT / "scripts" / "author_persona_skill" / "_version.py").read_text(encoding="utf-8")
        self.assertIn("VERSION = None  # __BURN_VERSION__", text)


class PackagingTest(unittest.TestCase):

    def test_sdist_carries_backend_and_excludes_tests(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        filename = build_backend._write_sdist(tmp.name)
        names = []
        with __import__("tarfile").open(Path(tmp.name) / filename) as archive:
            names = archive.getnames()
        self.assertTrue(any(name.endswith("build_backend.py") for name in names))
        self.assertTrue(any(name.endswith("pyproject.toml") for name in names))
        self.assertFalse(any("/tests/" in name for name in names))

    def test_wheel_burns_version_and_installs_console_script(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        filename = build_backend._write_wheel(tmp.name, editable=False)
        with zipfile.ZipFile(Path(tmp.name) / filename) as archive:
            version_py = archive.read("author_persona_skill/_version.py").decode("utf-8")
            entry_points = archive.read("author_persona_skill-"
                                        f"{_pyproject_version()}.dist-info/entry_points.txt").decode("utf-8")
        self.assertIn(f'VERSION = "{_pyproject_version()}"', version_py)
        self.assertIn("author-persona-skill = author_persona_skill.cli:main", entry_points)

    def test_release_zip_excludes_caches_and_tests(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        result = build_release.build_archive(ROOT, Path(tmp.name) / "release.zip")
        self.assertFalse(any("__pycache__" in name for name in result["files"]))
        self.assertFalse(any(name.startswith("author_persona_skill/tests/") for name in result["files"]))
        self.assertTrue(any(name.endswith("SKILL.md") for name in result["files"]))

    def test_release_zip_carries_vendored_jieba(self):
        # 分词依赖随包分发：zip 内必须带 libs/jieba（含词典与 posseg）与许可声明，
        # 否则解压后的技能会在分词处静默降级为弱信号。
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        result = build_release.build_archive(ROOT, Path(tmp.name) / "release.zip")
        self.assertTrue(result["files"], "打包清单不应为空")
        # 开档校验实际内容，而非只看文件清单。
        with zipfile.ZipFile(Path(tmp.name) / "release.zip") as archive:
            names = archive.namelist()
        self.assertTrue(any(n.endswith("/libs/jieba/__init__.py") for n in names))
        self.assertTrue(any(n.endswith("/libs/jieba/dict.txt") for n in names))
        self.assertTrue(any("/libs/jieba/posseg/" in n for n in names))
        self.assertTrue(any(n.endswith("/libs/jieba/LICENSE") for n in names))
        self.assertFalse(any("__pycache__" in n for n in names))

    def test_wheel_carries_vendored_jieba(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        filename = build_backend._write_wheel(tmp.name, editable=False)
        with zipfile.ZipFile(Path(tmp.name) / filename) as archive:
            names = archive.namelist()
        self.assertTrue(any(n.endswith("_vendored/jieba/__init__.py") for n in names))
        self.assertTrue(any(n.endswith("_vendored/jieba/dict.txt") for n in names))

    def test_sdist_carries_vendored_jieba(self):
        import tempfile
        import tarfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        filename = build_backend._write_sdist(tmp.name)
        with tarfile.open(Path(tmp.name) / filename) as archive:
            names = archive.getnames()
        self.assertTrue(any("/libs/jieba/__init__.py" in n for n in names))


class RootShimTest(unittest.TestCase):
    """The unzipped-skill layout imports through the skill-root ``__init__.py``.

    That shim and the installed package re-export one list (``_api.py``); this
    test proves the shim resolves and exposes the identical public surface.
    """

    def test_root_shim_forwards_the_identical_public_api(self):
        import subprocess
        import sys as _sys

        from author_persona_skill import __all__ as package_exports

        code = (
            "import author_persona_skill as a;"
            "print(a.__file__);"
            "print(','.join(sorted(a.__all__)))"
        )
        result = subprocess.run(
            [_sys.executable, "-c", code],
            capture_output=True, text=True, cwd=str(ROOT.parent),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        shim_path, exports = result.stdout.strip().splitlines()
        self.assertEqual(Path(shim_path).resolve(), (ROOT / "__init__.py").resolve())
        self.assertEqual(exports.split(","), sorted(package_exports))


class DocumentationContractTest(unittest.TestCase):
    """SKILL.md is the entry document; it must describe what the code does."""

    @classmethod
    def setUpClass(cls):
        cls.skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.manifest = (ROOT / "manifest.yaml").read_text(encoding="utf-8")

    def test_documents_the_three_stage_flow_and_repair_loop(self):
        for stage in ("prepare_analysis", "finalize_analysis", "finalize"):
            self.assertIn(stage, self.skill)
        self.assertIn("修复", self.skill)

    def test_documents_every_public_function_in_manifest(self):
        from author_persona_skill import __all__

        for name in ("prepare_analysis", "finalize_analysis", "run_fidelity_check",
                     "analyze_style", "process_large_file"):
            self.assertIn(name, self.manifest)
        self.assertIn("prepare_analysis", __all__)

    def test_manifest_description_matches_skill_frontmatter(self):
        frontmatter = self.skill.split("---")[1]
        description = re.search(r"^description:\s*(.+)$", frontmatter, re.M).group(1).strip()
        raw_manifest = re.search(r'^description:\s*"(.*)"$', self.manifest, re.M).group(1)
        # The manifest quotes YAML double-quoted scalars (\"5\"), so decode them.
        manifest_desc = json.loads(f'"{raw_manifest}"')
        self.assertEqual(description, manifest_desc)

    def test_referenced_reference_files_exist(self):
        for match in re.finditer(r"references/([a-z\-]+\.md)", self.skill):
            self.assertTrue((ROOT / "references" / match.group(1)).is_file(), match.group(1))

    def test_docs_do_not_claim_stdlib_only(self):
        # 分词依赖已内嵌，文档不得再声称「纯标准库 / 无第三方依赖」。
        for path in ("SKILL.md", "README.md"):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("纯标准库", text, path)
            self.assertNotIn("无第三方依赖", text, path)
            self.assertNotIn("仅依赖 Python 标准库", text, path)

    def test_docs_declare_schema_six(self):
        for path in ("SKILL.md", "README.md", "references/report-schema.md"):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn('schema_version "5"', text, path)
            self.assertIn('schema_version "6"', text, path)

    def test_docs_mention_vendored_tokenizer(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("jieba", text)

    def test_skill_declares_independent_operation(self):
        """本技能必须能独立运行、独立发布，不得把别的技能写成前提。

        曾出现「两仓版本对齐（发布要求）」这类表述，把下游读取方是否跟进
        当作本技能的发布前置条件——两个技能各自独立，这是定位错误。
        """
        for path in ("SKILL.md", "README.md", "manifest.yaml"):
            text = (ROOT / path).read_text(encoding="utf-8")
            for banned in ("发布要求", "同批发布", "必须同步到 schema", "两仓"):
                self.assertNotIn(banned, text, f"{path} 含发布依赖表述：{banned}")
        # 描述里不得再声称「符合 novel-writer 契约」（本技能自有契约）。
        self.assertNotIn("符合 `novel-writer` 契约", self.skill)

    def test_documentation_lists_independent_operation(self):
        self.assertIn("独立运行", self.skill)

    def test_examples_use_canonical_sent_len_brackets(self):
        """范例的句长档位措辞必须等于 sent_len_bracket 的实产标签。

        阈值曾在三处散落，收敛为 SENT_LEN_BRACKETS 单一表后，范例沿用旧措辞
        就会与实际产物对不上——文档是用户唯一的对照系，必须钉住。
        """
        from author_persona_skill.analyzers.low_level import (
            SENT_LEN_BRACKETS, sent_len_bracket)

        for name in ("xuanhuan_style_report.md", "historical_style_report.md"):
            text = (ROOT / "assets" / "examples" / name).read_text(encoding="utf-8")
            match = re.search(r"平均句长\s*([\d.]+)\s*字.*?句长分档属于“([^”]+)”", text, re.S)
            self.assertIsNotNone(match, f"{name} 未找到句长分档句")
            avg = float(match.group(1))
            stated = match.group(2).replace("（", "(").replace("）", ")")
            self.assertEqual(
                stated, sent_len_bracket(avg),
                f"{name}: 档位措辞与 sent_len_bracket 不一致")

        # 标签表本身必须是单一来源且覆盖全区间（含最小值与超长）
        self.assertTrue(SENT_LEN_BRACKETS[-1][0] is None)
        self.assertEqual(sent_len_bracket(0), SENT_LEN_BRACKETS[0][1])
        self.assertEqual(sent_len_bracket(999), SENT_LEN_BRACKETS[-1][1])

    def test_manifest_block_count_matches_analyzer(self):
        """manifest 写的「N 个数据块」必须等于 StyleAnalyzer 实产键数。

        v10 曾声称「17 dimensions」而实返 11 键；改为写实数并由本用例钉住。
        """
        from tests import _fixtures as fx

        actual = len(fx.prepared(key="blocks")["quantitative_features"])
        manifest = (ROOT / "manifest.yaml").read_text(encoding="utf-8")
        match = re.search(r"共 (\d+) 个数据块", manifest)
        self.assertIsNotNone(match, "manifest 未声明数据块数量")
        self.assertEqual(int(match.group(1)), actual)

    def test_example_appendix_b_is_reproducible(self):
        """范例附录 B 的可读性数值必须能由同一表的句长/词长/复杂词比复算。

        本轮修复前，范例写着 FK 84.0、杨承淑 14.1，而它自己声明的输入
        （句长 24.2、复杂词比 0.2418）按公式推不出这两个数——公开产物不得
        包含无法复算的数字。
        """
        for name in ("historical_style_report.md", "xuanhuan_style_report.md"):
            text = (ROOT / "assets" / "examples" / name).read_text(encoding="utf-8")
            block = text.split("### B.1 可读性与词汇丰富度", 1)[1].split("### B.2", 1)[0]

            def grab(label):
                m = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*([\d.]+)\s*\|", block)
                self.assertIsNotNone(m, f"{name}: 缺少 {label}")
                return float(m.group(1))

            sl = grab("平均句长（字）")
            wl = grab("平均词长（字）")
            cr = grab("复杂词比（≥4 字，同 B.3「四字及以上比」）")
            self.assertAlmostEqual(grab("杨承淑指数"), round(0.4 * (sl + 100 * cr), 2),
                                   delta=0.02, msg=name)
            self.assertAlmostEqual(
                grab("Flesch-Kincaid"),
                round(max(0.0, 0.39 * sl + 11.8 * wl - 15.59), 2), delta=0.02, msg=name)
            self.assertAlmostEqual(
                grab("Gunning-Fog"), round(0.4 * (sl / wl + 100 * cr), 2),
                delta=0.02, msg=name)
            self.assertAlmostEqual(
                grab("SMOG"), round(1.043 * (cr * sl / wl) ** 0.5 + 3.1291, 2),
                delta=0.02, msg=name)

    def test_fidelity_profile_count_matches_docs(self):
        """fidelity.md 标的 profile 数必须等于代码里实际分支数。"""
        import inspect

        from author_persona_skill.fidelity.fidelity_check import evaluate_card_in_text

        src = inspect.getsource(evaluate_card_in_text)
        profiles = set(re.findall(r'profile = "([a-z_]+)"', src))
        doc = (ROOT / "references" / "fidelity.md").read_text(encoding="utf-8")
        match = re.search(r"可自动检测的技法范围（(\d+) 类 profile）", doc)
        self.assertIsNotNone(match, "fidelity.md 未声明 profile 数量")
        self.assertEqual(int(match.group(1)), len(profiles), sorted(profiles))


if __name__ == "__main__":
    unittest.main()
