from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
import os
import uuid
import subprocess
import asyncio
from datetime import datetime
import shutil
from pathlib import Path
import uvicorn

app = FastAPI(title="M3U8 Video Downloader Proxy", version="1.0.0")

# Base download directory
DOWNLOAD_BASE_DIR = "downloads"

# Ensure downloads directory exists
os.makedirs(DOWNLOAD_BASE_DIR, exist_ok=True)

@app.get("/")
async def root():
    # Check if ffmpeg is available
    ffmpeg_available = False
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10)
        ffmpeg_available = result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    return {
        "message": "M3U8 Video Downloader Proxy", 
        "status": "running",
        "ffmpeg_available": ffmpeg_available,
        "usage": "GET /stream?url=<m3u8_url> to download videos directly"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

async def download_m3u8_video(url: str, download_dir: str):
    """Download M3U8 video using ffmpeg"""
    try:
        # Check if ffmpeg is available
        try:
            ffmpeg_check = await asyncio.create_subprocess_exec(
                "ffmpeg", "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await ffmpeg_check.communicate()
            if ffmpeg_check.returncode != 0:
                return {"status": "error", "message": "FFmpeg is not available in the system"}
        except FileNotFoundError:
            return {"status": "error", "message": "FFmpeg is not installed"}
        
        # Generate output filename
        output_file = os.path.join(download_dir, f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
        
        # Use ffmpeg to download M3U8 stream
        cmd = [
            "ffmpeg",
            "-i", url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-y",  # Overwrite output file
            "-timeout", "30000000",  # 30 second timeout
            output_file
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0 and os.path.exists(output_file):
            file_size = os.path.getsize(output_file)
            return {
                "status": "success", 
                "message": "Download completed",
                "file_path": output_file,
                "file_size": file_size
            }
        else:
            error_msg = stderr.decode() if stderr else "Unknown error"
            return {"status": "error", "message": f"Download failed: {error_msg}"}
            
    except Exception as e:
        return {"status": "error", "message": f"Exception occurred: {str(e)}"}

@app.get("/stream")
@app.post("/stream")
async def stream_download_video(url: str = Query(..., description="M3U8 URL to download and stream directly")):
    """Download M3U8 video and stream it directly to user"""
    if not url:
        raise HTTPException(status_code=400, detail="URL parameter is required")
    
    if not url.startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="Invalid URL format")
    
    # Generate unique directory for this download
    download_id = str(uuid.uuid4())
    download_dir = os.path.join(DOWNLOAD_BASE_DIR, download_id)
    os.makedirs(download_dir, exist_ok=True)
    
    try:
        # Download the video
        result = await download_m3u8_video(url, download_dir)
        
        if result["status"] == "success":
            file_path = result["file_path"]
            filename = os.path.basename(file_path)
            
            # Stream the file directly to user
            return FileResponse(
                file_path,
                media_type='video/mp4',
                filename=filename,
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        else:
            # Clean up failed download directory
            shutil.rmtree(download_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail=result["message"])
            
    except Exception as e:
        # Clean up on error
        shutil.rmtree(download_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@app.get("/download")
@app.post("/download")
async def download_video(url: str = Query(..., description="M3U8 URL to download")):
    """Download M3U8 video from provided URL"""
    if not url:
        raise HTTPException(status_code=400, detail="URL parameter is required")
    
    if not url.startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="Invalid URL format")
    
    # Generate unique directory for this download
    download_id = str(uuid.uuid4())
    download_dir = os.path.join(DOWNLOAD_BASE_DIR, download_id)
    os.makedirs(download_dir, exist_ok=True)
    
    try:
        # Download the video
        result = await download_m3u8_video(url, download_dir)
        
        if result["status"] == "success":
            return {
                "download_id": download_id,
                "status": "completed",
                "message": "Video downloaded successfully",
                "download_path": download_dir,
                "file_info": {
                    "file_path": result["file_path"],
                    "file_size": result["file_size"]
                }
            }
        else:
            # Clean up failed download directory
            shutil.rmtree(download_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail=result["message"])
            
    except Exception as e:
        # Clean up on error
        shutil.rmtree(download_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
