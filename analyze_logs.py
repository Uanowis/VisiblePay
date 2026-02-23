import os
import sys
import django

# Setup Django environment
sys.path.append(os.path.join(os.getcwd(), 'web_interface'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web_interface.settings')
django.setup()

from core.models import Order, TestRun

print("--- ANALYZING RECENT FAILED ORDERS ---")
failed_orders = Order.objects.filter(status='FAILED').order_by('-created_at')[:5]
if not failed_orders:
    print("No failed orders found.")
for order in failed_orders:
    print(f"Order ID: {order.id} | Date: {order.created_at} | Phone: {order.phone_number}")
    print(f"Log Message: {order.log_message}")
    print("-" * 30)

print("\n--- ANALYZING RECENT TEST RUNS ---")
test_runs = TestRun.objects.all().order_by('-created_at')[:5]
if not test_runs:
    print("No test runs found.")
for run in test_runs:
    print(f"TestRun ID: {run.id} | Date: {run.created_at} | Status: {run.status}")
    print(f"Logs:\n{run.logs}")
    print("=" * 30)
