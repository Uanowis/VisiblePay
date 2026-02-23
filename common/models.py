from django.db import models
from django.utils.translation import gettext_lazy as _

class Operator(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, db_index=True)
    base_url = models.URLField(max_length=200)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class CreditCard(models.Model):
    alias = models.CharField(max_length=100)
    holder_name = models.CharField(max_length=100)
    # Storing plain text for now as requested
    card_number = models.CharField(max_length=20) 
    exp_month = models.CharField(max_length=2)
    exp_year = models.CharField(max_length=4)
    cvv = models.CharField(max_length=4)

    def __str__(self):
        return f"{self.alias} ({self.card_number[-4:]})"

class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        PROCESSING = 'PROCESSING', _('Processing')
        WAITING_3DS = '3DS_WAITING', _('3DS Waiting')
        COMPLETED = 'COMPLETED', _('Completed')
        FAILED = 'FAILED', _('Failed')

    phone_number = models.CharField(max_length=20)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name='orders')
    
    # Amount or Package ID depending on type
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    package_id = models.CharField(max_length=100, null=True, blank=True)
    
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    
    log_message = models.TextField(blank=True, null=True)
    selected_card = models.ForeignKey(
        CreditCard, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='orders'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order {self.id} - {self.phone_number} ({self.status})"

class SMSLog(models.Model):
    sender = models.CharField(max_length=50)
    message_content = models.TextField()
    received_at = models.DateTimeField(auto_now_add=True)
    related_order = models.ForeignKey(
        Order, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='sms_logs'
    )

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f"SMS from {self.sender} at {self.received_at}"
