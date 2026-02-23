import os
import django
from celery import Celery

# Set the default Django settings module for the 'celery' program.
# We need to make sure the worker can find the implementation
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../web_interface'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web_interface.settings')
django.setup()

app = Celery('worker')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
