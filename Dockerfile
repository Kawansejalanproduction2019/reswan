FROM python:3.13.4-slim

RUN apt-get update && \
    apt-get install -y \
    ffmpeg \
    libopus0 \
    libopus-dev \
    libsodium23 \
    libsodium-dev \
    git \
    curl \
    nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data downloads reswan/data

CMD ["python", "main.py"]
