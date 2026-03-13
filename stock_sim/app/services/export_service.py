"""ExportService (Spec Task 13 / Task 38 增量)

职责 (R10 AC1/2/3/4 初步):
- 导出结构化数据为 CSV / Excel (Excel 需要���选依赖 pandas)。
- 统一 snapshot_id 绑定: meta 中提供或通过 snapshot_id_provider 获取; 若数据行中包含 snapshot_id 字段则全部必须一致。
- 写入元数据行 (CSV 顶部首行注释; Excel 写 META sheet) —— 单测判定文件含元数据行。
- 记录指标: export_start / export_success / export_failure / export_csv_success / export_excel_success / export_ms。

后续 (Task 38) 还将扩展: 深拷贝缓存数据 / 账户与导出净值差异校验 (<0.01%)。

增量 (Task 38 已实现):
- 在 export() 内对 data 做深拷贝 (避免调用方后续修改影响已写出文件)
- 若 meta 提供 baseline_equity 且 rows 中存在 equity 字段, 校���相对差异 <0.0001 (0.01%)
  超出则抛出 ExportServiceError('EQUITY_INCONSISTENT') 并计数 metrics.export_equity_inconsistent
"""
from __future__ import annotations
from typing import Iterable, Any, Dict, List, Callable, Literal
import os
import time
from dataclasses import dataclass
import copy

from observability.metrics import metrics

try:  # 可选依赖
    import pandas as _pd  # type: ignore
except Exception:  # pragma: no cover - 未安装时走降级
    _pd = None  # type: ignore

# 新增 openpyxl 作为回退
try:  # pragma: no cover
    from openpyxl import Workbook as _OpenpyxlWorkbook  # type: ignore
except Exception:  # pragma: no cover
    _OpenpyxlWorkbook = None  # type: ignore

try:
    from pydantic import BaseModel  # type: ignore
except Exception:  # pragma: no cover
    class BaseModel:  # type: ignore
        pass

Format = Literal['csv', 'xlsx', 'excel']

class ExportServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

@dataclass
class _ExportResult:
    path: str
    rows: int
    snapshot_id: str

class ExportService:
    def __init__(self, *, snapshot_id_provider: Callable[[], str] | None = None):
        self._snapshot_id_provider = snapshot_id_provider

    # ---------------- Internal helpers ----------------
    def _resolve_snapshot_id(self, meta: Dict[str, Any]) -> str:
        if 'snapshot_id' in meta and meta['snapshot_id']:
            return str(meta['snapshot_id'])
        if self._snapshot_id_provider:
            sid = self._snapshot_id_provider()
        else:
            sid = f"snap-{int(time.time()*1000)}"
        meta['snapshot_id'] = sid
        return sid

    def _normalize_rows(self, data: Iterable[Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                rows.append(dict(item))
            elif isinstance(item, BaseModel):  # pydantic
                to_dict = getattr(item, 'dict', None) or getattr(item, 'model_dump', None)
                if callable(to_dict):
                    rows.append(to_dict())  # type: ignore[arg-type]
                else:  # pragma: no cover
                    rows.append(vars(item))
            else:
                if hasattr(item, '__dict__'):
                    rows.append(vars(item))
                else:
                    rows.append({'value': item})
        return rows

    def _validate_snapshot_ids(self, rows: List[Dict[str, Any]], snapshot_id: str):
        mismatches = [r.get('snapshot_id') for r in rows if r.get('snapshot_id') and r.get('snapshot_id') != snapshot_id]
        if mismatches:
            raise ExportServiceError('SNAPSHOT_ID_MISMATCH', 'data rows contain different snapshot_id')

    def _ensure_path(self, file_path: str | None, ext: str, snapshot_id: str) -> str:
        if file_path:
            if os.path.isdir(file_path):
                return os.path.join(file_path, f"export_{snapshot_id}.{ext}")
            base, suf = os.path.splitext(file_path)
            if not suf:
                return base + '.' + ext
            return file_path
        return f"export_{snapshot_id}.{ext}"

    # ---------------- Public API ----------------
    def export(self, fmt: Format, data: Iterable[Any], meta: Dict[str, Any], file_path: str | None = None) -> str:
        fmt_l = fmt.lower()
        if fmt_l not in ('csv', 'xlsx', 'excel'):
            raise ExportServiceError('INVALID_FORMAT', f'unsupported format: {fmt}')
        metrics.inc('export_start')
        start = time.perf_counter()
        # 深拷贝调用方数据 (Task 38)
        data_materialized = list(data)
        data_copied = [copy.deepcopy(d) for d in data_materialized]
        snapshot_id = self._resolve_snapshot_id(meta)
        rows = self._normalize_rows(data_copied)
        try:
            self._validate_snapshot_ids(rows, snapshot_id)
            self._check_equity_consistency(rows, meta)  # Task 38
            if fmt_l == 'csv':
                path = self._ensure_path(file_path, 'csv', snapshot_id)
                self._write_csv(path, rows, meta)
                metrics.inc('export_csv_success')
            else:
                path = self._ensure_path(file_path, 'xlsx', snapshot_id)
                self._write_xlsx_with_fallback(path, rows, meta)
                metrics.inc('export_excel_success')
            metrics.inc('export_success')
        except ExportServiceError as e:
            if e.code == 'EQUITY_INCONSISTENT':
                metrics.inc('export_equity_inconsistent')
            metrics.inc('export_failure')
            raise
        except OSError as e:
            metrics.inc('export_failure')
            raise ExportServiceError('IO_ERROR', str(e)) from e
        finally:
            metrics.add_timing('export_ms', (time.perf_counter() - start) * 1000)
        return path

    # ---------------- Writers ----------------
    def _write_csv(self, path: str, rows: List[Dict[str, Any]], meta: Dict[str, Any]):
        header_keys: List[str] = []
        for r in rows:
            for k in r.keys():
                if k not in header_keys:
                    header_keys.append(k)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            meta_parts = [f"{k}={meta[k]}" for k in sorted(meta.keys())]
            f.write('# meta ' + ';'.join(meta_parts) + '\n')
            if header_keys:
                f.write(','.join(header_keys) + '\n')
                for r in rows:
                    vals = [self._format_csv_value(r.get(k)) for k in header_keys]
                    f.write(','.join(vals) + '\n')

    def _write_xlsx_with_fallback(self, path: str, rows: List[Dict[str, Any]], meta: Dict[str, Any]):  # pragma: no cover (依赖外部包)
        """优先使用 pandas+xlsxwriter; 若缺失则回退 openpyxl; 若均无 -> 抛 PANDAS_MISSING.
        META sheet: key,value 两列; DATA sheet: tabular rows.
        """
        # 1) pandas 路径
        if _pd is not None:
            try:
                self._write_excel_pandas(path, rows, meta)
                return
            except ModuleNotFoundError:  # xlsxwriter 缺失, 尝试 openpyxl
                pass
            except Exception:  # 其他 pandas 写入错误回退 openpyxl
                pass
        # 2) openpyxl 回退
        if _OpenpyxlWorkbook is not None:
            self._write_excel_openpyxl(path, rows, meta)
            return
        # 3) 均不可用
        raise ExportServiceError('PANDAS_MISSING', 'pandas/openpyxl not installed for excel export')

    def _write_excel_pandas(self, path: str, rows: List[Dict[str, Any]], meta: Dict[str, Any]):  # pragma: no cover
        assert _pd is not None
        df = _pd.DataFrame(rows)
        meta_df = _pd.DataFrame([(k, meta[k]) for k in sorted(meta.keys())], columns=['key', 'value'])
        with _pd.ExcelWriter(path, engine='xlsxwriter') as writer:  # type: ignore[arg-type]
            meta_df.to_excel(writer, sheet_name='META', index=False)
            df.to_excel(writer, sheet_name='DATA', index=False)

    def _write_excel_openpyxl(self, path: str, rows: List[Dict[str, Any]], meta: Dict[str, Any]):  # pragma: no cover
        wb = _OpenpyxlWorkbook()
        ws_meta = wb.active
        ws_meta.title = 'META'
        ws_meta.append(['key', 'value'])
        for k in sorted(meta.keys()):
            ws_meta.append([k, meta[k]])
        # DATA sheet
        ws_data = wb.create_sheet('DATA')
        # 生成 header 顺序
        header_keys: List[str] = []
        for r in rows:
            for k in r.keys():
                if k not in header_keys:
                    header_keys.append(k)
        if header_keys:
            ws_data.append(header_keys)
            for r in rows:
                ws_data.append([r.get(k, None) for k in header_keys])
        wb.save(path)

    def _write_excel(self, path: str, rows: List[Dict[str, Any]], meta: Dict[str, Any]):  # 保留旧接口 (不再直接调用)
        self._write_xlsx_with_fallback(path, rows, meta)

    def _format_csv_value(self, v: Any) -> str:
        if v is None:
            return ''
        if isinstance(v, (int, float)):
            return str(v)
        s = str(v)
        if any(c in s for c in [',', '\n', '\r', '"']):
            s = '"' + s.replace('"', '""') + '"'
        return s

    def _check_equity_consistency(self, rows: List[Dict[str, Any]], meta: Dict[str, Any]):
        """校验账���导出 equity 一致性 (<0.01%)。

        触发条件: meta 中含 baseline_equity 且 >0, 且 rows 至少一行包含 numeric equity。
        判定: abs(row_equity - baseline_equity) / baseline_equity < 0.0001
        否则抛出 ExportServiceError('EQUITY_INCONSISTENT').
        多行有 equity 时取第一行进行校验 (约定账户汇总行位于首行)。
        """
        baseline = meta.get('baseline_equity')
        if baseline is None:
            return
        try:
            baseline_f = float(baseline)
        except (TypeError, ValueError):  # 非数值忽略
            return
        if baseline_f <= 0:
            return
        target_equity = None
        for r in rows:
            eq = r.get('equity')
            if isinstance(eq, (int, float)):
                target_equity = float(eq)
                break
        if target_equity is None:
            return
        rel = abs(target_equity - baseline_f) / baseline_f
        if rel >= 0.0001:
            raise ExportServiceError('EQUITY_INCONSISTENT', f'equity diff {rel:.6f} >= 0.0001')

__all__ = ['ExportService', 'ExportServiceError']
