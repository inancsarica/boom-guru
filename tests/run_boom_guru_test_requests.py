"""Fetch recent test rows and replay them against the Boom Guru endpoint."""
from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

import requests

from src.config import MSSQL_DATABASE
from src.db import get_db_connection

LOGGER = logging.getLogger(__name__)
DEFAULT_ENDPOINT = "http://localhost:8361/boom_guru"
DEFAULT_OUTPUT_PATH = Path("boom_guru_test_responses.json")
DEFAULT_WEBHOOK_URL = "http://localhost:8092/webhook-receiver"
DEFAULT_ORDER_CANDIDATES: Sequence[str] = (
    "created_at",
    "created_on",
    "created_date",
    "inserted_at",
    "inserted_on",
    "updated_at",
    "request_date",
    "request_time",
    "id",
)
REQUIRED_FIELDS = ("image_url", "image_id", "serial_number", "webhook_url", "language")
OPTIONAL_FIELDS = ("form_id", "question_id")
TABLE_SCHEMA = "dbo"
TABLE_NAME = "BOOM_GURU_TEST"
FULL_TABLE_NAME = f"AIRPA.{TABLE_SCHEMA}.{TABLE_NAME}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch recent entries from the Boom Guru test table and issue POST requests "
            "to the configured inference endpoint."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of rows to replay. Default: 10.",
    )
    parser.add_argument(
        "--order-column",
        dest="order_column",
        type=str,
        default=None,
        help=(
            "Column to use when determining recency. If omitted, the script attempts "
            "to pick a sensible default."
        ),
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default=DEFAULT_ENDPOINT,
        help=f"HTTP endpoint that will receive the replayed requests. Default: {DEFAULT_ENDPOINT}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=(
            "Path of the JSON file that will contain the responses. Default: "
            f"{DEFAULT_OUTPUT_PATH}."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP request timeout in seconds. Default: 30s.",
    )
    parser.add_argument(
        "--default-language",
        type=str,
        default="tr",
        help="Fallback language value when the database row does not provide one.",
    )
    parser.add_argument(
        "--default-webhook-url",
        type=str,
        default="http://localhost:8092/webhook-receiver",
        help="Fallback webhook URL when the database row does not provide one.",
    )
    parser.add_argument(
        "--default-form-id",
        type=str,
        default=None,
        help="Fallback form_id when the database row does not provide one.",
    )
    parser.add_argument(
        "--default-question-id",
        type=str,
        default=None,
        help="Fallback question_id when the database row does not provide one.",
    )
    parser.add_argument(
        "--default-image-url",
        type=str,
        default=None,
        help="Fallback image_url when the database row does not provide one.",
    )
    parser.add_argument(
        "--default-image-id",
        type=str,
        default=None,
        help="Fallback image_id when the database row does not provide one.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch rows and show the payloads without issuing HTTP requests.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()

    with get_db_connection() as connection:
        cursor = connection.cursor()
        available_columns = set(fetch_column_names(cursor))
        order_column = choose_order_column(args.order_column, available_columns)
        rows = fetch_recent_rows(cursor, limit=args.limit, order_column=order_column)

    LOGGER.info("Fetched %d row(s) from %s", len(rows), FULL_TABLE_NAME)

    fallback_values = {
        "language": args.default_language,
        "webhook_url": DEFAULT_WEBHOOK_URL,
        "form_id": args.default_form_id,
        "question_id": args.default_question_id,
        "image_url": args.default_image_url,
        "image_id": args.default_image_id,
    }

    responses: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        payload = build_payload(row, fallback_values)
        LOGGER.info(
            "[%d/%d] Sending request for serial_number=%s", index, len(rows), payload.get("serial_number")
        )
        if args.dry_run:
            responses.append(
                {
                    "serial_number": payload.get("serial_number"),
                    "request_payload": payload,
                    "response": None,
                    "status_code": None,
                }
            )
            continue

        try:
            payload['webhook_url'] = DEFAULT_WEBHOOK_URL
            response = requests.post(
                args.endpoint,
                json=payload,
                timeout=args.timeout,
            )
            response.raise_for_status()
            parsed_body = try_parse_json(response)
            status = response.status_code
        except requests.HTTPError as http_error:
            parsed_body = safe_error_payload(http_error.response)
            status = http_error.response.status_code if http_error.response else None
            LOGGER.error(
                "Request for serial_number=%s failed with status %s", payload.get("serial_number"), status
            )
        except requests.RequestException as request_error:
            parsed_body = {"error": str(request_error)}
            status = None
            LOGGER.error(
                "Request for serial_number=%s failed: %s", payload.get("serial_number"), request_error
            )

        responses.append(
            {
                "serial_number": payload.get("serial_number"),
                "request_payload": payload,
                "response": parsed_body,
                "status_code": status,
            }
        )

    write_responses(args.output, responses)
    LOGGER.info("Stored %d response(s) in %s", len(responses), args.output)


def fetch_column_names(cursor: Any) -> list[str]:
    """Return the column names for the configured test table."""
    query = (
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_CATALOG = ? AND TABLE_SCHEMA = ? AND TABLE_NAME = ?"
    )
    cursor.execute(query, (MSSQL_DATABASE, TABLE_SCHEMA, TABLE_NAME))
    return [row[0] for row in cursor.fetchall()]


def choose_order_column(override: str | None, available_columns: Iterable[str]) -> str | None:
    normalized = {column.lower(): column for column in available_columns}
    if override:
        cleaned = override.strip()
        validate_column_name(cleaned)
        try:
            return normalized[cleaned.lower()]
        except KeyError as exc:
            raise ValueError(
                f"Column '{cleaned}' does not exist on {FULL_TABLE_NAME}."
            ) from exc

    for candidate in DEFAULT_ORDER_CANDIDATES:
        if candidate.lower() in normalized:
            return normalized[candidate.lower()]

    LOGGER.warning(
        "Could not determine an order column automatically; the query will not include ORDER BY."
    )
    return None


def validate_column_name(column: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_]+", column):
        raise ValueError(f"Column name '{column}' contains invalid characters.")


def fetch_recent_rows(cursor: Any, *, limit: int, order_column: str | None) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("Limit must be a positive integer.")

    order_clause = f" ORDER BY {order_column} DESC" if order_column else ""
    query = (
        f"SELECT TOP ({limit}) * FROM {FULL_TABLE_NAME} "
        "WHERE serial_number NOT LIKE ('SRC%')"
        f"{order_clause}"
    )
    cursor.execute(query)
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def build_payload(row: dict[str, Any], fallback_values: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    missing_fields: list[str] = []
    for field in REQUIRED_FIELDS:
        value = row.get(field)
        if value in (None, ""):
            value = fallback_values.get(field)
        if value in (None, ""):
            missing_fields.append(field)
        else:
            payload[field] = value

    for field in OPTIONAL_FIELDS:
        value = row.get(field)
        if value in (None, ""):
            value = fallback_values.get(field)
        if value is not None:
            payload[field] = value

    if missing_fields:
        raise ValueError(
            f"Row for serial_number={row.get('serial_number')} is missing required fields: {', '.join(missing_fields)}"
        )

    return payload


def try_parse_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def safe_error_payload(response: requests.Response | None) -> dict[str, Any]:
    if response is None:
        return {"error": "No HTTP response returned."}
    try:
        return response.json()
    except ValueError:
        return {"status_code": response.status_code, "raw": response.text}


def write_responses(path: Path, responses: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = json.loads(json.dumps(responses, default=_json_default))
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2))


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


if __name__ == "__main__":
    main()