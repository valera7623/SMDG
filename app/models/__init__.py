# app/models/__init__.py
# Импортируем все модели, чтобы SQLAlchemy зарегистрировала их мапперы
from app.models.user import User
from app.models.file import File
from app.models.tenant import Tenant
from app.models.file_link import FileLink
from app.models.webhook import WebhookSubscription, WebhookDelivery
from app.models.dicom_view_token import DicomViewToken
from app.models.dead_letter import DeadLetterMessage, DeadLetterLog
from app.models.archive import ArchiveRecord, ArchiveRestoreRequest
from app.models.deleted_user import DeletedUser

__all__ = [
    'User',
    'File',
    'Tenant',
    'FileLink',
    'WebhookSubscription',
    'WebhookDelivery',
    'DicomViewToken',
    'DeadLetterMessage',
    'DeadLetterLog',
    'ArchiveRecord',
    'ArchiveRestoreRequest',
    'DeletedUser',
]
