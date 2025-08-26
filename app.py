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

async def download_m3u8_video_with_progress(url: str, download_dir: str, download_id: str):
    """Download M3U8 video using ffmpeg with detailed progress tracking"""
    try:
        # Initialize progress tracking
        download_progress[download_id] = {
            "status": "initializing",
            "progress_percent": 0,
            "segments_downloaded": 0,
            "total_segments": 0,
            "download_speed": "0 MB/s",
            "eta": "calculating...",
            "current_segment": "",
            "start_time": time.time(),
            "bytes_downloaded": 0,
            "total_bytes": 0,
            "error": None
        }
        
        # Check if ffmpeg is available
        try:
            ffmpeg_check = await asyncio.create_subprocess_exec(
                "ffmpeg", "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await ffmpeg_check.communicate()
            if ffmpeg_check.returncode != 0:
                download_progress[download_id]["status"] = "error"
                download_progress[download_id]["error"] = "FFmpeg is not available in the system"
        
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
async def stream_download_video(url: str = Query(..., description="M3U8 URL to download and stream directly")):
    """Download M3U8 video and stream it directly to user"""
    if not url or not url.startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="Valid URL required")
    
    download_id = str(uuid.uuid4())
    download_dir = os.path.join(DOWNLOAD_BASE_DIR, download_id)
    os.makedirs(download_dir, exist_ok=True)
    
    try:
        result = await download_m3u8_video_with_progress(url, download_dir, download_id)
        
        if result["status"] == "success":
            file_path = result["file_path"]
            filename = os.path.basename(file_path)
            
            return FileResponse(
                file_path,
                media_type='video/mp4',
                filename=filename,
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        else:
            shutil.rmtree(download_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail=result["message"])
            
    except Exception as e:
        shutil.rmtree(download_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@app.post("/cancel/{download_id}")
async def cancel_download(download_id: str):
    """Cancel an ongoing download"""
    if download_id not in download_progress:
        raise HTTPException(status_code=404, detail="Download ID not found")
    
    if download_progress[download_id]["status"] not in ["downloading", "initializing"]:
        raise HTTPException(status_code=400, detail="Download cannot be cancelled in current state")
    
    # Update status to cancelled
    download_progress[download_id]["status"] = "cancelled"
    
    # Clean up download directory
    download_dir = os.path.join(DOWNLOAD_BASE_DIR, download_id)
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir, ignore_errors=True)
    
    return {
        "download_id": download_id,
        "status": "cancelled",
        "message": "Download cancelled successfully"
    }

@app.get("/progress/{download_id}")
async def get_download_progress(download_id: str):
    """Get real-time download progress - Perfect for web UI!"""
    if download_id not in download_progress:
        raise HTTPException(status_code=404, detail="Download ID not found or not started")
    
    progress_data = download_progress[download_id].copy()
    
    return {
        "download_id": download_id,
        "status": progress_data["status"],
        "progress": {
            "percent": progress_data["progress_percent"],
            "segments": {
                "downloaded": progress_data["segments_downloaded"],
                "total": progress_data["total_segments"],
                "display": f"{progress_data['segments_downloaded']}/{progress_data['total_segments']}"
            },
            "speed": progress_data["download_speed"],
            "eta": progress_data["eta"],
            "current_segment": progress_data["current_segment"],
            "bytes": {
                "downloaded": progress_data["bytes_downloaded"],
                "total": progress_data["total_bytes"],
                "downloaded_mb": round(progress_data["bytes_downloaded"] / (1024 * 1024), 2),
                "total_mb": round(progress_data["total_bytes"] / (1024 * 1024), 2)
            }
        },
        "error": progress_data.get("error"),
        "can_cancel": progress_data["status"] in ["downloading", "initializing"]
    }

@app.post("/cancel/{download_id}")
async def cancel_download(download_id: str):
    """Cancel an ongoing download"""
    if download_id not in download_progress:
        raise HTTPException(status_code=404, detail="Download ID not found")
    
    if download_progress[download_id]["status"] not in ["downloading", "initializing"]:
        raise HTTPException(status_code=400, detail="Download cannot be cancelled in current state")
    
    # Update status to cancelled
    download_progress[download_id]["status"] = "cancelled"
    download_progress[download_id]["current_segment"] = "Download cancelled by user"
    
    # Clean up download directory
    download_dir = os.path.join(DOWNLOAD_BASE_DIR, download_id)
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir, ignore_errors=True)
    
    return {
        "download_id": download_id,
        "status": "cancelled",
        "message": "Download cancelled successfully"
    }

@app.get("/download/{download_id}/status")
async def get_download_status(download_id: str):
    """Check status of a download (legacy endpoint)"""
    download_dir = os.path.join(DOWNLOAD_BASE_DIR, download_id)
    
    if not os.path.exists(download_dir):
        raise HTTPException(status_code=404, detail="Download ID not found")
    
    # List files in download directory
    files = []
    for file in os.listdir(download_dir):
        file_path = os.path.join(download_dir, file)
        if os.path.isfile(file_path):
            files.append({
                "filename": file,
                "size": os.path.getsize(file_path),
                "modified": datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat()
            })
    
    return {
        "download_id": download_id,
        "status": "completed" if files else "processing",
        "files": files
    }

@app.get("/download/{download_id}/file/{filename}")
async def serve_download_file(download_id: str, filename: str):
    """Serve a downloaded file for download"""
    file_path = os.path.join(DOWNLOAD_BASE_DIR, download_id, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        file_path, 
        media_type='video/mp4',
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/download/{download_id}/files")
async def list_download_files(download_id: str):
    """List all files in a download directory with download links"""
    download_dir = os.path.join(DOWNLOAD_BASE_DIR, download_id)
    
    if not os.path.exists(download_dir):
        raise HTTPException(status_code=404, detail="Download ID not found")
    
    files = []
    for file in os.listdir(download_dir):
        file_path = os.path.join(download_dir, file)
        if os.path.isfile(file_path):
            files.append({
                "filename": file,
                "size": os.path.getsize(file_path),
                "size_mb": round(os.path.getsize(file_path) / (1024 * 1024), 2),
                "modified": datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat(),
                "download_url": f"/download/{download_id}/file/{file}"
            })
    
    return {
        "download_id": download_id,
        "files": files,
        "total_files": len(files)
    }

@app.get("/downloads")
async def list_downloads():
    """List all download directories"""
    if not os.path.exists(DOWNLOAD_BASE_DIR):
        return {"downloads": []}
    
    downloads = []
    for item in os.listdir(DOWNLOAD_BASE_DIR):
        item_path = os.path.join(DOWNLOAD_BASE_DIR, item)
        if os.path.isdir(item_path):
            # Get files in directory
            files = [f for f in os.listdir(item_path) if os.path.isfile(os.path.join(item_path, f))]
            file_count = len(files)
            
            # Get total size
            total_size = sum(os.path.getsize(os.path.join(item_path, f)) for f in files)
            
            downloads.append({
                "download_id": item,
                "created": datetime.fromtimestamp(os.path.getctime(item_path)).isoformat(),
                "file_count": file_count,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "files_url": f"/download/{item}/files"
            })
    
    return {"downloads": downloads}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
