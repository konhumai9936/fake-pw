# M3U8 Video Downloader Proxy

A fast and simple proxy service for downloading M3U8 video streams. Perfect for Railway deployment.

## Features

- Download M3U8 video streams using FFmpeg
- Each download creates a unique directory
- RESTful API with FastAPI
- Railway-ready deployment configuration
- Health check endpoint
- Download status tracking

## API Endpoints

### `GET /`
Returns service information and usage instructions.

### `POST /download?url=<m3u8_url>`
Downloads a video from the provided M3U8 URL.

**Parameters:**
- `url` (required): The M3U8 URL to download

**Response:**
```json
{
  "download_id": "unique-uuid",
  "status": "completed",
  "message": "Video downloaded successfully",
  "download_path": "downloads/unique-uuid",
  "file_info": {
    "file_path": "downloads/unique-uuid/video_20231201_120000.mp4",
    "file_size": 12345678
  }
}
```

### `GET /download/{download_id}/status`
Check the status of a specific download.

### `GET /downloads`
List all download directories and their information.

### `GET /health`
Health check endpoint for monitoring.

## Usage Examples

### Download a video
```bash
curl -X POST "https://your-app.railway.app/download?url=https://example.com/video.m3u8"
```

### Check download status
```bash
curl "https://your-app.railway.app/download/your-download-id/status"
```

## Railway Deployment

1. Push this code to a GitHub repository
2. Connect your GitHub repo to Railway
3. Railway will automatically detect the configuration and deploy

The service will be available at your Railway-provided URL.

## Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the service:
```bash
python app.py
```

The service will be available at `http://localhost:8000`

## Requirements

- Python 3.11+
- FFmpeg (automatically installed in Docker/Railway)
- FastAPI and Uvicorn

## Notes

- Each download creates a new directory with a unique UUID
- Videos are saved as MP4 files with timestamps
- The service uses FFmpeg for reliable M3U8 stream processing
- Failed downloads automatically clean up their directories
