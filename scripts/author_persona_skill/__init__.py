# -*- coding: utf-8 -*-
"""Author Persona Skill Package API."""
from __future__ import annotations

# 必须最先导入：_version 只依赖标准库、不 import 包内任何模块，因此能安全地在
# pipeline 之前加载。report/renderer.py 会在包 __init__ 仍在执行期间导入它
# （__init__ -> pipeline -> renderer），详见 _version.py 顶部的 CONTRACT。
from ._version import __version__

# 内嵌依赖（jieba）必须早于任何 analyzers 导入：分词与词性标注是低层测量的
# 前置能力。_vendor 同样只依赖标准库，可安全地在 _api 之前执行。
from ._vendor import ensure_libs_on_path as _ensure_libs_on_path

_ensure_libs_on_path()

# 公共接口清单在 _api.py 单一真源；根目录 shim 转发同一份。
from ._api import *  # noqa: E402,F401,F403
from ._api import __all__ as _API_EXPORTS  # noqa: E402

__all__ = ["__version__", *_API_EXPORTS]
