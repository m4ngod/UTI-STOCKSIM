import os
import tempfile
import pytest

from app.security.script_validator import ScriptValidator, ScriptValidationError
from observability.metrics import metrics


def test_forbidden_import_violation():
    v = ScriptValidator()
    base_start = metrics.counters.get("script_validate_start", 0)
    base_fail = metrics.counters.get("script_validate_fail", 0)
    code = "import os\nprint('hi')"
    violations = v.validate_source(code)
    assert any(x.code == 'FORBIDDEN_IMPORT' for x in violations)
    assert metrics.counters.get("script_validate_start", 0) == base_start + 1
    assert metrics.counters.get("script_validate_fail", 0) == base_fail + 1  # 有违规


def test_forbidden_attribute_violation():
    v = ScriptValidator()
    code = "__import__('math')\n"
    violations = v.validate_source(code)
    assert any(x.code == 'FORBIDDEN_ATTR' for x in violations)


def test_whitelist_import_rule():
    v = ScriptValidator(whitelist=['math'])
    code = "import math, json\n"
    violations = v.validate_source(code)
    assert any(x.code == 'IMPORT_NOT_WHITELISTED' and 'json' in x.message for x in violations)


def test_syntax_error():
    v = ScriptValidator()
    with pytest.raises(ScriptValidationError) as e:
        v.validate_source('def oops(:\n    pass')
    assert e.value.code == 'SYNTAX_ERROR'


def test_file_too_large(tmp_path):
    # 创建超过限制文件
    big_content = 'a' * 200
    path = tmp_path / 'big.py'
    path.write_text(big_content, encoding='utf-8')
    v = ScriptValidator(max_bytes=100)
    with pytest.raises(ScriptValidationError) as e:
        v.validate_file(str(path))
    assert e.value.code == 'FILE_TOO_LARGE'


def test_clean_script_ok():
    v = ScriptValidator(whitelist=['math'])
    base_ok = metrics.counters.get("script_validate_ok", 0)
    code = 'import math\nvalue = math.sqrt(4)\n'
    violations = v.validate_source(code)
    assert violations == []
    assert metrics.counters.get("script_validate_ok", 0) == base_ok + 1

