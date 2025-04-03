#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, request, send_file, jsonify, redirect
import os
import logging
import sys
import subprocess
import time
import json
import urllib.request
import re
import signal
import shutil
import tempfile

# Setup logging
logging.basicConfig(level=logging.INFO, filename='/var/log/youtubedl.log', filemode='a')
logger = logging.getLogger('youtubedl')

# Set the port
PORT = 6776
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOME_DIR = os.path.expanduser("~")
FFMPEG_PATH = os.path.join(HOME_DIR, "ffmpeg")
YT_DLP_PATH = os.path.join(BASE_DIR, "venv/bin/yt-dlp")

# Explicitly set HTML_FILE path to the current directory
HTML_FILE = os.path.join(BASE_DIR, "youtubedl.html")

# Create directory for downloads
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
TEMP_DIR = os.path.join(DOWNLOAD_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

logger.info(f"Starting with BASE_DIR: {BASE_DIR}")
logger.info(f"HTML file path set to: {HTML_FILE}")
logger.info(f"Download directory: {DOWNLOAD_DIR}")
logger.info(f"yt-dlp path: {YT_DLP_PATH}")

app = Flask(__name__)

@app.route('/')
def index():
    try:
        logger.info(f"Attempting to serve HTML from: {HTML_FILE}")
        if os.path.exists(HTML_FILE):
            try:
                with open(HTML_FILE, 'r', encoding='utf-8') as f:
                    return f.read()
            except UnicodeDecodeError:
                logger.error("Unicode decode error reading HTML file")
                # Fallback to binary read and decode with error handling
                with open(HTML_FILE, 'rb') as f:
                    content = f.read()
                    return content.decode('utf-8', errors='replace')
        else:
            logger.error(f"HTML file not found at: {HTML_FILE}")
            return f"Error: HTML file not found at {HTML_FILE}", 404
    except Exception as e:
        logger.error(f"Failed to serve HTML: {str(e)}")
        return f"Error: {str(e)}", 500

def get_available_formats(video_id):
    """Get available video formats using yt-dlp"""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Run yt-dlp to list formats
        cmd = [YT_DLP_PATH, "-F", url]
        logger.info(f"Running yt-dlp format command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"yt-dlp format error: {result.stderr}")
            return []
        
        formats = []
        for line in result.stdout.splitlines():
            # Look for lines that contain resolution
            if any(res in line for res in ["x360", "x480", "x720", "x1080"]):
                if "x360" in line:
                    formats.append({"quality": "360p", "available": True})
                elif "x480" in line:
                    formats.append({"quality": "480p", "available": True})
                elif "x720" in line:
                    formats.append({"quality": "720p", "available": True})
                elif "x1080" in line:
                    formats.append({"quality": "1080p", "available": True})
        
        # Remove duplicates while preserving order
        unique_formats = []
        seen = set()
        for fmt in formats:
            if fmt["quality"] not in seen:
                seen.add(fmt["quality"])
                unique_formats.append(fmt)
        
        return unique_formats
    except Exception as e:
        logger.error(f"Error getting formats: {str(e)}")
        return []

def get_video_info_with_yt_dlp(video_id):
    """Get video information using yt-dlp"""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Run yt-dlp to get JSON info about the video
        cmd = [YT_DLP_PATH, "-j", url]
        logger.info(f"Running yt-dlp info command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"yt-dlp info error: {result.stderr}")
            return None
            
        video_info = json.loads(result.stdout)
        return video_info
    except Exception as e:
        logger.error(f"Error getting video info with yt-dlp: {str(e)}")
        return None

@app.route('/api/info')
def get_video_info():
    video_id = request.args.get('id')
    if not video_id:
        return jsonify({'error': 'Missing video ID'}), 400
    
    try:
        # Get video info using yt-dlp
        video_info_data = get_video_info_with_yt_dlp(video_id)
        
        if video_info_data:
            title = video_info_data.get('title', 'YouTube Video')
            thumbnail = video_info_data.get('thumbnail', f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg")
            duration = video_info_data.get('duration', 0)
            
            # Get available formats from format list
            formats = get_available_formats(video_id)
            
            # If no formats were found, use standard options
            if not formats:
                formats = [
                    {'quality': '360p', 'available': True},
                    {'quality': '480p', 'available': True},
                    {'quality': '720p', 'available': True},
                    {'quality': '1080p', 'available': True}
                ]
                
            response = {
                'id': video_id,
                'title': title,
                'thumbnail': thumbnail,
                'duration': duration,
                'available_formats': formats
            }
        else:
            # Fallback to basic info
            response = {
                'id': video_id,
                'title': 'YouTube Video',
                'thumbnail': f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
                'available_formats': [
                    {'quality': '360p', 'available': True},
                    {'quality': '480p', 'available': True},
                    {'quality': '720p', 'available': True},
                    {'quality': '1080p', 'available': True}
                ]
            }
        
        return jsonify(response)
    except Exception as e:
        logger.error(f"Error getting info: {str(e)}")
        return jsonify({"error": str(e)}), 500

def combine_audio_video(video_file, audio_file, output_file):
    """Combine video and audio files using ffmpeg"""
    try:
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            logger.warning("ffmpeg not found in PATH")
            return False
        
        # Command to combine video and audio
        cmd = [
            ffmpeg_path,
            "-i", video_file,
            "-i", audio_file,
            "-c:v", "copy",       # Copy video without re-encoding
            "-c:a", "aac",        # Convert audio to AAC
            "-strict", "experimental",
            "-y",                 # Overwrite output file if it exists
            output_file
        ]
        
        logger.info(f"Running ffmpeg combine command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 10000:
            logger.info(f"Successfully combined files to MP4: {output_file}")
            return True
        else:
            logger.error(f"Combination failed: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error during combination: {str(e)}")
        return False

def convert_to_mp4(input_file, output_file, height=None):
    """Convert any video file to MP4 using ffmpeg with optional scaling"""
    try:
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            logger.warning("ffmpeg not found in PATH")
            return False
        
        # Set video bitrate based on quality
        bitrate_map = {
            "1080": "4M",  # 1080p
            "720": "2.5M",  # 720p
            "480": "1M",    # 480p
            "360": "700k",  # 360p
        }
        
        # Set scale resolution based on quality
        scale_map = {
            "1080": "1920:1080",
            "720": "1280:720",
            "480": "854:480",
            "360": "640:360"
        }
        
        # Base command
        cmd = [
            ffmpeg_path,
            "-i", input_file,
            "-c:v", "libx264",     # Use H.264 for video
            "-c:a", "aac",         # Use AAC for audio
            "-b:a", "128k",        # Audio bitrate
            "-strict", "experimental",
            "-y"                   # Overwrite output file if it exists
        ]
        
        # Add scaling and bitrate if height is specified
        if height and height in ["360", "480", "720", "1080"]:
            bitrate = bitrate_map.get(height, "2M")
            scale = scale_map.get(height, "1280:720")
            
            cmd.extend([
                "-vf", f"scale={scale}", # Scale to resolution
                "-b:v", bitrate,         # Video bitrate
                "-maxrate", bitrate,
                "-bufsize", "2M",
                "-preset", "fast",       # Faster encoding
                "-movflags", "+faststart" # Web optimization
            ])
        
        cmd.append(output_file)
        
        logger.info(f"Running ffmpeg conversion command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 10000:
            logger.info(f"Successfully converted to MP4: {output_file}")
            return True
        else:
            logger.error(f"Conversion failed: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error during conversion: {str(e)}")
        return False

def format_size(size_bytes):
    """Format file size in human-readable format"""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes/(1024*1024):.1f} MB"
    else:
        return f"{size_bytes/(1024*1024*1024):.1f} GB"

def sanitize_filename(filename):
    """Sanitize a string to be used as a filename"""
    # Remove invalid characters for filenames across operating systems
    filename = re.sub(r'[\\/*?:"<>|]', '', filename)
    # Replace multiple spaces with a single space
    filename = re.sub(r'\s+', ' ', filename).strip()
    # Limit filename length (most filesystems have limits around 255 chars)
    if len(filename) > 100:
        filename = filename[:97] + '...'
    return filename

@app.route('/api/download')
def download_video():
    video_id = request.args.get('id')
    quality = request.args.get('quality', '720p')
    
    if not video_id:
        return jsonify({'error': 'Missing video ID'}), 400
    
    try:
        # Get video info first to get the title
        video_info = get_video_info_with_yt_dlp(video_id)
        if not video_info:
            return jsonify({'error': 'Could not retrieve video information'}), 500
        
        # Get video title and sanitize it for use in filename
        video_title = video_info.get('title', 'YouTube Video')
        # Sanitize title for filename use
        safe_title = sanitize_filename(video_title)
        
        # Set up the output file path
        quality_suffix = quality.lower().replace('p', '')
        final_output_file = os.path.join(DOWNLOAD_DIR, f"{safe_title}-{quality}.mp4")
        
        # If the final MP4 file already exists and is valid, serve it
        if os.path.exists(final_output_file) and os.path.getsize(final_output_file) > 1000000:
            logger.info(f"File already exists, serving from cache: {final_output_file}")
            return send_file(
                final_output_file,
                as_attachment=True,
                download_name=f"{safe_title}-{quality}.mp4",
                mimetype="video/mp4"
            )
        
        # Get height from quality
        height = quality.rstrip('p')
        if not height.isdigit():
            height = "720"  # Default if not a valid number
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Direct download approach with ffmpeg post-processing
        temp_dir = tempfile.mkdtemp(dir=TEMP_DIR)
        logger.info(f"Created temporary directory: {temp_dir}")
        
        try:
            # Modified approach: Download video directly at the requested format
            # This simplifies the process and avoids the problematic merge step
            temp_video_path = os.path.join(temp_dir, f"{video_id}_temp.mp4")
            
            # Choose format based on quality
            format_selector = {
                "360": "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
                "480": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
                "720": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
            }.get(height, "best")
            
            # Use yt-dlp to download but skip the merge step - we'll do it with ffmpeg
            cmd = [
                YT_DLP_PATH,
                "-f", format_selector,
                "-o", os.path.join(temp_dir, "%(id)s.%(ext)s"),
                "--no-playlist",
                "--no-check-certificate",
                url
            ]
            
            logger.info(f"Running yt-dlp download command: {' '.join(cmd)}")
            
            # Execute the download
            process = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            logger.info(f"yt-dlp download completed with return code: {process.returncode}")
            
            if process.returncode != 0:
                logger.error(f"yt-dlp error output: {process.stderr}")
                return jsonify({"error": "Failed to download video. Please try again later."}), 500
            
            # Find the downloaded files
            downloaded_files = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
            logger.info(f"Downloaded files: {downloaded_files}")
            
            if not downloaded_files:
                logger.error("No files were downloaded")
                return jsonify({"error": "No video files were downloaded."}), 500
            
            # Choose the best video and audio files
            video_file = None
            audio_file = None
            
            for file in downloaded_files:
                if file.endswith(('.mp4', '.webm', '.mkv')):
                    # Simple approach: pick the largest file as our source
                    if not video_file or os.path.getsize(file) > os.path.getsize(video_file):
                        video_file = file
            
            if not video_file:
                logger.error("No valid video file found")
                return jsonify({"error": "No valid video file was downloaded."}), 500
            
            logger.info(f"Using source file: {video_file} with size {os.path.getsize(video_file)} bytes")
            
            # Now convert the video file to the desired quality using ffmpeg
            logger.info(f"Converting {video_file} to quality {quality}")
            
            if convert_to_mp4(video_file, final_output_file, height):
                logger.info(f"Successfully converted to quality {quality}")
                
                # Serve the file
                if os.path.exists(final_output_file) and os.path.getsize(final_output_file) > 10000:
                    logger.info(f"Serving file: {final_output_file}")
                    return send_file(
                        final_output_file,
                        as_attachment=True,
                        download_name=f"{safe_title}-{quality}.mp4",
                        mimetype="video/mp4"
                    )
                else:
                    logger.error(f"Final file not found or too small: {final_output_file}")
            else:
                logger.error(f"Failed to convert {video_file} to quality {quality}")
                
                # Fallback: just copy the source file if conversion failed
                logger.info(f"Falling back to original file")
                shutil.copy(video_file, final_output_file)
                
                if os.path.exists(final_output_file) and os.path.getsize(final_output_file) > 10000:
                    logger.info(f"Serving original file as fallback: {final_output_file}")
                    return send_file(
                        final_output_file,
                        as_attachment=True,
                        download_name=f"{safe_title}-{quality}.mp4",
                        mimetype="video/mp4"
                    )
            
            # If we get here, something went wrong
            return jsonify({"error": "Failed to process video. Please try again."}), 500
            
        except Exception as e:
            logger.error(f"Error during download/conversion: {str(e)}")
            return jsonify({"error": f"Processing error: {str(e)}"}), 500
        finally:
            # Clean up temp directory
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up temporary directory: {temp_dir}")
            except Exception as cleanup_error:
                logger.error(f"Failed to clean up temp directory: {str(cleanup_error)}")
            
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/debug')
def debug_info():
    try:
        # Try to get ffmpeg version
        try:
            ffmpeg_path = shutil.which('ffmpeg') or os.path.join(FFMPEG_PATH, "ffmpeg")
            result = subprocess.run([ffmpeg_path, "-version"], 
                                   capture_output=True, text=True, timeout=5)
            ffmpeg_version = result.stdout.split('\n')[0] if result.returncode == 0 else "Error"
        except Exception as e:
            ffmpeg_version = f"Error: {str(e)}"
        
        # Try to get yt-dlp version
        try:
            yt_dlp_version = "Not installed"
            if os.path.exists(YT_DLP_PATH):
                result = subprocess.run([YT_DLP_PATH, "--version"], 
                                      capture_output=True, text=True, timeout=5)
                yt_dlp_version = result.stdout.strip() if result.returncode == 0 else "Error"
        except Exception as e:
            yt_dlp_version = f"Error: {str(e)}"
            
        # List directory contents
        try:
            dir_contents = os.listdir(BASE_DIR)
            downloads_contents = os.listdir(DOWNLOAD_DIR) if os.path.exists(DOWNLOAD_DIR) else []
            temp_contents = os.listdir(TEMP_DIR) if os.path.exists(TEMP_DIR) else []
        except Exception as e:
            dir_contents = f"Could not list directory: {str(e)}"
            downloads_contents = "Not available"
            temp_contents = "Not available"
            
        return jsonify({
            'ffmpeg_path': ffmpeg_path,
            'ffmpeg_exists': os.path.exists(ffmpeg_path),
            'ffmpeg_version': ffmpeg_version,
            'yt_dlp_path': YT_DLP_PATH,
            'yt_dlp_exists': os.path.exists(YT_DLP_PATH),
            'yt_dlp_version': yt_dlp_version,
            'python_version': sys.version,
            'html_file_path': HTML_FILE,
            'html_file_exists': os.path.exists(HTML_FILE),
            'base_dir': BASE_DIR,
            'download_dir': DOWNLOAD_DIR,
            'download_dir_exists': os.path.exists(DOWNLOAD_DIR),
            'directory_contents': dir_contents,
            'downloads_contents': downloads_contents,
            'temp_contents': temp_contents,
            'path_environment': os.environ.get('PATH', ''),
            'system_ffmpeg': shutil.which('ffmpeg')
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/list-downloads')
def list_downloads():
    """List all downloaded files"""
    try:
        files = []
        
        # Check main download directory
        if os.path.exists(DOWNLOAD_DIR):
            for filename in os.listdir(DOWNLOAD_DIR):
                if filename.endswith(('.mp4', '.webm', '.mkv')):
                    file_path = os.path.join(DOWNLOAD_DIR, filename)
                    size = os.path.getsize(file_path)
                    modified = os.path.getmtime(file_path)
                    
                    # Extract title and quality from filename
                    # Filename format should be "{title}-{quality}.mp4"
                    quality_match = re.search(r'-(360p|480p|720p|1080p)\.(mp4|webm|mkv)$', filename)
                    quality = quality_match.group(1) if quality_match else "Unknown"
                    
                    # Extract title (everything before the last hyphen)
                    title = filename.rsplit('-', 1)[0] if '-' in filename else filename
                    
                    files.append({
                        'filename': filename,
                        'title': title,
                        'quality': quality,
                        'path': file_path,
                        'size': size,
                        'size_formatted': format_size(size),
                        'modified': modified,
                        'modified_formatted': time.ctime(modified)
                    })
        
        return jsonify({
            'status': 'success',
            'files': files
        })
    except Exception as e:
        logger.error(f"Error listing downloads: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)})

# Try to find and kill processes using port 6776
def kill_port_process():
    try:
        logger.info(f"Attempting to free up port {PORT}...")
        # Try netstat command
        try:
            cmd = ["netstat", "-tunlp"]
            output = subprocess.check_output(cmd, text=True)
            
            for line in output.splitlines():
                if f":{PORT}" in line:
                    pid_match = re.search(r'LISTEN\s+(\d+)', line)
                    if pid_match:
                        pid = pid_match.group(1)
                        logger.info(f"Found process using port {PORT}: PID {pid}")
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                            logger.info(f"Killed process {pid}")
                            return True
                        except Exception as e:
                            logger.error(f"Failed to kill process {pid}: {str(e)}")
        except Exception as e:
            logger.warning(f"Netstat method failed: {str(e)}")
        
        # Try ps and grep as another alternative
        try:
            ps_output = subprocess.check_output(["ps", "-ef"], text=True)
            for line in ps_output.splitlines():
                if f":{PORT}" in line:
                    fields = line.split()
                    if len(fields) > 1:
                        pid = fields[1]
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                            logger.info(f"Killed process {pid}")
                            return True
                        except Exception as e:
                            logger.error(f"Failed to kill process {pid}: {str(e)}")
        except Exception as e:
            logger.warning(f"ps method failed: {str(e)}")
            
        return False
    except Exception as e:
        logger.error(f"Error in kill_port_process: {str(e)}")
        return False

if __name__ == "__main__":
    # Try to find system-wide ffmpeg
    system_ffmpeg = shutil.which('ffmpeg')
    if system_ffmpeg:
        logger.info(f"Found system ffmpeg at: {system_ffmpeg}")
        os.environ['PATH'] = os.path.dirname(system_ffmpeg) + os.pathsep + os.environ.get('PATH', '')
    else:
        # Add standard paths to environment
        os.environ['PATH'] = f"{FFMPEG_PATH}:/usr/bin:/usr/local/bin:/var/services/homes/user/.local/bin:" + os.environ.get('PATH', '')
    
    # Debug info
    try:
        logger.info(f"Current directory: {os.getcwd()}")
        logger.info(f"BASE_DIR: {BASE_DIR}")
    except Exception as e:
        logger.error(f"Error listing directory contents: {str(e)}")
    
    # Try to kill any process using our port
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('0.0.0.0', PORT))
        if result == 0:  # Port is open, so another instance is running
            logger.error(f"Port {PORT} is already in use. Attempting to kill the process...")
            kill_port_process()
        sock.close()
    except Exception as e:
        logger.error(f"Error checking port: {str(e)}")
    
    try:
        app.run(host='0.0.0.0', port=PORT)
    except Exception as e:
        logger.error(f"Failed to start the server: {str(e)}")