import importlib

from app.diagnostics_runtime_gateway import DiagnosticsRuntimeGateway


runtime_query_service = importlib.import_module("services.runtime_query_service")


def test_default_query_service_is_created_lazily_once(monkeypatch):
    instances = []

    class Queries:
        def __init__(self):
            instances.append(self)

        def get_run_monitoring_snapshot(self, run_id):
            return {"run_id": run_id}

        def get_evidence_and_findings_snapshot(self, run_id):
            return {"run_id": run_id, "kind": "evidence"}

    monkeypatch.setattr(runtime_query_service, "RuntimeQueryService", Queries)

    gateway = DiagnosticsRuntimeGateway()

    assert instances == []
    assert gateway.get_run_monitoring_snapshot("run-1") == {
        "run_id": "run-1"
    }
    assert gateway.get_evidence_and_findings_snapshot("run-1") == {
        "run_id": "run-1",
        "kind": "evidence",
    }
    assert len(instances) == 1


def test_injected_query_service_is_used_without_replacement():
    calls = []

    class Queries:
        def list_health(self):
            calls.append("list_health")
            return ("healthy",)

    queries = Queries()
    gateway = DiagnosticsRuntimeGateway(query_service=queries)

    assert gateway.list_health() == ("healthy",)
    assert calls == ["list_health"]
