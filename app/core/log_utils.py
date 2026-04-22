"""Утилиты логирования.

Содержит ``ThrottledErrorLogger`` — обёртка над ``logging.Logger``, которая
позволяет фоновым задачам (health_collector, webhook_retry_scheduler и т.п.)
не спамить одним и тем же сообщением каждые N секунд при длительной
деградации зависимости.

Поведение:

* Первая ошибка данного "ключа" (или ошибка с новой сигнатурой) —
  пишется на уровне ``first_level`` (по умолчанию ``WARNING``).
* Последующие повторения той же сигнатуры — на ``repeat_level``
  (по умолчанию ``DEBUG``), так что в INFO-логе их не видно.
* Каждые ``remind_every`` повторений — напоминание на уровне
  ``WARNING`` с текущим счётчиком подряд идущих сбоев.
* Вызов ``recovered`` после серии сбоев пишет INFO-сообщение.
  Если сбоев не было, ``recovered`` тихо возвращает ``False``.

Сигнатура ошибки считается как ``"{ТипИсключения}: {первая строка str(exc)}"``
и обрезается до 200 символов, чтобы один и тот же DNS-timeout с разными
адресами в сообщении не считался новой ошибкой на каждой итерации.

Класс рассчитан на один event loop и один поток — внутри нет блокировок.
Если одним объектом нужно делиться между потоками, оберни вызовы в lock
снаружи (на практике для background-шедулеров это не нужно).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional


__all__ = ["ThrottledErrorLogger", "error_signature"]


def error_signature(exc: BaseException, max_len: int = 200) -> str:
    """Короткая детерминированная сигнатура исключения для сравнения."""
    msg = str(exc) if exc else ""
    first_line = msg.splitlines()[0] if msg else ""
    return f"{type(exc).__name__}: {first_line}"[:max_len]


@dataclass
class _KeyState:
    signature: Optional[str] = None
    consecutive_failures: int = 0


@dataclass
class ThrottledErrorLogger:
    """Throttled logger для фоновых циклов.

    Args:
        logger: стандартный ``logging.Logger``, в который пишем.
        remind_every: после скольких одинаковых подряд ошибок выдавать
            "напоминание" на WARNING. По умолчанию 30 — при 30-секундном
            цикле это ~15 минут.
        first_level: уровень для первой ошибки / смены сигнатуры.
        repeat_level: уровень для повторов той же сигнатуры.
    """

    logger: logging.Logger
    remind_every: int = 30
    first_level: int = logging.WARNING
    repeat_level: int = logging.DEBUG
    _states: Dict[str, _KeyState] = field(default_factory=dict)

    def _state(self, key: str) -> _KeyState:
        st = self._states.get(key)
        if st is None:
            st = _KeyState()
            self._states[key] = st
        return st

    def failure(
        self,
        key: str,
        exc: BaseException,
        *,
        message: str = "%s failed: %s",
        include_traceback_on_new: bool = False,
    ) -> None:
        """Зарегистрировать ошибку ``exc`` под ключом ``key``.

        Args:
            key: логическое имя точки, где произошла ошибка
                (например, ``"health.database"``).
            exc: само исключение.
            message: формат-строка для logger'а. Подставляются
                ``(key, signature)`` — то есть должны быть два ``%s``.
            include_traceback_on_new: если True — при смене сигнатуры
                писать полный traceback (exc_info=True). Полезно для
                диагностики неожиданных ошибок.
        """
        sig = error_signature(exc)
        st = self._state(key)
        st.consecutive_failures += 1

        if sig != st.signature:
            # Новая (или первая) ошибка этого типа — полный лог.
            st.signature = sig
            self.logger.log(
                self.first_level,
                message,
                key,
                sig,
                exc_info=include_traceback_on_new,
            )
            return

        if self.remind_every > 0 and st.consecutive_failures % self.remind_every == 0:
            # Напоминание раз в N — что та же ошибка всё ещё с нами.
            self.logger.warning(
                "%s still failing after %d consecutive attempts: %s",
                key,
                st.consecutive_failures,
                sig,
            )
            return

        # Обычное повторение — в DEBUG.
        self.logger.log(self.repeat_level, message, key, sig)

    def recovered(self, key: str, *, message: str = "%s recovered after %d failed attempts") -> bool:
        """Отметить восстановление ``key`` после серии сбоев.

        Returns:
            ``True`` — если было хотя бы одно падение и мы записали INFO,
            ``False`` — если ключ был здоров (никакого лога не пишется).
        """
        st = self._states.get(key)
        if st is None or st.consecutive_failures == 0:
            return False
        self.logger.info(message, key, st.consecutive_failures)
        st.consecutive_failures = 0
        st.signature = None
        return True

    def failures(self, key: str) -> int:
        """Количество подряд идущих сбоев по ключу (0 — здоров)."""
        st = self._states.get(key)
        return st.consecutive_failures if st else 0

    def reset(self, key: Optional[str] = None) -> None:
        """Сбросить состояние ключа (или всех ключей, если ``key is None``)."""
        if key is None:
            self._states.clear()
        else:
            self._states.pop(key, None)
