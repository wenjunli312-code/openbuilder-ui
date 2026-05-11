FROM python:3.11-slim

WORKDIR /app

# Install git for cloning repos
RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Install docker CLI (static binary) to run dockcross containers
RUN curl -fsSL https://download.docker.com/linux/static/stable/aarch64/docker-27.5.1.tgz | \
    tar xzf - --strip-components=1 -C /usr/bin docker/docker && \
    docker --version

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/downloads

EXPOSE 8080

CMD ["python", "app.py"]
