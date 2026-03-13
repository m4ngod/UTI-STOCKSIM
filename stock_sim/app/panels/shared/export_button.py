"""ExportButton 统一导出逻辑组件 (Spec Task 31)

职责 (R10):
- 封装 ExportService 导出调用
- 注入 snapshot_id (由 ExportService 的 snapshot_id_provider 或 meta 覆盖)
- 保证导出列顺序与当前表格 columns 顺序一致

设计:
- 纯逻辑 (非 UI), 可被任意面板复用: 传入 rows(list[dict]) + columns(list[str])
- 提供 state 查询最近一次导出结果/错误
- 可扩展: 支持 include_extra_columns=True 时将未在 columns 中出现的字段追加在末尾

API:
export(rows, columns, *, fmt='csv', meta=None, file_path=None, include_extra_columns=False) -> str | raises
get_state() -> {last_path,last_error,last_snapshot_id,last_format,last_rows,last_meta}
clear_last()

指标(可选): export_button_start / export_button_success / export_button_fail
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional, Iterable
from threading import RLock

from app.services.export_service import ExportService, ExportServiceError

try:  # metrics 可选
    from observability.metrics import metrics
except Exception:  # pragma: no cover
    class _Dummy:
        def inc(self, *a, **kw):
            pass
    metrics = _Dummy()

__all__ = ["ExportButton"]

class ExportButton:
    def __init__(self, service: ExportService, *, default_format: str = 'csv'):
        self._svc = service
        self._default_format = default_format
        self._lock = RLock()
        self._last_path: Optional[str] = None
        self._last_error: Optional[str] = None
        self._last_snapshot_id: Optional[str] = None
        self._last_format: Optional[str] = None
        self._last_rows: int = 0
        self._last_meta: Dict[str, Any] | None = None

    # ------------- Public API -------------
    def export(self, rows: Iterable[Dict[str, Any]], columns: List[str], *, fmt: str | None = None,
               meta: Optional[Dict[str, Any]] = None, file_path: str | None = None,
               include_extra_columns: bool = False) -> str:
        fmt_real = (fmt or self._default_format).lower()
        metrics.inc('export_button_start')
        meta_use: Dict[str, Any] = dict(meta) if meta else {}
        rows_list = list(rows)
        ordered_rows = self._reorder(rows_list, columns, include_extra_columns=include_extra_columns)
        try:
            path = self._svc.export(fmt_real, ordered_rows, meta_use, file_path=file_path)
            # ExportService 会在 meta_use 中填充 snapshot_id
            snapshot_id = meta_use.get('snapshot_id')
            with self._lock:
                self._last_path = path
                self._last_error = None
                self._last_snapshot_id = snapshot_id
                self._last_format = fmt_real
                self._last_rows = len(ordered_rows)
                self._last_meta = meta_use
            metrics.inc('export_button_success')
            return path
        except ExportServiceError as e:
            with self._lock:
                self._last_error = e.code
            metrics.inc('export_button_fail')
            raise
        except Exception:
            with self._lock:
                self._last_error = 'UNKNOWN'
            metrics.inc('export_button_fail')
            raise

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'last_path': self._last_path,
                'last_error': self._last_error,
                'last_snapshot_id': self._last_snapshot_id,
                'last_format': self._last_format,
                'last_rows': self._last_rows,
                'last_meta': dict(self._last_meta) if self._last_meta else None,
            }

    def clear_last(self):
        with self._lock:
            self._last_path = None
            self._last_error = None
            self._last_snapshot_id = None
            self._last_format = None
            self._last_rows = 0
            self._last_meta = None

    # ------------- Internal -------------
    def _reorder(self, rows: List[Dict[str, Any]], columns: List[str], *, include_extra_columns: bool) -> List[Dict[str, Any]]:
        col_set = list(columns)
        if include_extra_columns:
            # 追加未在 columns 中出现的字段 (按首次出现顺序)
            seen = set(col_set)
            for r in rows:
                for k in r.keys():
                    if k not in seen:
                        seen.add(k)
                        col_set.append(k)
        out: List[Dict[str, Any]] = []
        for r in rows:
            new_r: Dict[str, Any] = {}
            for c in col_set:
                if c in r:
                    new_r[c] = r[c]
                else:
                    new_r[c] = None  # 缺失列填 None
            out.append(new_r)
        return out

