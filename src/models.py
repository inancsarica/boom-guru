"""Pydantic models used by the FastAPI application."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ImageRequest(BaseModel):
    image_url: str
    image_id: str
    serial_number: str
    form_id: Optional[str] = None
    question_id: Optional[str] = None
    webhook_url: str
    language: str