from sqlalchemy import Column, Integer, String, DateTime, Enum, Boolean, Text, ForeignKey
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func
import enum

Base = declarative_base()

class TransactionStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    WAITING_SMS = "WAITING_SMS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, index=True, nullable=False)
    operator = Column(String, nullable=False)  # TURKCELL, VODAFONE
    package_name = Column(String, nullable=False)
    amount = Column(String, nullable=True) # Price if available
    
    status = Column(Enum(TransactionStatus), default=TransactionStatus.PENDING)
    failure_reason = Column(Text, nullable=True)
    
    # Billing Info
    card_holder = Column(String, nullable=True)
    card_number = Column(String, nullable=True) # Encrypted or masked in real app
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class SMSMessage(Base):
    __tablename__ = "sms_messages"

    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String, index=True)
    content = Column(Text, nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now())
    is_used = Column(Boolean, default=False)
    related_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
