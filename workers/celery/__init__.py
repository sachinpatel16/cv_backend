import os
import sys

# Ensure project root is on sys.path so 'shared', 'modules', 'configs', 'services' are importable
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from celery import Celery
from configs.base import settings

celery_app = Celery(
    "cv_backend_workers",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    imports=["modules.peoplefind.tasks", "workers.tasks", "modules.smokingdetect.tasks"]
)
