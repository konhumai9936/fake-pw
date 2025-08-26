from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
import os
import uuid
import subprocess
import asyncio
from datetime import datetime
import shutil
import uvicorn
import re
import time

app = FastAPI(title="M3U8 Video Downloader", version="1.0.0")

# Base download directory
DOWNLOAD_BASE_DIR = "downloads"
os.makedirs(DOWNLOAD_BASE_DIR, exist_ok=True)

# Global progress tracking (minimal - only ETA and speed)
download_progress = {}

@app.get("/")
async def root():
    # Check FFmpeg availability for diagnostics
    ffmpeg_available = False
    ffmpeg_error = None
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10)
        ffmpeg_available = result.returncode == 0
    except FileNotFoundError:
        ffmpeg_error = "FFmpeg not found"
    except subprocess.TimeoutExpired:
        ffmpeg_error = "FFmpeg timeout"
    except Exception as e:
        ffmpeg_error = str(e)
    
    return {
        "message": "M3U8 Video Downloader", 
        "status": "running",
        "ffmpeg_available": ffmpeg_available,
        "ffmpeg_error": ffmpeg_error,
        "endpoints": {
            "stream": "GET/POST /stream?url=<m3u8_url> - Download and stream video directly",
            "cancel": "POST /cancel/<download_id> - Cancel ongoing download"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint for Railway"""
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "service": "M3U8 Video Downloader"
    }

async def download_m3u8_video_with_progress(url: str, download_dir: str, download_id: str):
    """Download M3U8 video with minimal progress tracking (ETA + Speed only)"""
    try:
        # Initialize minimal progress
        download_progress[download_id] = {
            "status": "downloading",
            "speed": "0 MB/s",
            "eta": "calculating...",
            "start_time": time.time(),
            "bytes_downloaded": 0
        }
        
        # Generate output filename
        output_file = os.path.join(download_dir, f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
        
        # FFmpeg command with progress output
        cmd = [
            "ffmpeg", "-i", url, "-c", "copy", "-bsf:a", "aac_adtstoasc", 
            "-y", "-timeout", "30000000", "-progress", "pipe:1", output_file
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        
        # Monitor progress (minimal - only speed and ETA)
        async def monitor_progress():
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                line = line.decode().strip()
                
                if "size=" in line:
                    size_match = re.search(r'size=\s*(\d+)', line)
                    if size_match:
                        bytes_downloaded = int(size_match.group(1)) * 1024
                        download_progress[download_id]["bytes_downloaded"] = bytes_downloaded
                        
                        # Calculate speed and ETA
                        elapsed = time.time() - download_progress[download_id]["start_time"]
                        if elapsed > 0:
                            speed_mbps = (bytes_downloaded / elapsed) / (1024 * 1024)
                            download_progress[download_id]["speed"] = f"{speed_mbps:.2f} MB/s"
                            
                            # Simple ETA estimation
                            if bytes_downloaded > 1024 * 1024:  # After 1MB downloaded
                                estimated_total = bytes_downloaded * 15  # Rough estimate
                                remaining = estimated_total - bytes_downloaded
                                eta_seconds = remaining / (bytes_downloaded / elapsed)
                                eta_minutes = int(eta_seconds // 60)
                                eta_secs = int(eta_seconds % 60)
                                download_progress[download_id]["eta"] = f"{eta_minutes}:{eta_secs:02d}"
        
        # Start progress monitoring
        progress_task = asyncio.create_task(monitor_progress())
        stdout, stderr = await process.communicate()
        progress_task.cancel()
        
        if process.returncode == 0 and os.path.exists(output_file):
            download_progress[download_id]["status"] = "completed"
            return {"status": "success", "file_path": output_file, "file_size": os.path.getsize(output_file)}
        else:
            download_progress[download_id]["status"] = "error"
            return {"status": "error", "message": stderr.decode() if stderr else "Download failed"}
            
    except Exception as e:
        download_progress[download_id]["status"] = "error"
        return {"status": "error", "message": str(e)}

@app.get("/stream")
@app.post("/stream")
async def stream_download_video(url: str = Query(None, description="M3U8 URL to download and stream directly")):
    """Download M3U8 video and stream it directly to user"""
    try:
        # Better URL validation
        if not url:
            raise HTTPException(status_code=400, detail="URL parameter is required")
        
        if not url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail="Valid HTTP/HTTPS URL required")
        
        # Check FFmpeg availability first
        try:
            ffmpeg_check = await asyncio.create_subprocess_exec(
                "ffmpeg", "-version", 
                stdout=asyncio.subprocess.PIPE, 
                stderr=asyncio.subprocess.PIPE
            )
            await ffmpeg_check.communicate()
            if ffmpeg_check.returncode != 0:
                raise HTTPException(status_code=500, detail="FFmpeg not available on server")
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="FFmpeg not installed on server")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"FFmpeg check failed: {str(e)}")
        
        download_id = str(uuid.uuid4())
        download_dir = os.path.join(DOWNLOAD_BASE_DIR, download_id)
        os.makedirs(download_dir, exist_ok=True)
        
        result = await download_m3u8_video_with_progress(url, download_dir, download_id)
        
        if result["status"] == "success":
            file_path = result["file_path"]
            if not os.path.exists(file_path):
                shutil.rmtree(download_dir, ignore_errors=True)
                raise HTTPException(status_code=500, detail="Downloaded file not found")
            
            filename = os.path.basename(file_path)
            
            return FileResponse(
                file_path,
                media_type='video/mp4',
                filename=filename,
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        else:
            shutil.rmtree(download_dir, ignore_errors=True)
            error_msg = result.get("message", "Unknown download error")
            raise HTTPException(status_code=500, detail=f"Download failed: {error_msg}")
            
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        # Clean up on any unexpected error
        try:
            if 'download_dir' in locals() and os.path.exists(download_dir):
                shutil.rmtree(download_dir, ignore_errors=True)
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

@app.post("/cancel/{download_id}")
async def cancel_download(download_id: str):
    """Cancel an ongoing download"""
    if download_id not in download_progress:
        raise HTTPException(status_code=404, detail="Download ID not found")
    
    if download_progress[download_id]["status"] != "downloading":
        raise HTTPException(status_code=400, detail="Download cannot be cancelled")
    
    download_progress[download_id]["status"] = "cancelled"
    
    # Clean up
    download_dir = os.path.join(DOWNLOAD_BASE_DIR, download_id)
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir, ignore_errors=True)
    
    return {"download_id": download_id, "status": "cancelled", "message": "Download cancelled"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
