import json

import pytest

from app.services.evidence_core import (
    CALIBRATION_TARGET_BANDS_SCHEMA_VERSION,
    P0_CALIBRATION_METRICS,
    load_calibration_target_bands,
)


def test_loads_valid_target_bands_from_config():
    target_bands = load_calibration_target_bands()

    assert target_bands["schema_version"] == CALIBRATION_TARGET_BANDS_SCHEMA_VERSION
    assert target_bands["pass_level"] == "engineering_pass"
    assert target_bands["research_pass"] is False
    assert target_bands["metric_names"] == P0_CALIBRATION_METRICS
    assert set(target_bands["target_bands"]) == set(P0_CALIBRATION_METRICS)
    assert set(target_bands["bands"]) == set(P0_CALIBRATION_METRICS)
    assert target_bands["target_bands"]["spread"]["required"] is True
    assert target_bands["bands"]["spread"]["min"] == target_bands["target_bands"]["spread"]["target_min"]


def test_rejects_missing_required_metric(tmp_path):
    payload = load_calibration_target_bands()
    payload["target_bands"].pop("spread")
    path = tmp_path / "bands.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required P0 metrics: spread"):
        load_calibration_target_bands(path)


def test_rejects_invalid_band_range(tmp_path):
    payload = load_calibration_target_bands()
    payload["target_bands"]["spread"]["target_min"] = 2.0
    payload["target_bands"]["spread"]["target_max"] = 1.0
    path = tmp_path / "bands.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="spread target_min must be <= target_max"):
        load_calibration_target_bands(path)


def test_rejects_missing_band_field_with_clear_error(tmp_path):
    payload = load_calibration_target_bands()
    payload["target_bands"]["spread"].pop("description")
    path = tmp_path / "bands.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="spread missing fields: description"):
        load_calibration_target_bands(path)
