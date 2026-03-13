"""i18n Loader (Spec Task 17)

功能:
- lazy 加载语言 JSON (app/i18n/<lang>.json)
- 提供 translate(key, **kwargs) / t 别名
- set_language() 切换当前语言, 未加载时自动加载
- 缺失 key: metrics.i18n_missing++ 并记录在 _missing_keys 集合
- 支持占位符格式化: "Hello {name}" 传参 translate("greet", name="Alice")
- fallback: 先尝试当前语言; 若缺失则尝试主回退 zh_CN; 若仍缺失则尝试 en_US; 最后返回 key 本身

满足需求: R11 AC1/2, R6 AC1
"""
from __future__ import annotations
import json
import os
from threading import RLock
from typing import Dict, Any, Set
import time
from observability.metrics import metrics

_TRANSLATIONS: Dict[str, Dict[str, str]] = {}
_current_language: str = "zh_CN"  # 默认中文
_lock = RLock()
_missing_keys: Set[str] = set()  # 记录 language:key
_BASE_DIR = os.path.dirname(__file__)
_DEFAULT_FALLBACK = "zh_CN"  # 主回退改为中文
_SECONDARY_FALLBACK = "en_US"  # 次级回退英文

class I18NError(Exception):
    pass

def load_language(lang: str, *, force: bool = False) -> None:
    """加载指定语言 JSON。
    force=True 时重新加载。
    """
    with _lock:
        if not force and lang in _TRANSLATIONS:
            return
        path = os.path.join(_BASE_DIR, f"{lang}.json")
        if not os.path.exists(path):
            raise I18NError(f"language file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise I18NError(f"invalid json for {lang}: {e}") from e
            if not isinstance(data, dict):
                raise I18NError(f"language root must be object: {lang}")
            # 不做嵌套展开，按点号访问
            _TRANSLATIONS[lang] = data

def current_language() -> str:
    return _current_language

def get_current_locale() -> str:
    """别名：当前语言代码（locale）。"""
    return current_language()

def set_language(lang: str) -> None:
    load_language(lang)  # lazy
    global _current_language
    with _lock:
        _current_language = lang

def reload(locale: str) -> str:
    """重新加载并切换到指定 locale。
    返回最终生效的 locale（若失败则回退到默认语言，或保持原值）。
    """
    t0 = time.perf_counter()
    applied = None
    try:
        load_language(locale, force=True)
        set_language(locale)
        applied = locale
    except Exception:
        # 回退到默认
        try:
            load_language(_DEFAULT_FALLBACK, force=False)
            set_language(_DEFAULT_FALLBACK)
            applied = _DEFAULT_FALLBACK
        except Exception:
            # 连默认也不可用：保持现状
            applied = current_language()
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        metrics.add_timing('i18n_switch_ms', dt_ms)
    return applied  # type: ignore[return-value]

def _get(lang: str, key: str) -> str | None:
    table = _TRANSLATIONS.get(lang)
    if not table:
        return None
    # 支持点号访问嵌套
    if key in table:
        return table[key]
    if "." in key:
        cur: Any = table
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        if isinstance(cur, str):
            return cur
    return None

def translate(key: str, **kwargs) -> str:
    lang = current_language()
    # 确保已加载当前语言
    if lang not in _TRANSLATIONS:
        try:
            load_language(lang)
        except I18NError:
            # 回退到主默认
            if _DEFAULT_FALLBACK not in _TRANSLATIONS:
                try:
                    load_language(_DEFAULT_FALLBACK)
                except Exception:
                    pass
            lang = _DEFAULT_FALLBACK
    # 1) 当前语言
    text = _get(lang, key)
    # 2) 主回退 zh_CN
    if text is None and lang != _DEFAULT_FALLBACK:
        if _DEFAULT_FALLBACK not in _TRANSLATIONS:
            try:
                load_language(_DEFAULT_FALLBACK)
            except Exception:
                pass
        text = _get(_DEFAULT_FALLBACK, key)
    # 3) 次回退 en_US（兼容只提供英文的键）
    if text is None and _SECONDARY_FALLBACK != lang:
        if _SECONDARY_FALLBACK not in _TRANSLATIONS:
            try:
                load_language(_SECONDARY_FALLBACK)
            except Exception:
                pass
        text = _get(_SECONDARY_FALLBACK, key)
    # 4) 缺失统计
    if text is None:
        miss_id = f"{lang}:{key}"
        with _lock:
            _missing_keys.add(miss_id)
        metrics.inc("i18n_missing", 1)
        return key  # 返回 key 本身
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            # 格式化失败也计一次错误
            metrics.inc("i18n_format_error", 1)
    return text

def t(key: str, **kwargs) -> str:
    return translate(key, **kwargs)

def get_missing_keys() -> Set[str]:
    with _lock:
        return set(_missing_keys)

__all__ = [
    "translate", "t", "set_language", "current_language", "load_language", "get_missing_keys", "I18NError", "reload", "get_current_locale"
]
