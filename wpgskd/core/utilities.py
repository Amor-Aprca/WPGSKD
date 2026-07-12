import re
import logging
from typing import Optional
from datetime import timedelta

log = logging.getLogger("Utilities")

def sanitize_filename(filename: str) -> str:
    if not filename:
        return "unknown"
        
    filename = filename.replace("/", " - ").replace("\\", " - ")
    filename = filename.replace(":", " - ")
    filename = re.sub(r'[\*\?\"\<\>\|]', "", filename)
    filename = filename.replace("&", " and ")
    filename = re.sub(r"[. ]{2,}", ".", filename)
    filename = filename.strip(". ")
    return filename

def pt_to_sec(pt_str: str) -> Optional[float]:
    if not pt_str:
        return None
        
    pt_str = pt_str.strip()
    if pt_str.startswith('P0Y0M0DT'):
        pt_str = pt_str.replace('P0Y0M0DT', 'PT')
    elif pt_str.startswith('P') and 'T' in pt_str:
        pt_str = 'PT' + pt_str.split('T', 1)[1]
    elif not pt_str.startswith('PT'):
        return None
        
    match = re.match(r'PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?', pt_str)
    if not match:
        return None
        
    h = float(match.group(1) or 0)
    m = float(match.group(2) or 0)
    s = float(match.group(3) or 0)
    return h * 3600 + m * 60 + s

def format_duration(seconds: float) -> str:
    if seconds is None:
        return "N/A"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h{m}m{s}s"
    elif m > 0:
        return f"{m}m{s}s"
    else:
        return f"{s}s"

def get_track_size_estimate(bitrate: int, duration_sec: float) -> Optional[int]:
    if not bitrate or not duration_sec or duration_sec <= 0:
        return None
    return int((float(bitrate) * float(duration_sec)) / 8.0)

def humanize_size(num_bytes: int) -> str:
    try:
        size = float(num_bytes)
    except TypeError:
        return "N/A"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.2f} {units[i]}"