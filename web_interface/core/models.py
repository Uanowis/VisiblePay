from django.db import models
from django.contrib.auth.models import User

class Operator(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class CreditCard(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='credit_cards')
    card_alias = models.CharField(max_length=100, help_text="e.g. My Bonus Card")
    card_holder_name = models.CharField(max_length=100)
    card_number = models.CharField(max_length=20) # Store as char for simplicity in this demo
    expiry_date = models.CharField(max_length=5, help_text="MM/YY")
    cvv = models.CharField(max_length=4)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.card_alias} - {self.card_number[-4:]}"

class Order(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('3DS_WAITING', '3DS Waiting'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    phone_number = models.CharField(max_length=20)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name='orders')
    package_id = models.CharField(max_length=100)
    credit_card = models.ForeignKey(CreditCard, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.phone_number} - {self.package_id}"
