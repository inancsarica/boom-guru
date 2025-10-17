"""Helpers for interacting with Azure OpenAI and webhook callbacks."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import requests

from ..config import client


def call_openai_api(messages: List[Dict[str, Any]], session_id: str) -> str:
    """Calls the OpenAI API with the given messages and handles the response."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.5,
            top_p=1,
        )
        logging.info("OpenAI API call successful for session_id=%s", session_id)
        return response.choices[0].message.content
    except Exception as exc:  # pylint: disable=broad-except
        logging.error(
            "OpenAI API call failed for session_id=%s: %s",
            session_id,
            exc,
        )
        raise Exception(f"OpenAI API call failed: {exc}") from exc


def send_callback(callback_url: str, payload: Dict[str, Any], session_id: str) -> None:
    """Sends a callback to the specified URL."""
    try:
        headers = {
            "Boom724ExternalApiKey": os.getenv("BOOM_API_KEY"),
            "Language": "en",
            "Content-Type": "application/json",
        }
        callback_response = requests.post(
            callback_url,
            json=payload,
            headers=headers,
            verify=False,
        )
        if callback_response.status_code == 200:
            logging.info("Callback sent successfully for session_id=%s", session_id)
        else:
            logging.error(
                "Callback failed with status code %s for session_id=%s. Response: %s",
                callback_response.status_code,
                session_id,
                callback_response.text,
            )
    except Exception as exc:  # pylint: disable=broad-except
        logging.error(
            "Failed to send callback for session_id=%s: %s",
            session_id,
            exc,
        )