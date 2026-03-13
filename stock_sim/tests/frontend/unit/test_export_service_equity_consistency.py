import os
import pytest
from app.services.export_service import ExportService, ExportServiceError

def test_export_equity_consistency_pass(tmp_path):
    svc = ExportService()
    meta = {"snapshot_id": "sid-pass", "baseline_equity": 100000.0}
    # 差异 5 (0.005%) < 0.01%
    data = [{"equity": 100005.0, "snapshot_id": "sid-pass"}]
    path = svc.export("csv", data, meta, file_path=tmp_path/"eq_ok")
    assert os.path.isfile(path)


def test_export_equity_consistency_fail(tmp_path):
    svc = ExportService()
    meta = {"snapshot_id": "sid-fail", "baseline_equity": 100000.0}
    # 差异 20 (0.02%) > 0.01%
    data = [{"equity": 100020.0, "snapshot_id": "sid-fail"}]
    with pytest.raises(ExportServiceError) as e:
        svc.export("csv", data, meta, file_path=tmp_path/"eq_bad")
    assert e.value.code == "EQUITY_INCONSISTENT"

