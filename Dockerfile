FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.txt /app/
RUN pip install --default-timeout=1000 --no-cache-dir -r requirements.txt

# Copy project
COPY . /app/

# Add a step to collect static files (assuming SQLite or temporary DB works for collecting static files)
RUN python web_interface/manage.py collectstatic --noinput

# Expose port (for Django)
EXPOSE 8000

# Default command (overridden in docker-compose)
CMD ["gunicorn", "web_interface.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
