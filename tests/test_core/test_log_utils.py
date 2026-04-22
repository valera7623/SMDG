"""Тесты для ``app.core.log_utils.ThrottledErrorLogger``."""
from __future__ import annotations

import logging

import pytest

from app.core.log_utils import ThrottledErrorLogger, error_signature


def test_error_signature_includes_type_and_first_line() -> None:
    try:
        raise RuntimeError("boom\nsecond line")
    except RuntimeError as exc:
        sig = error_signature(exc)
    assert sig == "RuntimeError: boom"


def test_error_signature_is_truncated() -> None:
    try:
        raise ValueError("x" * 500)
    except ValueError as exc:
        sig = error_signature(exc, max_len=50)
    assert len(sig) == 50
    assert sig.startswith("ValueError: xxx")


def test_first_failure_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.first_failure")
    tl = ThrottledErrorLogger(logger=logger, remind_every=5)

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        tl.failure("db", RuntimeError("oops"))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "db" in warnings[0].getMessage()
    assert "oops" in warnings[0].getMessage()


def test_repeated_same_signature_goes_to_debug(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.repeat")
    tl = ThrottledErrorLogger(logger=logger, remind_every=100)

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        # Первая — WARNING
        tl.failure("db", RuntimeError("same"))
        # Последующие — DEBUG
        for _ in range(4):
            tl.failure("db", RuntimeError("same"))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(warnings) == 1
    assert len(debugs) == 4
    assert tl.failures("db") == 5


def test_different_signature_logs_warning_again(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.sig_change")
    tl = ThrottledErrorLogger(logger=logger, remind_every=100)

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        tl.failure("db", RuntimeError("first"))
        tl.failure("db", ValueError("second"))  # новый тип
        tl.failure("db", ValueError("second"))  # повтор второго типа

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(warnings) == 2, "первая из серии и смена сигнатуры обе должны быть WARNING"
    assert len(debugs) == 1


def test_reminder_every_n_failures(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.reminder")
    tl = ThrottledErrorLogger(logger=logger, remind_every=3)

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        for _ in range(6):
            tl.failure("db", RuntimeError("persistent"))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    # 1 — первая ошибка, 2 и 3 — напоминания на итерациях №3 и №6
    assert len(warnings) == 3
    assert "still failing" in warnings[1].getMessage()
    assert "still failing" in warnings[2].getMessage()


def test_recovered_logs_info_only_if_failures(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.recovery")
    tl = ThrottledErrorLogger(logger=logger)

    # Нет падений — recovered не должен ничего писать
    with caplog.at_level(logging.DEBUG, logger=logger.name):
        assert tl.recovered("db") is False
    assert not caplog.records

    caplog.clear()

    with caplog.at_level(logging.INFO, logger=logger.name):
        tl.failure("db", RuntimeError("x"))
        tl.failure("db", RuntimeError("x"))
        tl.failure("db", RuntimeError("x"))
        assert tl.recovered("db") is True

    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(infos) == 1
    assert "recovered after 3 failed attempts" in infos[0].getMessage()
    # Счётчик сброшен
    assert tl.failures("db") == 0


def test_keys_are_independent(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.keys")
    tl = ThrottledErrorLogger(logger=logger, remind_every=100)

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        tl.failure("db", RuntimeError("same"))
        tl.failure("redis", RuntimeError("same"))  # тот же текст — но другой key

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert tl.failures("db") == 1
    assert tl.failures("redis") == 1
