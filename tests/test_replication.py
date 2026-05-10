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

    async def fake_snapshot(force_refresh: bool = False):
        return {
            "replica_0": {"id": 0, "healthy": True, "lag_bytes": 0, "lag_seconds": 0.0, "error": None},
            "replica_1": {"id": 1, "healthy": True, "lag_bytes": 0, "lag_seconds": 0.0, "error": None},
        }

    monkeypatch.setattr(router, "replica_session_factories", [make_read_factory(0), make_read_factory(1)])
    monkeypatch.setattr(router, "master_session_factory", write_factory)
    monkeypatch.setattr(router, "_get_replica_snapshot", fake_snapshot)

    session1 = await router.get_read_session()
    session2 = await router.get_read_session()
    write_session = await router.get_write_session()

    assert isinstance(session1, DummySession)
    assert isinstance(session2, DummySession)
    assert read_calls == [0, 1]  # round-robin
    assert write_session == "write-session"

    await router.dispose()


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
        def __init__(self):
            self._n = 0

        async def execute(self, _):
            self._n += 1
            if self._n == 1:
                return DummyResult(1)
            if self._n == 2:
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

        async def dispose(self) -> None:
            pass

    monkeypatch.setattr(router, "replica_engines", [DummyEngine()])

    lag = await router.get_replica_lag()

    assert "replica_0" in lag
    assert lag["replica_0"]["lag_bytes"] == 1024
    assert lag["replica_0"]["healthy"] is True

    await router.dispose()


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
