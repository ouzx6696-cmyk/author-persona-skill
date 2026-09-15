# -*- coding: utf-8 -*-
"""Author Persona Skill Root Entrypoint (unzipped-skill layout).

把技能目录本身放进 ``sys.path`` 的场景（例如解压后直接使用、或从仓库根导入）
会命中这个文件。它只做两件事：

1. 把 ``scripts/`` 加入 ``sys.path``；
2. 把 ``scripts/author_persona_skill`` 并入 ``__path__``，让
   ``author_persona_skill.pipeline`` 之类的子模块能被解析。

随后转发到 ``scripts/author_persona_skill/_api.py`` 的公共接口——导出清单只有一份。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _SKILL_DIR / "scripts"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Extend package __path__ so that submodules (e.g. author_persona_skill.pipeline) resolve properly
_SUBPKG_DIR = str(_SCRIPTS_DIR / "author_persona_skill")
if _SUBPKG_DIR not in __path__:
    __path__.append(_SUBPKG_DIR)

# 版本号的唯一来源。必须最先导入：_version 只依赖标准库、不 import 包内任何模块，
# 因此不会与半初始化的包 __init__ 形成循环导入。
from author_persona_skill._version import __version__  # noqa: E402

# 内嵌依赖（jieba）注入 sys.path。本 shim 布局下 skill 根目录就在 _SKILL_DIR，
# 因此 libs/ 与其同级；_vendor 会按候选清单自动定位，此处只需尽早调用。
from author_persona_skill._vendor import ensure_libs_on_path as _ensure_libs_on_path  # noqa: E402

_ensure_libs_on_path()

from author_persona_skill._api import *  # noqa: E402,F401,F403
from author_persona_skill._api import __all__ as _API_EXPORTS  # noqa: E402

__all__ = ["__version__", *_API_EXPORTS]
