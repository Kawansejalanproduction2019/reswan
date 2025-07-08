# Menggunakan image dasar Python
FROM python:3.13.4

# Menginstal FFmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Menyalin file requirements.txt dan menginstal dependensi
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Menyalin semua file proyek ke dalam container
COPY . .

# Menentukan perintah untuk menjalankan aplikasi
CMD ["python", "main.py"]
