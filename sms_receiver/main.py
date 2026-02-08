from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..common.database import get_db, init_db
from ..common.models import SMSMessage
import logging 

app = FastAPI(title="SMS Receiver Service")
logger = logging.getLogger(__name__)

# Trigger DB Init if running standalone
init_db()

class SMSPayload(BaseModel):
    sender: str
    content: str
    timestamp: str = None

@app.post("/webhook")
def receive_sms(payload: SMSPayload, db: Session = Depends(get_db)):
    """
    Endpoint to receive SMS from an android gateway or modem.
    """
    logger.info(f"Received SMS from {payload.sender}: {payload.content}")
    
    sms = SMSMessage(
        sender=payload.sender,
        content=payload.content
    )
    db.add(sms)
    db.commit()
    
    return {"status": "received", "id": sms.id}
