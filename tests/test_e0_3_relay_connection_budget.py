import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUDGET = json.loads((ROOT / "docs/e0-3-relay-connection-budget.v1.json").read_text())


def test_budget_arithmetic_preserves_postgres_headroom():
    pg = BUDGET["postgresObservation"]
    runtime = BUDGET["enforcedRuntimeBound"]
    decision = BUDGET["decision"]
    assert pg["ordinaryClientCapacity"] == (
        pg["maxConnections"]
        - pg["reservedConnections"]
        - pg["superuserReservedConnections"]
    ) == 97
    assert runtime["maximumRelayClientConnections"] == (
        runtime["processes"]
        * (runtime["executorWorkers"] + runtime["synchronousEventLoopSlots"])
        * runtime["connectionsPerCallingThread"]
    ) == 9
    assert decision["connectionLimit"] == 12
    assert decision["operationalHeadroom"] == 3
    assert decision["ordinaryCapacityAfterRelayLimit"] == 85
    assert pg["ordinaryClientCapacity"] >= 2 * decision["connectionLimit"]


def test_runtime_executor_is_explicit_and_hard_capped():
    source = (ROOT / "relay-fastapi/main.py").read_text()
    unit = (ROOT / "deploy/systemd/relay-fastapi-runtime.conf").read_text()
    assert 'min(8, max(1, int(os.getenv("RELAY_EXECUTOR_WORKERS", "8"))))' in source
    assert "set_default_executor(executor)" in source
    assert "max_workers=RELAY_EXECUTOR_WORKERS" in source
    assert "Environment=RELAY_EXECUTOR_WORKERS=8" in unit
    assert BUDGET["enforcedRuntimeBound"]["executorHardMaximum"] == 8


def test_budget_is_evidence_only_and_fail_closed_on_topology_change():
    assert BUDGET["productionAuthorization"] is False
    assert BUDGET["implementationDeployed"] is False
    assert BUDGET["status"] == "MEASURED_ENVELOPE_REHEARSED_NOT_DEPLOYED"
    stops = " ".join(BUDGET["stopConditions"])
    assert "process count" in stops and "Uvicorn workers" in stops
    assert "more than one PostgreSQL connection" in stops
    assert BUDGET["nextPrerequisite"].startswith("rehearse the eight R5 transition writer")


def test_relay_repositories_do_not_declare_an_implicit_pool():
    sources = "\n".join(
        path.read_text() for path in (ROOT / "relay/repositories").glob("*.py")
    )
    assert "psycopg_pool" not in sources
    assert "ConnectionPool" not in sources
