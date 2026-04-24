import pytest

from app.core.database_router import DatabaseRouter


@pytest.mark.asyncio
async def test_read_write_split(monkeypatch):
    router = DatabaseRouter(
        master_url="postgresql+asyncpg://user:pass@master:5432/smdg",
        replica_urls=[
            "postgresql+asyncpg://user:pass@replica1:5432/smdg",
            "postgresql+asyncpg://user:pass@replica2:5432/smdg",
        ],
    )

    read_calls = []

    class DummySession:
        pass

    def make_read_factory(idx):
        def _factory():
            read_calls.append(idx)
            return DummySession()

        return _factory

    def write_factory():
        return "write-session"

    monkeypatch.setattr(router, "replica_session_factories", [make_read_factory(0), make_read_factory(1)])
    monkeypatch.setattr(router, "master_session_factory", write_factory)

    session1 = await router.get_read_session()
    session2 = await router.get_read_session()
    write_session = await router.get_write_session()

    assert isinstance(session1, DummySession)
    assert isinstance(session2, DummySession)
    assert read_calls == [0, 1]  # round-robin
    assert write_session == "write-session"


@pytest.mark.asyncio
async def test_replica_lag_monitoring(monkeypatch):
    router = DatabaseRouter(
        master_url="postgresql+asyncpg://user:pass@master:5432/smdg",
        replica_urls=["postgresql+asyncpg://user:pass@replica1:5432/smdg"],
    )

    class DummyResult:
        def __init__(self, value):
            self._value = value

        def scalar(self):
            return self._value

    class DummyConn:
        async def execute(self, _):
            if not hasattr(self, "called"):
                self.called = 1
                return DummyResult(1024)
            return DummyResult(0.25)

    class DummyContext:
        async def __aenter__(self):
            return DummyConn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyEngine:
        def connect(self):
            return DummyContext()

    monkeypatch.setattr(router, "replica_engines", [DummyEngine()])

    lag = await router.get_replica_lag()

    assert "replica_0" in lag
    assert lag["replica_0"]["lag_bytes"] == 1024
    assert lag["replica_0"]["healthy"] is True


@pytest.mark.asyncio
async def test_fallback_to_master_when_all_replicas_unhealthy(monkeypatch):
    router = DatabaseRouter(
        master_url="postgresql+asyncpg://user:pass@master:5432/smdg",
        replica_urls=["postgresql+asyncpg://user:pass@replica1:5432/smdg"],
        max_replica_lag_bytes=100,
    )

    async def unhealthy_snapshot(*args, **kwargs):
        return {
            "replica_0": {
                "id": 0,
                "healthy": False,
                "lag_bytes": 999999,
                "lag_seconds": 10.0,
                "error": "lag too high",
            }
        }

    monkeypatch.setattr(router, "_get_replica_snapshot", unhealthy_snapshot)
    monkeypatch.setattr(router, "master_session_factory", lambda: "master-session")

    session = await router.get_read_session()
    distribution = router.get_read_distribution()

    assert session == "master-session"
    assert distribution["counters"]["master_fallback"] == 1
