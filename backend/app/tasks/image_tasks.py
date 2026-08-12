"""Celery task: generates every derivative variant for an Image row (see
app/services/image_pipeline.py::process_image). Entry point invoked by
POST /restaurants/{id}/images right after the original is durably stored, and again by
POST /restaurants/{id}/images/{image_id}/crop (which resets status="processing" and sets
crop_box before re-enqueuing) -- the same task handles both, since crop generation is just
"reprocess this Image, this time cropping the original first."

Retried automatically on failure (a transient MinIO blip during variant upload); once
retries are exhausted, process_image()'s own try/except marks the row status="failed"
rather than leaving it stuck at "processing" forever -- see that function.
"""

import asyncio
import uuid

from app.services.image_pipeline import process_image
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.image_tasks.generate_image_variants", bind=True, max_retries=3, default_retry_delay=10)
def generate_image_variants(self, image_id: str) -> None:
    asyncio.run(process_image(uuid.UUID(image_id)))
