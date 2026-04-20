"""
Заглушка бэкенда под требования ГОСТ для профиля развёртывания Russia.

На текущем этапе делегирует операции модулю age (CryptoManager): замените методы
на интеграцию с сертифицированным криптопровайдером или библиотекой Стрибог/Kuznyechik по ТК26.
"""
from __future__ import annotations

import logging

from app.crypto.crypto import CryptoManager

logger = logging.getLogger(__name__)


class GOSTCrypto(CryptoManager):
    """Расширение CryptoManager для профиля RU; реализация ГОСТ — в следующих версиях."""

    def __init__(self) -> None:
        super().__init__()
        logger.warning(
            "GOSTCrypto использует временную реализацию на age; "
            "подключите сертифицированный ГОСТ-провайдер перед продакшеном."
        )
