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

