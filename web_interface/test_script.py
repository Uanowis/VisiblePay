import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web_interface.settings')
django.setup()

from django.contrib.auth.models import User
from core.models import CreditCard, Order, Operator

user = User.objects.first()
op = Operator.objects.first()
card = CreditCard.objects.filter(user=user).exclude(alias='').first()

if card:
    print(f"Testing card: {card.alias}, Initial usage: {card.usage_count_24h}")
    for i in range(7 - card.usage_count_24h):
        Order.objects.create(user=user, selected_card=card, operator=op, status='COMPLETED')
    print(f"Test orders created. Current usage limit value: {card.usage_count_24h}, Can be used: {card.can_be_used}")
else:
    print("No cards found for first user.")
