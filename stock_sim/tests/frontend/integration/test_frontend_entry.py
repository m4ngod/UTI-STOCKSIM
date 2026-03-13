from setup_frontend_entry import main

def test_frontend_entry_headless(monkeypatch):
    # 确保 headless 运行
    rc = main(["--headless", "--lang", "en_US", "--theme", "dark"])
    assert rc == 0

