from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "kelviontech",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.whatsapp_tasks",
        "app.tasks.reconciliation",
        "app.tasks.image_tasks",
        "app.tasks.demo_data_purge",
        "app.tasks.whatsapp_template_status_sync",
        "app.tasks.broadcast_sender",
        "app.tasks.broadcast_dispatch",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Requires a `celery -A app.tasks.celery_app beat` process running alongside the
    # worker to actually fire on schedule -- see docker-compose.yml/GOING_LIVE.md for
    # whether that process is deployed. Purely a schedule definition otherwise; the task
    # itself also works fine invoked manually/synchronously (see app/tasks/reconciliation.py).
    beat_schedule={
        "check-stuck-payments": {
            "task": "app.tasks.reconciliation.check_stuck_payments",
            "schedule": 300.0,  # every 5 minutes
        },
        "purge-demo-data": {
            "task": "app.tasks.demo_data_purge.purge_demo_data",
            "schedule": 86400.0,  # daily
        },
        "sync-whatsapp-template-statuses": {
            "task": "app.tasks.whatsapp_template_status_sync.sync_template_statuses",
            "schedule": 900.0,  # every 15 minutes
        },
        "dispatch-due-broadcasts": {
            "task": "app.tasks.broadcast_dispatch.dispatch_due_campaigns",
            "schedule": 900.0,  # every 15 minutes
        },
    },
)
