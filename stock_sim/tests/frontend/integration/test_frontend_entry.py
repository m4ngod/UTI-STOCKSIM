import setup_frontend_entry as entry
from setup_frontend_entry import main


def test_frontend_entry_headless(monkeypatch):
    called = {}

    class _MW:
        def __init__(self):
            self.opened_panels = {}
        def open_panel(self, name):
            self.opened_panels[name] = True
        def list_open(self):
            return list(self.opened_panels.keys())

    def _fake_start_frontend(*, headless: bool):
        called['headless'] = headless
        return _MW()

    monkeypatch.setattr(entry, '_start_frontend', _fake_start_frontend)
    rc = main(["--headless", "--lang", "en_US", "--theme", "dark"])
    assert rc == 0
    assert called['headless'] is True


def test_frontend_entry_check_db_exits_without_starting_frontend(monkeypatch):
    called = {}

    monkeypatch.setattr(entry, '_run_database_check', lambda *, ensure_schema: called.setdefault('checked', 0) or 0)
    monkeypatch.setattr(entry, '_start_frontend', lambda *, headless: called.setdefault('started', True))

    rc = main(["--check-db"])

    assert rc == 0
    assert called == {'checked': 0}


def test_frontend_entry_gui_start_fails_fast_on_db_check(monkeypatch):
    called = {}

    monkeypatch.setattr(entry, '_run_database_check', lambda *, ensure_schema: 3)
    monkeypatch.setattr(entry, '_start_frontend', lambda *, headless: called.setdefault('started', True))

    rc = main(["--lang", "en_US"])

    assert rc == 3
    assert called == {}


def test_frontend_entry_can_skip_startup_db_check(monkeypatch):
    called = {}

    class _MW:
        opened_panels = {}

    monkeypatch.setattr(entry, '_run_database_check', lambda *, ensure_schema: called.setdefault('checked', True))
    monkeypatch.setattr(entry, '_start_frontend', lambda *, headless: called.setdefault('started', True) or _MW())

    rc = main(["--skip-db-check"])

    assert rc == 0
    assert called == {'started': True}

