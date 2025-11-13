"""Business logic for handling image analysis requests."""
from __future__ import annotations

import base64
import json
import logging
import traceback
from pathlib import Path
from typing import Any, Dict, List

import requests

from ..config import (
    PART_CLASSIFIER_ATTEMPTS,
    VALID_PART_CATEGORIES,
    cid_description,
    eid_description,
    fmi_description,
)
from ..db import save_machine_analysis
from ..models import ImageRequest
from .openai_client import call_openai_api, send_callback

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = PROJECT_ROOT / "prompts"


async def process_image(session_id: str, request: ImageRequest) -> None:
    callback_url = request.webhook_url

    language_map = {
        "en": "English",
        "tr": "Türkçe",
        "ru": "Russian",
        "ka": "Georgian",
        "az": "Azerbaijani",
        "kk": "Kazakh",
        "ky": "Kyrgyz",
    }
    language_name = language_map.get(request.language, "English")

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(request.image_url, headers=headers, verify=False)
        if response.status_code != 200:
            raise Exception("Image download failed")

        logging.info("Image downloaded successfully for session_id=%s", session_id)

        image_base64 = base64.b64encode(response.content).decode("utf-8")
        image_extension = request.image_url.split(".")[-1].split("?")[0].lower()
        image_base64_str = f"data:image/{image_extension};base64,{image_base64}"

        dispatcher_prompt = (PROMPTS_DIR / "dispatcher.md").read_text(encoding="utf-8")
        dispatcher_messages = [
            {"role": "system", "content": dispatcher_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_base64_str}},
                ],
            },
        ]

        dispatcher_response_text = call_openai_api(dispatcher_messages, session_id)

        try:
            json_str = (
                dispatcher_response_text.replace("```json", "")
                .replace("```", "")
                .replace("\n", "")
            )
            response_data: Dict[str, Any] = json.loads(json_str)
            category = response_data.get("category")
            logging.info(
                "Predicted category: %s for session_id=%s",
                category,
                session_id,
            )
        except json.JSONDecodeError as exc:
            logging.error(
                "Failed to decode JSON from dispatcher response for session_id=%s: %s",
                session_id,
                exc,
            )
            category = "working_machine"

        final_answer = ""
        part_categories: List[str] = []
        if category == "working_machine":
            is_real_photo = True
            try:
                authenticity_prompt = (
                    PROMPTS_DIR / "photo_authenticity.md"
                ).read_text(encoding="utf-8")
                authenticity_messages = [
                    {"role": "system", "content": authenticity_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_base64_str}},
                        ],
                    },
                ]

                authenticity_response_text = call_openai_api(
                    authenticity_messages, session_id
                )
                json_str = (
                    authenticity_response_text.replace("```json", "")
                    .replace("```", "")
                    .replace("\n", "")
                    .strip()
                )
                authenticity_data = json.loads(json_str)
                is_real_value = authenticity_data.get("is_real_photo", True)
                if isinstance(is_real_value, bool):
                    is_real_photo = is_real_value
                elif isinstance(is_real_value, str):
                    is_real_photo = is_real_value.strip().lower() in {
                        "true",
                        "yes",
                        "1",
                    }
                elif isinstance(is_real_value, (int, float)):
                    is_real_photo = bool(is_real_value)
                logging.info(
                    "Image authenticity check for session_id=%s returned %s",
                    session_id,
                    is_real_photo,
                )
            except json.JSONDecodeError as exc:
                logging.error(
                    "Failed to decode authenticity JSON for session_id=%s: %s",
                    session_id,
                    exc,
                )
            except Exception as exc:  # pylint: disable=broad-except
                logging.error(
                    "Authenticity check failed for session_id=%s: %s",
                    session_id,
                    exc,
                )
                is_real_photo = True

            if not is_real_photo:
                logging.info(
                    "Image marked as non-real machine photo for session_id=%s", session_id
                )
                category = "other"

        if category == "other":
            final_answer = (
                "Yüklenen görsel bir iş makinesi veya hata kodu olarak tanımlanamadı ya da "
                "gerçek bir fotoğraf içermiyor (ör. dijital render, çizim). Lütfen gerçek bir "
                "makine ya da hata ekranı fotoğrafı içeren alakalı bir görsel yükleyin."
            )

        elif category == "error_code":
            error_codes_prompt = (
                PROMPTS_DIR / "error_codes.md"
            ).read_text(encoding="utf-8").replace("{language_name}", language_name)

            error_codes_messages = [
                {"role": "system", "content": error_codes_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_base64_str}},
                    ],
                },
            ]

            error_codes_response_text = call_openai_api(error_codes_messages, session_id)

            try:
                json_str = (
                    error_codes_response_text.replace("```json", "")
                    .replace("```", "")
                    .replace("\n", "")
                )
                response_data = json.loads(json_str)
                error_list = response_data.get("errors", [])
                additional_info = response_data.get("additional_info")
                logging.info(
                    "Extracted error codes: %s for session_id=%s",
                    error_list,
                    session_id,
                )
            except json.JSONDecodeError:
                error_list = []
                additional_info = ""
                logging.error(
                    "Failed to decode error codes JSON for session_id=%s",
                    session_id,
                )

            for error in error_list:
                code = error.get("code", "")
                if error.get("type") == "CID-FMI":
                    try:
                        cid, fmi = map(int, code.split("-"))
                        cid_desc = cid_description.loc[
                            cid_description.CID == cid, "Description"
                        ].iloc[0]
                        fmi_desc = fmi_description.loc[
                            fmi_description.FMI == fmi, "Description"
                        ].iloc[0]
                        error["name"] = f"{cid_desc} - {fmi_desc}"
                    except (ValueError, IndexError):
                        error["name"] = "Description not found"
                elif error.get("type") == "EID":
                    try:
                        eid = int(code)
                        eid_desc = eid_description.loc[
                            eid_description.EID == eid, "Description"
                        ].iloc[0]
                        error["name"] = eid_desc
                    except (ValueError, IndexError):
                        error["name"] = "Description not found"

            final_json_str = json.dumps(
                {"errors": error_list, "additional_info": additional_info}
            )

            final_prompt = (
                PROMPTS_DIR / "error_codes_prompt.md"
            ).read_text(encoding="utf-8").replace("{final_json_str}", final_json_str)
            final_prompt = final_prompt.replace("{target_language}", language_name)

            final_messages = [
                {"role": "system", "content": final_prompt},
                {
                    "role": "user",
                    "content": "Please generate a response based on the provided error codes.",
                },
            ]

            final_answer = call_openai_api(final_messages, session_id)

        else:  # "working_machine" category
            general_prompt = (
                PROMPTS_DIR / "prompt.md"
            ).read_text(encoding="utf-8").format(language_name=language_name)

            general_messages = [
                {"role": "system", "content": general_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_base64_str}},
                    ],
                },
            ]

            final_answer = call_openai_api(general_messages, session_id)

        if category in {"working_machine", "error_code"}:
            try:
                part_prompt = (PROMPTS_DIR / "part_classifier.md").read_text(
                    encoding="utf-8"
                )

                aggregated_categories: List[str] = []
                for attempt in range(1, PART_CLASSIFIER_ATTEMPTS + 1):
                    part_messages = [
                        {"role": "system", "content": part_prompt},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": image_base64_str},
                                },
                                {
                                    "type": "text",
                                    "text": (
                                        "The following analysis captures the extracted findings about the machine or fault:\n"
                                        f"{final_answer}"
                                    ),
                                },
                            ],
                        },
                    ]

                    try:             
                        part_response_text = call_openai_api(
                            part_messages,
                            session_id,
                            temperature=0.19920523,
                        )
                    except Exception as call_error:  # pylint: disable=broad-except
                        logging.error(
                            "Part classifier API call failed on attempt %s for session_id=%s: %s",
                            attempt,
                            session_id,
                            call_error,
                        )
                        continue

                    json_str = part_response_text.replace("```json", "").replace(
                        "```", ""
                    ).strip()
                    try:
                        part_data = json.loads(json_str)
                    except json.JSONDecodeError as decode_error:
                        logging.error(
                            "Failed to decode part classifier JSON on attempt %s for session_id=%s: %s\nResponse: %s",
                            attempt,
                            session_id,
                            decode_error,
                            json_str,
                        )
                        continue

                    raw_part_categories = part_data.get("part_categories", [])
                    if isinstance(raw_part_categories, str):
                        raw_part_categories = [raw_part_categories]
                    if not isinstance(raw_part_categories, list):
                        logging.warning(
                            "Unexpected part_categories format for session_id=%s: %s",
                            session_id,
                            type(raw_part_categories),
                        )
                        continue

                    validated_categories: List[str] = []
                    for item in raw_part_categories:
                        if not isinstance(item, str):
                            logging.warning(
                                "Discarding non-string part category '%s' for session_id=%s",
                                item,
                                session_id,
                            )
                            continue
                        normalized = item.strip()
                        if not normalized:
                            continue
                        if normalized not in VALID_PART_CATEGORIES:
                            logging.warning(
                                "Invalid part category '%s' for session_id=%s",
                                normalized,
                                session_id,
                            )
                            continue
                        if normalized not in validated_categories:
                            validated_categories.append(normalized)

                    for category_name in validated_categories:
                        if category_name not in aggregated_categories:
                            aggregated_categories.append(category_name)

                part_categories = aggregated_categories
                if part_categories:
                    logging.info(
                        "Predicted part categories: %s for session_id=%s",
                        part_categories,
                        session_id,
                    )
                else:
                    logging.info(
                        "No part categories predicted for session_id=%s",
                        session_id,
                    )
            except Exception as exc:  # pylint: disable=broad-except
                logging.error(
                    "Failed to determine part category for session_id=%s: %s",
                    session_id,
                    exc,
                )
                part_categories = []

        save_machine_analysis(
            session_id=session_id,
            serial_number=request.serial_number,
            image_id=request.image_id,
            form_id=request.form_id,
            question_id=request.question_id,
            webhook_url=request.webhook_url,
            image_url=request.image_url,
            category=category,
            part_category=", ".join(part_categories),
            final_answer=final_answer,
        )

        callback_payload = {
            "session_id": session_id,
            "image_id": request.image_id,
            "serial_number": request.serial_number,
            "form_id": request.form_id,
            "question_id": request.question_id,
            "answer": final_answer,
            "status": "done",
            "part_categories": part_categories,
        }

    except Exception as exc:  # pylint: disable=broad-except
        error_details = traceback.format_exc()
        logging.error("Error processing session_id=%s: %s", session_id, error_details)

        callback_payload = {
            "session_id": session_id,
            "image_id": request.image_id,
            "serial_number": request.serial_number,
            "form_id": request.form_id,
            "question_id": request.question_id,
            "answer": str(exc),
            "status": "failed",
            "part_categories": [],
        }

    send_callback(callback_url, callback_payload, session_id)