#!/usr/bin/env python3
"""Build a deterministic source archive without caches or local artifacts."""
from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from pathlib import Path

EXCLUDED_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_PARTS = {"tests", "test", ".zcode"}
# build_backend.py must ship alongside pyproject.toml: the [build-system]
# table points at it via backend-path = ["."], so an archive carrying the
# pyproject without the backend cannot be installed at all.
INCLUDE_ROOTS = (
    "assets",
    "references",
    "scripts",
    "manifest.yaml",
    "SKILL.md",
    "pyproject.toml",
    "build_backend.py",
    "__init__.py",  # skill 根入口 shim：解压后 import author_persona_skill 需要它
    "LICENSE",      # 许可正文，随发布包分发
)


def should_include(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in EXCLUDED_NAMES or part in EXCLUDED_PARTS for part in rel.parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    return True


def build_archive(source: Path, output: Path) -> dict[str, object]:
    source = source.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    _assert_version_consistency(source)
    files = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for root_name in INCLUDE_ROOTS:
            candidate = source / root_name
            if not candidate.exists():
                continue
            candidates = [candidate] if candidate.is_file() else sorted(candidate.rglob("*"))
            for path in candidates:
                if path.is_file() and should_include(path, source):
                    rel = Path("author_persona_skill") / path.relative_to(source)
                    archive.write(path, rel.as_posix())
                    files.append(rel.as_posix())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {"output": str(output), "sha256": digest, "files": files}


_VERSION_FILE_RE = re.compile(r'^VERSION = "([^"]+)"', re.M)


def _pyproject_version(source: Path):
    import tomllib

    path = source / "pyproject.toml"
    if not path.exists():
        return None
    return str(tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"])


def _first_match(text: str, pattern):
    match = pattern.search(text)
    return match.group(1) if match else None


def _assert_version_consistency(source: Path) -> None:
    """pyproject.toml 是唯一权威；其余各声明处必须与它一致。

    刻意按文件清单枚举而不是全库 grep：tests/ 下测试 docstring 中的版本字样
    属于测试内容本身，不参与跨文件版本一致性校验。
    """
    version = _pyproject_version(source)
    if version is None:
        return
    mismatches = []

    def check(rel: str, declared, where: str) -> None:
        if declared is None:
            mismatches.append(f"{rel} 未找到版本声明（{where}），pyproject 为 {version}")
        elif declared != version:
            mismatches.append(f"{rel} 声明 {declared}，pyproject 为 {version}（{where}）")

    manifest_path = source / "manifest.yaml"
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("version:"):
                check("manifest.yaml", line.split(":", 1)[1].strip().strip('"'), "version 字段")

    skill_path = source / "SKILL.md"
    if skill_path.exists():
        lines = skill_path.read_text(encoding="utf-8").splitlines()
        frontmatter = "\n".join(lines[:15])
        version_match = re.search(r"^(?:version|  version):\s*[\"']?([^\"'\s]+)", frontmatter, re.M)
        check("SKILL.md", version_match.group(1) if version_match else None, "frontmatter")


    # 安全网：源码树的 _version.py 不应带烧录值（烧录只发生在 wheel 内）
    version_py = source / "scripts" / "author_persona_skill" / "_version.py"
    if version_py.exists():
        burned = _first_match(version_py.read_text(encoding="utf-8"), _VERSION_FILE_RE)
        if burned is not None and burned != version:
            mismatches.append(
                f"_version.py 已被烧录为 {burned}，pyproject 为 {version}；"
                f"源码树应还原为 `VERSION = None  # __BURN_VERSION__`"
            )

    if mismatches:
        raise SystemExit("版本不一致，拒绝打包：\n  " + "\n  ".join(mismatches))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build a clean author-persona-skill zip")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    output = args.output
    if output is None:
        version = _pyproject_version(args.source) or "0.0.0"
        output = args.source / "dist" / f"author-persona-skill-{version}.zip"
    result = build_archive(args.source, output)
    print(f"output: {result['output']}")
    print(f"sha256: {result['sha256']}")
    print(f"files: {len(result['files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
