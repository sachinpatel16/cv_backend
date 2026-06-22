FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install build and runtime dependencies for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \

    && rm -rf /var/lib/apt/lists/*


# Copy only requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

# Expose application port (adjust if different)
EXPOSE 8000

# Set default command (adjust if using gunicorn/uvicorn etc.)
CMD ["python", "main.py"]
