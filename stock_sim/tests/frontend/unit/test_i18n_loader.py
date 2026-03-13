from app.i18n import t, set_language, get_missing_keys
from observability.metrics import metrics


def test_i18n_basic_and_formatting():
    # 默认 en_US
    set_language('en_US')
    assert t('app.title') == 'Stock Simulation'
    greet = t('greet', name='Alice')
    assert greet == 'Hello Alice'


def test_i18n_language_switch_and_fallback():
    set_language('zh_CN')
    assert t('app.title') == '股票模拟'
    # fallback: only exists in en_US
    before_missing = metrics.counters.get('i18n_missing', 0)
    val = t('only.english')
    after_missing = metrics.counters.get('i18n_missing', 0)
    assert val == 'Only English'
    # 未计为缺失
    assert after_missing == before_missing


def test_i18n_missing_key_counts():
    set_language('zh_CN')
    before = metrics.counters.get('i18n_missing', 0)
    key_name = 'not.exist.key'
    val = t(key_name)
    after = metrics.counters.get('i18n_missing', 0)
    assert val == key_name  # 返回 key 本身
    assert after == before + 1
    missing = get_missing_keys()
    assert any(k.endswith(':'+key_name) or k.split(':')[-1] == key_name for k in missing)


def test_i18n_format_error_increments():
    set_language('en_US')
    before = metrics.counters.get('i18n_format_error', 0)
    # greet 需要 name，占位符错误触发格式化异常
    result = t('greet', username='Bob')
    after = metrics.counters.get('i18n_format_error', 0)
    # 占位符未被替换仍包含 {name}
    assert '{name}' in result
    assert after == before + 1

