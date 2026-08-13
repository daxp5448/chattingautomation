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
    # No caller anywhere in this codebase ever reads a task's return value (every task
    # persists its own result to the database instead -- see e.g. image_pipeline.py's
    # process_image) -- this stops Celery from touching the result backend for task
    # bookkeeping at all. Without it, a `.delay()` call can spend tens of seconds retrying
    # a Redis result-backend connection (pubsub subscribe for late-join result delivery)
    # before ever getting to actually publish the task, even though nothing will ever ask
    # for that result -- exactly the stall app/services/image_pipeline.py::enqueue_processing's
    # broker-unreachable fallback exists to avoid.
    task_ignore_result=True,
    # Fails a publish attempt immediately instead of Celery's own internal retry-on-
    # publish-failure loop -- enqueue_processing's except clause is what should decide
    # what happens next (fall back to synchronous processing), not Celery retrying a
    # broker connection that's down for the whole life of a local dev process.
    task_publish_retry=False,
    broker_connection_retry_on_startup=False,
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
