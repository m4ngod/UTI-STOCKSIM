import os
import json
import pytest
from app.state import VersionStore, VersionStoreError


def test_add_and_latest(tmp_path):
    path = tmp_path / 'vs.json'
    store = VersionStore(str(path))
    v1 = store.add_version('agentA', {'param': 1}, 'alice')
    v2 = store.add_version('agentA', {'param': 2}, 'bob')
    assert v1.version == 1
    assert v2.version == 2
    latest = store.get_latest_version('agentA')
    assert latest.version == 2
    assert json.loads(path.read_text(encoding='utf-8'))['agentA'][-1]['version'] == 2


def test_rollback(tmp_path):
    path = tmp_path / 'vs.json'
    store = VersionStore(str(path))
    store.add_version('agentA', {'x': 1}, 'alice')  # v1
    store.add_version('agentA', {'x': 2}, 'alice')  # v2
    rb = store.create_rollback('agentA', 1, 'bob')  # v3 rollback_of=1
    assert rb.version == 3
    assert rb.rollback_of == 1
    versions = store.list_versions('agentA')
    assert [v.version for v in versions] == [1,2,3]


def test_rollback_not_found(tmp_path):
    path = tmp_path / 'vs.json'
    store = VersionStore(str(path))
    store.add_version('agentA', {'x': 1}, 'alice')
    with pytest.raises(VersionStoreError) as e:
        store.create_rollback('agentA', 5, 'bob')
    assert e.value.code == 'VERSION_NOT_FOUND'


def test_agent_not_found(tmp_path):
    path = tmp_path / 'vs.json'
    store = VersionStore(str(path))
    with pytest.raises(VersionStoreError) as e:
        store.list_versions('nope')
    assert e.value.code == 'AGENT_NOT_FOUND'


def test_persistence_reload(tmp_path):
    path = tmp_path / 'vs.json'
    store = VersionStore(str(path))
    store.add_version('agentA', {'p': 1}, 'alice')
    store.add_version('agentA', {'p': 2}, 'alice')
    # 重新加载
    store2 = VersionStore(str(path))
    latest = store2.get_latest_version('agentA')
    assert latest.version == 2

