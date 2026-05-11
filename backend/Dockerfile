FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Note: openbuilder is invoked via host Python subprocess, not installed in container
COPY . .

# Create downloads directory
RUN mkdir -p /app/downloads

EXPOSE 8080

CMD ["python", "app.py"]
