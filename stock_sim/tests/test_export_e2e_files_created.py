import os
import pytest

from app.services.export_service import ExportService, ExportServiceError


def test_export_e2e_csv_creates_file(tmp_path):
    svc = ExportService()
    meta = {"source": "e2e"}
    rows = [
        {"a": 1, "b": "x"},
        {"a": 2, "b": "y"},
    ]
    # 不带扩展名, 自动补 .csv
    out_path = svc.export("csv", rows, meta, file_path=tmp_path / "snapshot_export")
    assert out_path.endswith(".csv")
    assert os.path.isfile(out_path)
    assert os.path.getsize(out_path) > 0


def test_export_e2e_excel_creates_file_if_supported(tmp_path):
    svc = ExportService()
    meta = {"source": "e2e"}
    rows = [
        {"x": 10, "y": 20},
        {"x": 30, "y": 40},
    ]
    try:
        # excel / xlsx 均映射到 xlsx 输出
        out_path = svc.export("excel", rows, meta, file_path=tmp_path / "snapshot_export_xlsx")
    except ExportServiceError as e:
        # 环境缺失 pandas & openpyxl 时允许跳过
        if e.code == "PANDAS_MISSING":
            pytest.skip("excel export dependencies missing (pandas/openpyxl)")
        raise
    assert out_path.endswith(".xlsx")
    assert os.path.isfile(out_path)
    assert os.path.getsize(out_path) > 0

