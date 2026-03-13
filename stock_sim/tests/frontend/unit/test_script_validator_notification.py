from app.security.script_validator import ScriptValidator
from app.panels.shared.notifications import notification_center


def test_script_validation_violation_notification_dedup():
    notification_center.clear_all()
    v = ScriptValidator()
    code = "import os\nprint('x')"  # FORBIDDEN_IMPORT
    viol1 = v.validate_source(code)
    assert viol1, '应当有违规'
    notes = [n for n in notification_center.get_recent(10) if n.code == 'script_violation']
    assert len(notes) == 1
    data = notes[0].data
    assert data and 'code_excerpt' in data and 'violations' in data
    # 再次相同代码 -> 去重 (不新增)
    viol2 = v.validate_source(code)
    assert viol2
    notes2 = [n for n in notification_center.get_recent(10) if n.code == 'script_violation']
    assert len(notes2) == 1


def test_script_validation_exception_notification_once():
    notification_center.clear_all()
    v = ScriptValidator()
    bad_code = 'def oops(:\n    pass'  # 语法错误
    try:
        v.validate_source(bad_code)
    except Exception:
        pass
    notes = [n for n in notification_center.get_recent(10) if n.code == 'script_violation']
    assert len(notes) == 1
    assert notes[0].data['error_code'] == 'SYNTAX_ERROR'
    # 再次同样语法错误 -> 去重
    try:
        v.validate_source(bad_code)
    except Exception:
        pass
    notes2 = [n for n in notification_center.get_recent(10) if n.code == 'script_violation']
    assert len(notes2) == 1

