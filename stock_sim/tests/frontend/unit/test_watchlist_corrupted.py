from pathlib import Path
import json
from app.services.watchlist_store import WatchlistStore


def test_watchlist_corrupted_json_fallback(tmp_path: Path):
    p = tmp_path / 'watchlist.json'
    # 写入损坏内容
    p.write_text('{invalid json', encoding='utf-8')
    store = WatchlistStore(str(p), debounce_seconds=10.0)
    syms = store.load()
    assert syms == []  # 回退为空默认列表
    # 之后正常写入
    store.set_symbols(['AAA','BBB'])
    store.flush_now()
    data = json.loads(p.read_text(encoding='utf-8'))
    assert data['symbols'] == ['AAA','BBB']


def test_watchlist_wrong_type_symbols_field(tmp_path: Path):
    p = tmp_path / 'watchlist.json'
    p.write_text(json.dumps({'symbols': 'NOT_A_LIST'}), encoding='utf-8')
    store = WatchlistStore(str(p), debounce_seconds=0.1)
    syms = store.load()
    assert syms == []
    # 修复并写
    store.set_symbols(['X1'])
    store.flush_now()
    data = json.loads(p.read_text(encoding='utf-8'))
    assert data['symbols'] == ['X1']

