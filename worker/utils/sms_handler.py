import time
import re
import logging
from datetime import datetime, timedelta
# We need to import the django models. 
# Since this runs in the worker, Django is already setup by celery_app.py
from core.models import SMSLog, Order

logger = logging.getLogger(__name__)

def wait_for_sms(order_id: int, timeout: int = 120, check_interval: int = 2) -> str:
    """
    Polls the database for an SMSLog associated with the given order_id
    or a recent SMS if heuristics are used.
    
    Returns the 6-digit code if found, else raises TimeoutError.
    """
    logger.info(f"Waiting for SMS for Order {order_id} (Timeout: {timeout}s)")
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        # Check for logs linked to this order
        # Note: The webhook tries to link '3DS_WAITING' orders. 
        # So we look for SMSLog where related_order_id == order_id
        
        log = SMSLog.objects.filter(
            related_order_id=order_id,
            received_at__gte=datetime.now() - timedelta(seconds=timeout) # Optimization
        ).order_by('-received_at').first()
        
        if log:
            # Extract Code
            match = re.search(r'\b\d{6}\b', log.message_content)
            if match:
                code = match.group(0)
                logger.info(f"SMS Code Found: {code}")
                return code
            else:
                logger.warning(f"SMS found but no 6-digit code: {log.message_content}")
        
        time.sleep(check_interval)
        
    raise TimeoutError(f"SMS verification timed out for Order {order_id}")
