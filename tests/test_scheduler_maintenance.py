import pytest

from app.services import maintenance_service


class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeDb:
    def begin(self):
        return _Txn()


@pytest.mark.asyncio
async def test_purge_loops_until_a_short_batch(monkeypatch):
    results = iter([5000, 5000, 120])
    calls = []

    async def fake_batch(db, *, cutoff, batch_size):
        calls.append(batch_size)
        return next(results)

    monkeypatch.setattr(
        maintenance_service.maintenance_repository, "delete_expired_refresh_tokens_batch", fake_batch,
    )
    total = await maintenance_service.purge_expired_refresh_tokens(_FakeDb())
    assert total == 10120
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_purge_respects_max_batches(monkeypatch):
    async def always_full(db, *, cutoff, batch_size):
        return batch_size

    monkeypatch.setattr(
        maintenance_service.maintenance_repository, "delete_expired_refresh_tokens_batch", always_full,
    )
    total = await maintenance_service.purge_expired_refresh_tokens(_FakeDb(), batch_size=10, max_batches=4)
    assert total == 40