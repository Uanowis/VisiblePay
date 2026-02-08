from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..common.database import get_db, init_db
from ..common.models import Transaction, TransactionStatus
from ..worker.tasks import process_transaction
import logging

# Initialize DB
init_db()

app = FastAPI(title="Kontor Automation API")
logger = logging.getLogger(__name__)

class TopUpRequest(BaseModel):
    phone_number: str
    operator: str # TURKCELL, VODAFONE
    package_name: str
    card_holder: str
    card_number: str
    card_month: str
    card_year: str
    card_cvv: str

class TopUpResponse(BaseModel):
    transaction_id: int
    status: str

@app.post("/topup", response_model=TopUpResponse)
def create_topup(request: TopUpRequest, db: Session = Depends(get_db)):
    # Create Transaction
    db_transaction = Transaction(
        phone_number=request.phone_number,
        operator=request.operator,
        package_name=request.package_name,
        card_holder=request.card_holder,
        card_number=request.card_number, 
        # Note: In production, store card info securely or just pass to worker ephemeral
        # For this demo, we store raw (NOT RECOMMENDED for production)
        status=TransactionStatus.PENDING
    )
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)

    # Trigger Worker
    process_transaction.delay(db_transaction.id)

    return TopUpResponse(transaction_id=db_transaction.id, status=db_transaction.status)

@app.get("/transaction/{transaction_id}", response_model=TopUpResponse)
def get_transaction(transaction_id: int, db: Session = Depends(get_db)):
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return TopUpResponse(transaction_id=transaction.id, status=transaction.status)
