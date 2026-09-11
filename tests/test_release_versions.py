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


if __name__ == "__main__":
    unittest.main()
