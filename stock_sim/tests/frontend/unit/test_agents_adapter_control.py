from app.ui.adapters.agents_adapter import AgentsPanelAdapter


class _FakeItem:
    def __init__(self, text: str):
        self._text = text

    def text(self):
        return self._text


class _FakeTable:
    def __init__(self):
        self._rows = [
            [_FakeItem("agent-001")],
            [_FakeItem("agent-002")],
        ]

    def selectionModel(self):
        return None

    def currentRow(self):
        return 0

    def item(self, row: int, col: int):
        try:
            return self._rows[row][col]
        except Exception:
            return None


class _FakeIndex:
    def __init__(self, row: int):
        self._row = row

    def row(self):
        return self._row


class _FakeSelectionModel:
    def selectedRows(self):
        return [_FakeIndex(0), _FakeIndex(1)]


class _MultiFakeTable(_FakeTable):
    def selectionModel(self):
        return _FakeSelectionModel()


class _SelectedItem(_FakeItem):
    def __init__(self, text: str, row: int):
        super().__init__(text)
        self._row = row

    def row(self):
        return self._row


class _SelectedItemsTable(_FakeTable):
    def selectionModel(self):
        return None

    def selectedItems(self):
        return [_SelectedItem("agent-001", 0), _SelectedItem("agent-002", 1)]


class _FakeLogic:
    def __init__(self):
        self.control_calls = []

    def control(self, agent_id: str, action: str):
        self.control_calls.append((agent_id, action))


def test_agents_adapter_control_targets_current_row_instead_of_all_rows():
    adapter = AgentsPanelAdapter()
    logic = _FakeLogic()
    adapter._logic = logic
    adapter._table = _FakeTable()
    adapter._selected_agent = "agent-001"

    adapter._do_control("stop")

    assert logic.control_calls == [("agent-001", "stop")]


def test_agents_adapter_control_targets_all_selected_rows():
    adapter = AgentsPanelAdapter()
    logic = _FakeLogic()
    adapter._logic = logic
    adapter._table = _MultiFakeTable()
    adapter._selected_agent = "agent-001"

    adapter._do_control("start")

    assert logic.control_calls == [
        ("agent-001", "start"),
        ("agent-002", "start"),
    ]


def test_agents_adapter_control_falls_back_to_selected_items_rows():
    adapter = AgentsPanelAdapter()
    logic = _FakeLogic()
    adapter._logic = logic
    adapter._table = _SelectedItemsTable()
    adapter._selected_agent = "agent-001"

    adapter._do_control("start")

    assert logic.control_calls == [
        ("agent-001", "start"),
        ("agent-002", "start"),
    ]
