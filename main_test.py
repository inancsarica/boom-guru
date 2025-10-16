from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from uuid import uuid4
import requests
import logging
import os
import base64
from openai import AzureOpenAI
from dotenv import load_dotenv
from typing import Optional, List, Dict, Any
import traceback
import json
import pyodbc
import pandas as pd

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='main_test.log',
    filemode='a'
)
# Load environment variables
load_dotenv()

API_VERSION = os.getenv("AZURE_API_VERSION")
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
API_KEY = os.getenv("AZURE_API_KEY")
AZURE_DEPLOYMENT = os.getenv("AZURE_DEPLOYMENT")

# Creates client for Azure OpenAI
client = AzureOpenAI(
    api_version=API_VERSION,
    azure_endpoint=AZURE_ENDPOINT,
    api_key=API_KEY,
    azure_deployment=AZURE_DEPLOYMENT
)

cid_description = pd.read_excel("files/CID_DESCRIPTION.xlsx")
fmi_description = pd.read_excel("files/FMI_DESCRIPTION.xlsx")
eid_description = pd.read_excel("files/EID_DESCRIPTION.xlsx")

app = FastAPI()

MSSQL_SERVER = os.getenv("MSSQL_SERVER")
MSSQL_DATABASE = os.getenv("MSSQL_DATABASE")
MSSQL_USERNAME = os.getenv("MSSQL_USERNAME")
MSSQL_PASSWORD = os.getenv("MSSQL_PASSWORD")
MSSQL_DRIVER = os.getenv("MSSQL_DRIVER", "{ODBC Driver 18 for SQL Server}")
VALID_PART_CATEGORIES = {
    "MOTOR PARÇALARI",
    "HIDROLIK PARÇALARI",
    "CAT SPARE PARTS",
    "ELEKTIRIK VE DIĞER PARÇALAR",
    "SASE PARCALARI",
    "KORUYUCU BAKIM ÜRÜNLERI",
    "YÜRÜYÜŞ TAKIMI",
    "LASTIK",
}


def get_db_connection():
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
):
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
    except Exception as e:
        logging.error(
            f"Failed to persist machine analysis for session_id={session_id}: {str(e)}"
        )

class ImageRequest(BaseModel):
    image_url: str
    image_id: str
    serial_number: str
    form_id: Optional[str] = None
    question_id: Optional[str] = None
    webhook_url: str
    language: str

# Helper function to make OpenAI API calls
def call_openai_api(messages: List[Dict[str, Any]], session_id: str) -> str:
    """
    Calls the OpenAI API with the given messages and handles the response.
    
    Args:
        messages: The list of messages for the chat completion.
        session_id: The session ID for logging purposes.

    Returns:
        The content of the OpenAI response.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.5,
            top_p=1
        )
        logging.info(f"OpenAI API call successful for session_id={session_id}")
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"OpenAI API call failed for session_id={session_id}: {e}")
        raise Exception(f"OpenAI API call failed: {e}")

# Helper function to send the callback
def send_callback(callback_url: str, payload: Dict[str, Any], session_id: str):
    """
    Sends a callback to the specified URL.
    
    Args:
        callback_url: The URL to send the callback to.
        payload: The JSON payload for the callback.
        session_id: The session ID for logging.
    """
    try:
        headers = {
            "Boom724ExternalApiKey": os.getenv("BOOM_API_KEY"),
            "Language": "en",
            "Content-Type": "application/json"
        }
        callback_response = requests.post(callback_url, json=payload, headers=headers, verify=False)
        if callback_response.status_code == 200:
            logging.info(f"Callback sent successfully for session_id={session_id}")
        else:
            logging.error(f"Callback failed with status code {callback_response.status_code} for session_id={session_id}. Response: {callback_response.text}")
    except Exception as e:
        logging.error(f"Failed to send callback for session_id={session_id}: {str(e)}")

# 1. Receive request and immediately return session_id and metadata
@app.post("/boom_guru")
async def describe_image(request: ImageRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid4())
    background_tasks.add_task(process_image, session_id, request)

    logging.info(
        f"Received image description request: session_id={session_id}, "
        f"image_id={request.image_id}, serial_number={request.serial_number}, form_id={request.form_id}, "
        f"question_id={request.question_id}, image_url={request.image_url}"
    )

    return {
        "session_id": session_id,
        "image_id": request.image_id,
        "serial_number": request.serial_number,
        "form_id": request.form_id,
        "question_id": request.question_id,
        "webhook_url": request.webhook_url,
        "language": request.language,
        "status": "processing"
    }

# 2. Background processing function
async def process_image(session_id: str, request: ImageRequest):
    callback_url = request.webhook_url
    
    language_map = {
        "en": "English",
        "tr": "Türkçe",
        "ru": "Russian",
        "ka": "Georgian",
        "az": "Azerbaijani",
        "kk": "Kazakh",
        "ky": "Kyrgyz"
    }
    language_name = language_map.get(request.language, "English")

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(request.image_url, headers=headers, verify=False)
        if response.status_code != 200:
            raise Exception("Image download failed")

        logging.info(f"Image downloaded successfully for session_id={session_id}")

        image_base64 = base64.b64encode(response.content).decode('utf-8')
        image_extension = request.image_url.split(".")[-1].split("?")[0].lower()
        image_base64_str = f"data:image/{image_extension};base64,{image_base64}"

        # Step 1: Dispatcher call to determine category
        with open("prompts/dispatcher.md", "r", encoding="utf-8") as f:
            dispatcher_prompt = f.read()

        dispatcher_messages = [
            {"role": "system", "content": dispatcher_prompt},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_base64_str}}]}
        ]
        
        dispatcher_response_text = call_openai_api(dispatcher_messages, session_id)
        
        try:
            json_str = dispatcher_response_text.replace("```json", '').replace("```", '').replace("\n", '')
            response_data = json.loads(json_str)
            category = response_data.get("category")
            logging.info(f"Predicted category: {category} for session_id={session_id}")
        except json.JSONDecodeError as e:
            logging.error(f"Failed to decode JSON from dispatcher response for session_id={session_id}: {e}")
            category = "working_machine" # Default to working_machine

        final_answer = ""
        part_category: str = ""

        if category == "other":
            final_answer = "Yüklenen görsel bir iş makinesi veya hata kodu olarak tanımlanamadı. Lütfen bir makine ya da hata ekranı içeren alakalı bir görsel yükleyin."
        
        elif category == "error_code":
            # Step 2: Extract error codes
            with open("prompts/error_codes.md", "r", encoding="utf-8") as f:
                error_codes_prompt = f.read().replace("{language_name}", language_name)

            error_codes_messages = [
                {"role": "system", "content": error_codes_prompt},
                {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_base64_str}}]}
            ]
            
            error_codes_response_text = call_openai_api(error_codes_messages, session_id)
            
            try:
                json_str = error_codes_response_text.replace("```json", '').replace("```", '').replace("\n", '')
                response_data = json.loads(json_str)
                error_list = response_data.get("errors", [])
                additional_info = response_data.get("additional_info")
                logging.info(f"Extracted error codes: {error_list} for session_id={session_id}")
            except json.JSONDecodeError:
                error_list = []
                additional_info = ""
                logging.error(f"Failed to decode error codes JSON for session_id={session_id}")

            for error in error_list:
                code = error.get("code", "")
                if error.get('type') == 'CID-FMI':
                    try:
                        cid, fmi = map(int, code.split('-'))
                        cid_desc = cid_description.loc[cid_description.CID == cid, 'Description'].iloc[0]
                        fmi_desc = fmi_description.loc[fmi_description.FMI == fmi, 'Description'].iloc[0]
                        error["name"] = f"{cid_desc} - {fmi_desc}"
                    except (ValueError, IndexError):
                        error["name"] = "Description not found"
                elif error.get('type') == 'EID':
                    try:
                        eid = int(code)
                        eid_desc = eid_description.loc[eid_description.EID == eid, 'Description'].iloc[0]
                        error["name"] = eid_desc
                    except (ValueError, IndexError):
                        error["name"] = "Description not found"
            
            final_json_str = json.dumps({"errors": error_list, "additional_info": additional_info})

            # Step 3: Generate final human-readable response based on extracted codes
            with open("prompts/error_codes_prompt.md", "r", encoding="utf-8") as f:
                final_prompt = f.read().replace("{final_json_str}", final_json_str).replace("{target_language}", language_name)

            final_messages = [
                {"role": "system", "content": final_prompt},
                {"role": "user", "content": "Please generate a response based on the provided error codes."}
            ]
            
            final_answer = call_openai_api(final_messages, session_id)
        
        else: # "working_machine" category
            with open("prompts/prompt.md", "r", encoding="utf-8") as f:
                general_prompt = f.read().format(language_name=language_name)

            general_messages = [
                {"role": "system", "content": general_prompt},
                {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_base64_str}}]}
            ]
            
            final_answer = call_openai_api(general_messages, session_id)
        
        if category in {"working_machine", "error_code"}:
            try:
                with open("prompts/part_classifier.md", "r", encoding="utf-8") as f:
                    part_prompt = f.read()

                part_messages = [
                    {"role": "system", "content": part_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_base64_str}},
                            {
                                "type": "text",
                                "text": (
                                    "Aşağıdaki analiz, görseldeki hata veya makine hakkında çıkarılan bilgileri içerir:\n"
                                    f"{final_answer}"
                                ),
                            },
                        ],
                    },
                ]

                part_response_text = call_openai_api(part_messages, session_id)
                json_str = part_response_text.replace("```json", '').replace("```", '').strip()
                part_data = json.loads(json_str)
                part_category = part_data.get("part_category") or ""
                if part_category and part_category not in VALID_PART_CATEGORIES:
                    logging.warning(
                        f"Invalid part category '{part_category}' for session_id={session_id}"
                    )
                    part_category = ""
                elif part_category:
                    logging.info(
                        f"Predicted part category: {part_category} for session_id={session_id}"
                    )
                else:
                    logging.info(
                        f"No part category predicted for session_id={session_id}"
                    )
            except Exception as e:
                logging.error(
                    f"Failed to determine part category for session_id={session_id}: {str(e)}"
                )
                part_category = ""

        save_machine_analysis(
            session_id=session_id,
            serial_number=request.serial_number,
            image_id=request.image_id,
            form_id=request.form_id,
            question_id=request.question_id,
            category=category,
            part_category=part_category,
            final_answer=final_answer,
        )

        # Success payload
        callback_payload = {
            "session_id": session_id,
            "image_id": request.image_id,
            "serial_number": request.serial_number,
            "form_id": request.form_id,
            "question_id": request.question_id,
            "answer": final_answer,
            "status": "done",
            "part_category": part_category,
        }

    except Exception as e:
        error_details = traceback.format_exc()
        logging.error(f"Error processing session_id={session_id}: \n{error_details}")

        # Failure payload
        callback_payload = {
            "session_id": session_id,
            "image_id": request.image_id,
            "serial_number": request.serial_number,
            "form_id": request.form_id,
            "question_id": request.question_id,
            "answer": str(e),
            "status": "failed",
            "part_category": "",
        }

    send_callback(callback_url, callback_payload, session_id)

"""
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)
"""