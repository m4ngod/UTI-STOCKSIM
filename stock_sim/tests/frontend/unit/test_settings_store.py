from app.state import SettingsStore, LayoutPersistence


def test_language_change_triggers_callback(tmp_path):
    config_path = tmp_path / 'settings.json'
    store = SettingsStore(path=str(config_path))
    called = {}
    def on_lang(field, value, full):
        called['value'] = value
        called['field'] = field
    store.on_language(on_lang)
    store.set_language('en_US')
    assert called.get('value') == 'en_US'
    assert called.get('field') == 'language'
    # 持久化验证
    text = config_path.read_text(encoding='utf-8')
    assert 'en_US' in text


def test_layout_persistence(tmp_path):
    path = tmp_path / 'layout.json'
    lp = LayoutPersistence(str(path))
    lp.save({'panels': {'account': {'visible': True}}})
    lp.update({'panels': {'account': {'size': [800, 600]}, 'market': {'visible': False}}})
    data = lp.get()
    assert data['panels']['account']['visible'] is True
    assert data['panels']['account']['size'] == [800, 600]
    assert data['panels']['market']['visible'] is False
    # reload
    lp2 = LayoutPersistence(str(path))
    data2 = lp2.get()
    assert data2['panels']['account']['size'] == [800, 600]

