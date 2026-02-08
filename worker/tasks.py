from celery import Celery
from .engine.factory import OperatorFactory
from ..common.database import SessionLocal
from ..common.models import Transaction, TransactionStatus
import os
import logging

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Celery App
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
app = Celery("kontor_worker", broker=CELERY_BROKER_URL)

@app.task(name="process_transaction")
def process_transaction(transaction_id: int):
    logger.info(f"Starting transaction {transaction_id}")
    db = SessionLocal()
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    
    if not transaction:
        logger.error(f"Transaction {transaction_id} not found")
        return

    try:
        # Update Status
        transaction.status = TransactionStatus.PROCESSING
        db.commit()

        # Initialize Operator
        operator = OperatorFactory.get_operator(transaction.operator)
        operator.initialize_driver()

        # 1. Navigate & Select Type
        operator.navigate_to_home()
        # Logic to determine type (Package/TL) not yet in Transaction model implicitly
        # Assuming Package for now or based on package_name
        operator.select_type("Package") 

        # 2. Enter Phone
        operator.enter_phone_number(transaction.phone_number)

        # 3. Captcha
        if not operator.solve_captcha():
            raise Exception("Captcha solution failed")

        # 4. Select Package
        operator.select_package(transaction.package_name)

        # 5. Payment
        # Mock card info for now, in real app decrypt from transaction.card_number/etc
        card_info = {
            "holder_name": transaction.card_holder,
            "number": transaction.card_number,
            "month": "01", # Needs to be parsed/stored
            "year": "2026", # Needs to be parsed/stored
            "cvv": "123" # Needs to be stored/passed
        }
        operator.fill_payment_info(card_info)

        # 6. 3D Secure
        transaction.status = TransactionStatus.WAITING_SMS
        db.commit()
        
        # Here we would wait for SMS... 
        # For now, we assume 3D secure handling initiates the SMS process
        operator.handle_3d_secure()
        
        # ... Wait for SMS logic would go here ...
        
        transaction.status = TransactionStatus.SUCCESS
        db.commit()
        logger.info(f"Transaction {transaction_id} completed successfully")

    except Exception as e:
        logger.error(f"Transaction {transaction_id} failed: {e}")
        transaction.status = TransactionStatus.FAILED
        transaction.failure_reason = str(e)
        db.commit()
    finally:
        operator.close()
        db.close()
