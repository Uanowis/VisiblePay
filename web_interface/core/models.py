from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

class Operator(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, db_index=True)
    base_url = models.URLField(max_length=200)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class Package(models.Model):
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name='packages')
    category = models.CharField(max_length=100, default='General')
    name = models.CharField(max_length=100)
    package_id = models.CharField(max_length=100, help_text="ID used in automation")
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    code = models.CharField(max_length=50, null=True, blank=True, help_text="Package code (Küpür) from API")
    
    def __str__(self):
        base_str = f"[{self.category}] {self.name} ({self.price} TL)" if self.price else self.name
        return f"{base_str} - Code: {self.code}" if self.code else base_str

class CreditCard(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='credit_cards')
    alias = models.CharField(max_length=100)
    holder_name = models.CharField(max_length=100)
    # Storing plain text for now as requested
    card_number = models.CharField(max_length=20) 
    exp_month = models.CharField(max_length=2)
    exp_year = models.CharField(max_length=4)
    cvv = models.CharField(max_length=4)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.alias} ({self.card_number[-4:]})"

    @property
    def usage_count_24h(self):
        """Returns the number of non-failed orders made with this card in the last 24 hours."""
        now = timezone.now()
        start_time = now - timezone.timedelta(hours=24)
        from .models import Order
        return self.orders.filter(
            created_at__gte=start_time
        ).exclude(status=Order.Status.FAILED).count()

    @property
    def can_be_used(self):
        """Returns True if the card can be used (used less than 6 times in 24h)."""
        return self.usage_count_24h < 6

class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        PROCESSING = 'PROCESSING', _('Processing')
        WAITING_3DS = '3DS_WAITING', _('3DS Waiting')
        WAITING_MANUAL_ACTION = 'WAITING_MANUAL_ACTION', _('Waiting Manual Action')
        COMPLETED = 'COMPLETED', _('Completed')
        FAILED = 'FAILED', _('Failed')

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    phone_number = models.CharField(max_length=20)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name='orders')
    
    # Amount or Package ID depending on type
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    package_id = models.CharField(max_length=100, null=True, blank=True)
    
    status = models.CharField(
        max_length=30,
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
    balance_went_negative = models.BooleanField(default=False)

    # Scrape Results
    resolved_package_name = models.CharField(max_length=200, null=True, blank=True, help_text="The exact package name found and clicked by the robot")
    final_screenshot = models.ImageField(upload_to='order_screenshots/', null=True, blank=True, help_text="Screenshot of the browser at the final moment of the state")

    # API Integration Fields
    external_ref = models.CharField(max_length=100, null=True, blank=True, unique=True, help_text="Reference ID from external API")
    api_source = models.CharField(max_length=50, default='WEB', help_text="Source of the order (WEB, MATIK)")
    raw_api_data = models.TextField(blank=True, null=True, help_text="Raw data received from API")

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

class TestRun(models.Model):
    STATUS_CHOICES = [
        ('RUNNING', 'Running'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
    ]
    
    operator_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RUNNING')
    logs = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    
    def append_log(self, message):
        self.logs += f"[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
        self.save()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Test {self.id} - {self.operator_name} ({self.status})"

class SystemSetting(models.Model):
    is_autonomous_active = models.BooleanField(default=False, help_text="Sistemi açıp kapatma anahtarı")
    default_card = models.ForeignKey(
        CreditCard, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='+',
        help_text="Otomatik işlemlerde kullanılacak varsayılan kart"
    )

    class Meta:
        verbose_name = "Sistem Ayarı"
        verbose_name_plural = "Sistem Ayarları"

    @classmethod
    def get_settings(cls):
        obj, created = cls.objects.get_or_create(id=1)
        return obj

    def __str__(self):
        return "Global Sistem Ayarları"
