from fastapi import FastAPI, Request
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

# Create a new FastAPI app
listener_app = FastAPI()

@listener_app.post("/webhook-receiver")
async def webhook_receiver(request: Request):
    data = await request.json()
    logging.info(f"Webhook Received: {data}")
    return {"message": "Webhook received successfully."}

#CALLBACK_URL=http://localhost:8092/webhook-receiver