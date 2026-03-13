import os
import pytest

from app.services.export_service import ExportService, ExportServiceError
from observability.metrics import metrics


def test_export_csv_meta_and_metrics(tmp_path):
    es = ExportService()
    meta = {"snapshot_id": "sid1", "source": "unit"}
    data = [
        {"a": 1, "b": "x", "snapshot_id": "sid1"},
        {"a": 2, "b": "y", "snapshot_id": "sid1"},
    ]
    base_start = metrics.counters.get("export_start", 0)
    base_success = metrics.counters.get("export_success", 0)
    path = es.export("csv", data, meta, file_path=tmp_path / "out")  # 无扩展名自动补
    assert os.path.isfile(path)
    assert path.endswith(".csv")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[0].startswith("# meta ")
    assert "snapshot_id=sid1" in lines[0]
    # header 顺序包含字段
    assert lines[1].startswith("a,b,snapshot_id")
    # metrics
    assert metrics.counters.get("export_start", 0) == base_start + 1
    assert metrics.counters.get("export_success", 0) == base_success + 1
    assert metrics.counters.get("export_csv_success", 0) >= 1


def test_export_snapshot_id_mismatch(tmp_path):
    es = ExportService()
    meta = {"snapshot_id": "sid1"}
    data = [
        {"a": 1, "snapshot_id": "sid1"},
        {"a": 2, "snapshot_id": "sid2"},  # mismatch
    ]
    base_fail = metrics.counters.get("export_failure", 0)
    with pytest.raises(ExportServiceError) as e:
        es.export("csv", data, meta, file_path=tmp_path / "mismatch.csv")
    assert e.value.code == "SNAPSHOT_ID_MISMATCH"
    assert metrics.counters.get("export_failure", 0) == base_fail + 1


def test_export_excel_requires_pandas(tmp_path):
    es = ExportService()
    meta = {"snapshot_id": "sid1"}
    data = [{"x": 1, "snapshot_id": "sid1"}]
    # 若未安装 pandas 应抛出 PANDAS_MISSING; 若已安装则成功 (不强制依赖环境)
    try:
        path = es.export("excel", data, meta, file_path=tmp_path / "excel_export")
        # 若成功应生成文件
        assert os.path.isfile(path)
        assert path.endswith(".xlsx")
    except ExportServiceError as e:
        assert e.code == "PANDAS_MISSING"
