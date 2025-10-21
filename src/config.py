"""Application configuration and shared resources."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final

import pandas as pd
from dotenv import load_dotenv
from openai import AzureOpenAI

# Ensure environment variables are loaded before any configuration values are read.
load_dotenv()

# Configure application-wide logging once on import.
LOG_FILE_NAME: Final[str] = os.getenv("BOOMGURU_LOG_FILE", "logs/main.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename=LOG_FILE_NAME,
    filemode="a",
)

# Resolve important paths relative to the project root.
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
FILES_DIR: Final[Path] = PROJECT_ROOT / "files"

# Azure OpenAI settings
API_VERSION: Final[str | None] = os.getenv("AZURE_API_VERSION")
AZURE_ENDPOINT: Final[str | None] = os.getenv("AZURE_ENDPOINT")
API_KEY: Final[str | None] = os.getenv("AZURE_API_KEY")
AZURE_DEPLOYMENT: Final[str | None] = os.getenv("AZURE_DEPLOYMENT")

# Creates client for Azure OpenAI
client = AzureOpenAI(
    api_version=API_VERSION,
    azure_endpoint=AZURE_ENDPOINT,
    api_key=API_KEY,
    azure_deployment=AZURE_DEPLOYMENT,
)

# Static data used to enrich error codes.
cid_description = pd.read_excel(FILES_DIR / "CID_DESCRIPTION.xlsx")
fmi_description = pd.read_excel(FILES_DIR / "FMI_DESCRIPTION.xlsx")
eid_description = pd.read_excel(FILES_DIR / "EID_DESCRIPTION.xlsx")

# Database configuration
MSSQL_SERVER: Final[str | None] = os.getenv("MSSQL_SERVER")
MSSQL_DATABASE: Final[str | None] = os.getenv("MSSQL_DATABASE")
MSSQL_USERNAME: Final[str | None] = os.getenv("MSSQL_USERNAME")
MSSQL_PASSWORD: Final[str | None] = os.getenv("MSSQL_PASSWORD")
MSSQL_DRIVER: Final[str] = os.getenv("MSSQL_DRIVER", "{ODBC Driver 17 for SQL Server}")
BOOMGURU_TARGET_TABLE: Final[str] = os.getenv(
    "BOOMGURU_TABLE", "AIRPA.dbo.BOOM_GURU"
)

# Part classifier settings
PART_CLASSIFIER_ATTEMPTS: Final[int] = 3
VALID_PART_CATEGORIES: Final[set[str]] = {
    "ATASMANLAR-DIGER",
    "ATASMANLAR-KIRICI",
    "ATASMANLAR-KOVA",
    "HIDROLIK PARÇALARI - HORTUM / RAKOR",
    "HIDROLIK PARÇALARI - SILINDIR",
    "ELEKTIRIK VE DIĞER PARÇALAR",
    "SASE PARCALARI",
    "YÜRÜYÜŞ TAKIMI",
    "LASTIK",
}