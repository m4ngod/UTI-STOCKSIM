# pytest: unit tests for i18n loader reload/fallback
from __future__ import annotations
import time
import importlib
import pytest

from app.i18n import loader as I18N


def test_reload_success_and_translate_formatting():
    # 成功切换到 zh_CN
    applied = I18N.reload("zh_CN")
    assert applied == "zh_CN"
    assert I18N.get_current_locale() == "zh_CN"
    # 格式化翻译
    out = I18N.translate("greet", name="Alice")
    assert out.startswith("你好")


def test_reload_nonexistent_fallback_to_en_and_missing_key_metrics():
    # 记录缺失计数与集合长度快照
    miss_before = I18N.metrics.counters.get("i18n_missing", 0)  # type: ignore[attr-defined]
    set_before_len = len(I18N.get_missing_keys())
    # 切换到不存在语言，预期回退到 en_US
    applied = I18N.reload("fr_FR")
    assert applied == "en_US"
    assert I18N.current_language() == "en_US"
    # 仅 en_US 中存在的键应返回英文
    assert I18N.translate("only.english") == "Only English"
    # 缺失键：返回 key 本身，缺失计数 +1，集合新增记录
    key = "not.exist.key"
    assert I18N.translate(key) == key
    miss_after = I18N.metrics.counters.get("i18n_missing", 0)  # type: ignore[attr-defined]
    assert miss_after >= miss_before + 1
    set_after = I18N.get_missing_keys()
    assert len(set_after) >= set_before_len + 1
    assert any(item.endswith(":" + key) for item in set_after)

