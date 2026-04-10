# app/models/__init__.py
# Импортируем все модели, чтобы SQLAlchemy зарегистрировала их мапперы
from app.models.user import User
from app.models.file import File
from app.models.file_link import FileLink
from app.models.webhook import WebhookSubscription, WebhookDelivery

__all__ = [
    'User',
    'File',
    'FileLink',
    'WebhookSubscription',
    'WebhookDelivery',
]
