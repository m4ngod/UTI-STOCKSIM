from app.services.verification_report import generate_verification_report


def test_verification_report_match():
    expected = {"a": 1, "b": 2, "c": 3}
    actual = {"a": 1, "b": 2, "c": 3}
    report = generate_verification_report(expected, actual)
    assert report.ok is True
    assert len(report.issues) == 0


def test_verification_report_mismatch_multi_types():
    # diff: b, extra: c, missing: d
    expected = {"a": 1, "b": 2, "d": 5}
    actual = {"a": 1, "b": 3, "c": 9}
    report = generate_verification_report(expected, actual)
    assert report.ok is False
    # b diff, c extra, d missing -> 3 issues
    assert len(report.issues) == 3
    kinds = {i.field: i.kind for i in report.issues}
    assert kinds["b"] == "diff"
    assert kinds["c"] == "extra"
    assert kinds["d"] == "missing"

