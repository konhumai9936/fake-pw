FROM python:3.11-slim

# Install ffmpeg for M3U8 video processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create downloads directory
RUN mkdir -p downloads

# Verify ffmpeg installation
RUN ffmpeg -version

# Expose port
EXPOSE 8000

# Start the application
CMD ["python", "app.py"]
