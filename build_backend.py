"""Tiny dependency-free PEP 517/660 backend for the standard-library package."""
from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable

NAME = "author-persona-skill"
DIST = "author_persona_skill"
ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = ROOT / "scripts" / "author_persona_skill"


def _load_pyproject() -> Dict[str, Any]:
    """Single source of truth for build metadata: pyproject.toml [project].

    Deliberately does not swallow errors: a missing version must fail the build
    rather than silently produce a wheel stamped with a made-up number.
    """
    import tomllib

    pyproj = ROOT / "pyproject.toml"
    return tomllib.loads(pyproj.read_text(encoding="utf-8")).get("project", {})


_proj = _load_pyproject()
try:
    VERSION = str(_proj["version"])
except KeyError as exc:  # 没有版本号就拒绝构建，而不是悄悄编一个
    raise RuntimeError("pyproject.toml 缺少 [project].version，拒绝构建") from exc
_SUMMARY = str(_proj.get("description", "脱敏、分层采样与可验证风格能力报告工具"))
_REQUIRES_PYTHON = str(_proj.get("requires-python", ">=3.10"))
_AUTHORS = [dict(item) for item in _proj.get("authors", [])]
_CLASSIFIERS = [str(item) for item in _proj.get("classifiers", [])]
_DEPENDENCIES = [str(item) for item in _proj.get("dependencies", [])]
_LICENSE = _proj.get("license")
_LICENSE_FILES = [str(item) for item in _proj.get("license-files", [])]
DIST_INFO = f"{DIST}-{VERSION}.dist-info"


def _metadata() -> str:
    # PEP 639：SPDX 短串要求 Metadata-Version 2.4 + License-Expression；
    # 旧式 { text = ... } 表则保持 2.1 + License: 自由文本。两条分支都保留，
    # 这样将来把 pyproject 改回旧式写法也不会构建失败。
    spdx = _LICENSE if isinstance(_LICENSE, str) else None
    legacy = str(_LICENSE.get("text", "")) if isinstance(_LICENSE, dict) else ""
    lines = [
        "Metadata-Version: 2.4" if spdx else "Metadata-Version: 2.1",
        f"Name: {NAME}",
        f"Version: {VERSION}",
        f"Summary: {_SUMMARY}",
    ]
    for author in _AUTHORS:
        name = str(author.get("name", "")).strip()
        email = str(author.get("email", "")).strip()
        if name:
            lines.append(f"Author: {name}")
        if email:
            lines.append(f"Author-email: {name} <{email}>" if name else f"Author-email: {email}")
    if spdx:
        lines.append(f"License-Expression: {spdx}")
        for rel in _LICENSE_FILES:
            lines.append(f"License-File: {rel}")
    elif legacy:
        lines.append(f"License: {legacy}")
    lines.append(f"Requires-Python: {_REQUIRES_PYTHON}")
    for classifier in _CLASSIFIERS:
        lines.append(f"Classifier: {classifier}")
    for requirement in _DEPENDENCIES:
        lines.append(f"Requires-Dist: {requirement}")
    return "\n".join(lines) + "\n"


def _wheel_metadata() -> str:
    return "Wheel-Version: 1.0\nGenerator: author-persona-build-backend\nRoot-Is-Purelib: true\nTag: py3-none-any\n"


def _entry_points() -> str:
    return "[console_scripts]\nauthor-persona-skill = author_persona_skill.cli:main\n"


def _hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _dist_info_files() -> Dict[str, bytes]:
    files = {
        f"{DIST_INFO}/METADATA": _metadata().encode("utf-8"),
        f"{DIST_INFO}/WHEEL": _wheel_metadata().encode("utf-8"),
        f"{DIST_INFO}/entry_points.txt": _entry_points().encode("utf-8"),
    }
    # PEP 639 惯例：许可证正文随 dist-info 分发。
    # _package_files 只 rglob 包目录，不会带上仓库根的 LICENSE。
    if (ROOT / "LICENSE").is_file():
        files[f"{DIST_INFO}/LICENSE"] = (ROOT / "LICENSE").read_bytes()
    return files


def _package_files() -> Iterable[tuple[str, bytes]]:
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        yield (f"author_persona_skill/{path.relative_to(PACKAGE_ROOT).as_posix()}", path.read_bytes())


#: Data suffixes carried by the vendored libraries (jieba dictionary and model
#: modules). Kept explicit so a stray .pyc or editor backup can never ship.
_VENDOR_SUFFIXES = {".py", ".txt", ".json"}
_VENDOR_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache"}


def _vendored_lib_files() -> Iterable[tuple[str, bytes]]:
    """Map ``libs/`` into ``author_persona_skill/_vendored/`` for the wheel.

    Namespacing the vendored copy under our own package is deliberate: a
    top-level ``jieba`` in site-packages would shadow (or be shadowed by) a real
    jieba install depending on sys.path order. ``_vendor.find_libs_path`` probes
    this package-local location first.
    """
    libs_root = ROOT / "libs"
    if not libs_root.is_dir():
        return
    for path in sorted(libs_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(libs_root)
        if set(rel.parts) & _VENDOR_EXCLUDE_PARTS:
            continue
        if path.suffix not in _VENDOR_SUFFIXES and path.name != "LICENSE":
            continue
        yield (f"author_persona_skill/_vendored/{rel.as_posix()}", path.read_bytes())


_BURN_MARKER_RE = re.compile(r"^VERSION = None  # __BURN_VERSION__$", re.M)


def _burned_version_py() -> bytes:
    """Replace the burn marker in _version.py with the literal version string.

    Only used for non-editable builds: a wheel ships no pyproject.toml, so the
    dynamic lookup would fail and every installed copy would report the
    unresolved placeholder instead of the real version.
    """
    source = (PACKAGE_ROOT / "_version.py").read_text(encoding="utf-8")
    burned, count = _BURN_MARKER_RE.subn(f'VERSION = "{VERSION}"', source)
    if count != 1:
        raise RuntimeError(
            "_version.py 的烧录标记缺失或不唯一（期望恰好 1 处 "
            "'VERSION = None  # __BURN_VERSION__'），拒绝构建"
        )
    return burned.encode("utf-8")


def _write_wheel(wheel_directory: str | os.PathLike[str], editable: bool) -> str:
    wheel_dir = Path(wheel_directory)
    wheel_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{DIST}-{VERSION}-py3-none-any.whl"
    output = wheel_dir / filename
    files: Dict[str, bytes] = {}
    if editable:
        # editable 只写 .pth 指向源码树，不复制也不改写任何源文件 —— 源码树零污染。
        files["author_persona_skill_editable.pth"] = (str(ROOT / "scripts") + "\n").encode("utf-8")
    else:
        files.update(dict(_package_files()))
        # 内嵌 jieba 随 wheel 分发，命名空间在包内避免与真实 jieba 互相遮蔽。
        files.update(dict(_vendored_lib_files()))
        # 必须放在 update 之后：覆盖 _package_files 收集到的源码树版本。
        files["author_persona_skill/_version.py"] = _burned_version_py()
    files.update(_dist_info_files())

    records = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
            records.append(f"{name},{_hash(data)},{len(data)}")
        records.append(f"{DIST_INFO}/RECORD,,")
        archive.writestr(f"{DIST_INFO}/RECORD", ("\n".join(records) + "\n").encode("utf-8"))
    return filename


SDIST_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".git", ".zcode"}
SDIST_EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _sdist_files() -> Iterable[tuple[str, bytes]]:
    """An sdist must carry pyproject.toml and build_backend.py.

    ``[build-system] backend-path = ["."]`` means that without the backend, an
    unpacked sdist cannot be built at all — this is the minimum viable set.
    """
    prefix = f"{DIST}-{VERSION}"
    yield (f"{prefix}/PKG-INFO", _metadata().encode("utf-8"))
    for name in ("pyproject.toml", "build_backend.py", "SKILL.md", "manifest.yaml", "LICENSE"):
        path = ROOT / name
        if path.is_file():
            yield (f"{prefix}/{name}", path.read_bytes())
    # libs/ carries the vendored jieba；没有它 sdist 装出来的包无法分词，
    # 低层测量会静默降级为启发式。
    for rel in ("scripts", "assets", "references", "libs"):
        base = ROOT / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel_path = path.relative_to(ROOT)
            if set(rel_path.parts) & SDIST_EXCLUDE_PARTS:
                continue
            if path.suffix in SDIST_EXCLUDE_SUFFIXES:
                continue
            yield (f"{prefix}/{rel_path.as_posix()}", path.read_bytes())


def _write_sdist(sdist_directory: str | os.PathLike[str]) -> str:
    sdist_dir = Path(sdist_directory)
    sdist_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{DIST}-{VERSION}.tar.gz"
    output = sdist_dir / filename
    with tarfile.open(output, "w:gz") as archive:
        for name, data in sorted(_sdist_files()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0  # 确定性：固定时间戳
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    return filename


def get_requires_for_build_wheel(config_settings: Any = None) -> list[str]:
    return []


def get_requires_for_build_editable(config_settings: Any = None) -> list[str]:
    return []


def get_requires_for_build_sdist(config_settings: Any = None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(metadata_directory: str, config_settings: Any = None) -> str:
    target = Path(metadata_directory) / DIST_INFO
    target.mkdir(parents=True, exist_ok=True)
    (target / "METADATA").write_text(_metadata(), encoding="utf-8")
    (target / "WHEEL").write_text(_wheel_metadata(), encoding="utf-8")
    (target / "entry_points.txt").write_text(_entry_points(), encoding="utf-8")
    return DIST_INFO


def prepare_metadata_for_build_editable(metadata_directory: str, config_settings: Any = None) -> str:
    return prepare_metadata_for_build_wheel(metadata_directory, config_settings)


def build_wheel(
    wheel_directory: str,
    config_settings: Any = None,
    metadata_directory: str | None = None,
) -> str:
    return _write_wheel(wheel_directory, editable=False)


def build_editable(
    wheel_directory: str,
    config_settings: Any = None,
    metadata_directory: str | None = None,
) -> str:
    return _write_wheel(wheel_directory, editable=True)


def build_sdist(sdist_directory: str, config_settings: Any = None) -> str:
    return _write_sdist(sdist_directory)
