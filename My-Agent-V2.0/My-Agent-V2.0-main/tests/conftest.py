"""conftest.py — 测试间模块隔离（防止 mock 泄漏）"""

import sys
import pytest


@pytest.fixture(autouse=True)
def _isolate_modules():
    """每个测试函数前后保护 sys.modules 不被永久污染"""
    before = dict(sys.modules)
    yield
    # 恢复：把被 mock 替换的模块还原
    for key in list(sys.modules.keys()):
        if key in before:
            # 如果测试中被替换成了 MagicMock，恢复原值
            from unittest.mock import MagicMock
            if isinstance(sys.modules.get(key), MagicMock) and not isinstance(before.get(key), MagicMock):
                sys.modules[key] = before[key]
        else:
            # 测试中新创建的模块（如 mock），测试后移除
            from unittest.mock import MagicMock
            if isinstance(sys.modules.get(key), MagicMock):
                sys.modules.pop(key, None)
