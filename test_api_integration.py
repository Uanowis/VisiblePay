import os
import sys
import django
from unittest.mock import patch

# Setup Django environment
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'web_interface'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web_interface.settings')
django.setup()

from worker.tasks import poll_matik_api, process_autonomous_order
from core.models import Order

# Mock XML Response based on user's structure
MOCK_XML_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<turkcell>
    <talep>
        <id>5554604</id>
        <numara>5495242525</numara>
        <kontor>475904</kontor>
        <operator>turkcellses</operator>
    </talep>
    <talep>
        <id>5554605</id>
        <numara>5551234567</numara>
        <kontor>250</kontor>
        <operator>turkcelltam</operator>
    </talep>
</turkcell>
"""

class MockResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code
        self.text = content.decode('utf-8') if isinstance(content, bytes) else content
        
    def raise_for_status(self):
        if self.status_code != 200:
            raise Exception("HTTP Error")

def test_poll_and_process():
    print("--- Starting Integration Test ---")
    
    # Check initial order count
    initial_count = Order.objects.count()
    print(f"Initial Order count: {initial_count}")
    
    # 1. Mock requests.get inside fetch_pending_orders
    with patch('requests.get') as mock_get:
        mock_get.return_value = MockResponse(MOCK_XML_RESPONSE.encode('utf-8'))
        
        # 2. Mock process_autonomous_order.delay so it just calls the function synchronously for testing purposes
        # but prevents playwright from actually running to save time.
        with patch('worker.tasks.process_autonomous_order.delay') as mock_process:
            
            print("Running poll_matik_api task...")
            poll_matik_api()
            
            # Check if orders were created
            new_count = Order.objects.count()
            print(f"New Order count: {new_count}")
            print(f"Orders created: {new_count - initial_count}")
            
            # Print the created orders
            orders = Order.objects.filter(external_ref__in=['5554604', '5554605'])
            
            for index, order in enumerate(orders):
                print(f"Created Order: Ref={order.external_ref}, Phone={order.phone_number}, Source={order.api_source}")
                
                print(f"--- Firing Logic for {order.external_ref} ---")
                
                # We want to test the logic BEFORE playwright launch. We can mock sync_playwright
                with patch('worker.tasks.sync_playwright') as mock_playwright:
                    # Make it raise an exception so it stops right before launching browser,
                    # UNLESS it hits return early (e.g. for WAITING_MANUAL_ACTION)
                    mock_playwright.side_effect = Exception("Browser Launch Prevented")
                    
                    try:
                        process_autonomous_order(order.id)
                    except Exception as e:
                        if str(e) == "Browser Launch Prevented":
                            print(f">>> Proceeded to Browser Automation step for {order.external_ref}!")
                        else:
                            print(f">>> Exception: {e}")
                
                order.refresh_from_db()
                print(f"Resulting Status: {order.status}")
                print(f"Log Message: {order.log_message}")
                print("")

if __name__ == '__main__':
    test_poll_and_process()
