from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI

from src.models import ImageRequest
from src.services.image_processing import process_image

app = FastAPI()

@app.post("/boom_guru")
async def describe_image(request: ImageRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid4())
    background_tasks.add_task(process_image, session_id, request)

    logging.info(
        "Received image description request: session_id=%s, image_id=%s, serial_number=%s, "
        "form_id=%s, question_id=%s, image_url=%s",
        session_id,
        request.image_id,
        request.serial_number,
        request.form_id,
        request.question_id,
        request.image_url,
    )

    return {
        "session_id": session_id,
        "image_id": request.image_id,
        "serial_number": request.serial_number,
        "form_id": request.form_id,
        "question_id": request.question_id,
        "webhook_url": request.webhook_url,
        "language": request.language,
        "status": "processing",
    }
