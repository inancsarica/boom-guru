"""Database utilities for persisting machine analysis results."""
from __future__ import annotations

import logging
from typing import Optional

import pyodbc

from .config import (
    MSSQL_DATABASE,
    MSSQL_DRIVER,
    MSSQL_PASSWORD,
    MSSQL_SERVER,
    MSSQL_USERNAME,
)


def get_db_connection() -> pyodbc.Connection:
    required = {
        "MSSQL_SERVER": MSSQL_SERVER,
        "MSSQL_DATABASE": MSSQL_DATABASE,
        "MSSQL_USERNAME": MSSQL_USERNAME,
        "MSSQL_PASSWORD": MSSQL_PASSWORD,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            f"Missing required MSSQL configuration values: {', '.join(missing)}"
        )
    connection_string = (
        f"DRIVER={MSSQL_DRIVER};"
        f"SERVER={MSSQL_SERVER};"
        f"DATABASE={MSSQL_DATABASE};"
        f"UID={MSSQL_USERNAME};"
        f"PWD={MSSQL_PASSWORD};"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(connection_string, autocommit=False)


def save_machine_analysis(
    session_id: str,
    serial_number: str,
    image_id: str,
    form_id: Optional[str],
    question_id: Optional[str],
    category: Optional[str],
    part_category: str,
    final_answer: str,
) -> None:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO AIRPA.dbo.BOOM_GURU (
                    session_id,
                    serial_number,
                    image_id,
                    form_id,
                    question_id,
                    category,
                    part_category,
                    final_answer
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    serial_number,
                    image_id,
                    form_id,
                    question_id,
                    category,
                    part_category,
                    final_answer,
                ),
            )
            conn.commit()
    except Exception as exc:  # pylint: disable=broad-except
        logging.error(
            "Failed to persist machine analysis for session_id=%s: %s",
            session_id,
            exc,
        )