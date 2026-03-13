from app.services.export_service import ExportService, ExportServiceError
from app.panels.shared.export_button import ExportButton
import os


def test_export_button_basic_order_and_snapshot(tmp_path):
    # 固定 snapshot_id 便于断言
    svc = ExportService(snapshot_id_provider=lambda: 'snap-fixed')
    btn = ExportButton(svc)
    rows = [
        {'b': 2, 'a': 1, 'c': 3},  # 无序
        {'a': 10, 'b': 20, 'c': 30},
    ]
    columns = ['a', 'b']  # 仅导出 a,b 顺序
    path = btn.export(rows, columns, meta={'user': 'alice'}, fmt='csv', file_path=str(tmp_path / 'out.csv'))
    assert os.path.isfile(path)
    state = btn.get_state()
    assert state['last_snapshot_id'] == 'snap-fixed'
    # 读取文件验证第二行 header 顺序
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.read().strip().splitlines()
    assert lines[1] == 'a,b'
    # 第一数据行按顺序对应 a,b
    assert lines[2].startswith('1,2')


def test_export_button_include_extra_columns(tmp_path):
    svc = ExportService(snapshot_id_provider=lambda: 'sid-1')
    btn = ExportButton(svc)
    rows = [ {'x': 1, 'y': 2, 'z': 3} ]
    columns = ['y']
    path = btn.export(rows, columns, include_extra_columns=True, fmt='csv', meta={}, file_path=str(tmp_path / 'extra.csv'))
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.read().strip().splitlines()
    # header 行应为 y,x,z 或 y,z,x 取决于出现顺序; 我们逻辑: columns 顺序 + 其他字段按首次出现顺序 => y,x,z
    assert lines[1] == 'y,x,z'
    assert lines[2] == '2,1,3'


def test_export_button_error_handling_invalid_format(tmp_path):
    svc = ExportService(snapshot_id_provider=lambda: 'snap-err')
    btn = ExportButton(svc)
    try:
        btn.export([{'a':1}], ['a'], fmt='txt', meta={}, file_path=str(tmp_path / 'bad.txt'))
        assert False, 'should raise'
    except ExportServiceError as e:
        assert e.code == 'INVALID_FORMAT'
    st = btn.get_state()
    # last_error 记录 INVALID_FORMAT
    assert st['last_error'] == 'INVALID_FORMAT'


def test_export_button_snapshot_id_mismatch(tmp_path):
    svc = ExportService(snapshot_id_provider=lambda: 'snap-new')
    btn = ExportButton(svc)
    # 行里携带不同 snapshot_id -> mismatch
    rows = [{'value': 1, 'snapshot_id': 'other-snap'}]
    try:
        btn.export(rows, ['value', 'snapshot_id'], fmt='csv', meta={}, file_path=str(tmp_path / 'mismatch.csv'))
        assert False, 'expected mismatch'
    except ExportServiceError as e:
        assert e.code == 'SNAPSHOT_ID_MISMATCH'
    st = btn.get_state()
    assert st['last_error'] == 'SNAPSHOT_ID_MISMATCH'

