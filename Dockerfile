# Menggunakan image dasar Python
FROM python:3.13.4-slim

# Menginstal FFmpeg dan dependencies
RUN apt-get update && \
    apt-get install -y \
    ffmpeg \
    libopus0 \
    libsodium23 \
    git \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Menyalin file requirements.txt dan menginstal dependensi
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Menyalin semua file proyek ke dalam container
COPY . .

# Buat directory untuk data
RUN mkdir -p data downloads reswan/data

# Menentukan perintah untuk menjalankan aplikasi
CMD ["python", "main.py"]
