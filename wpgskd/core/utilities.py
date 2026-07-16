import re
import base64
import logging
from typing import Optional, Any
from datetime import timedelta
from hashlib import md5

from langcodes import Language, closest_match

from wpgskd.core.constants import LANGUAGE_MAX_DISTANCE
from wpgskd.vendor.pymp4.parser import Box
from pywidevine.cdm import Cdm 
from pywidevine.license_protocol_pb2 import WidevinePsshData

log = logging.getLogger("Utilities")

def get_boxes(data: bytes, box_type: bytes, as_bytes: bool = False):
    """Scan a byte array for a wanted box, then parse and yield each find."""
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("data must be bytes")
    while True:
        try:
            index = data.index(box_type)
        except ValueError:
            break
        if index < 0:
            break
        if index > 4:
            index -= 4  # size is before box type and is 4 bytes long
        data = data[index:]
        try:
            box = Box.parse(data)
        except IOError:
            break
        if as_bytes:
            box = Box.build(box)
        yield box

def is_close_match(language: Any, languages: Any) -> bool:
    if not (language and languages and all(languages)):
        return False
    languages = list(map(str, [x for x in languages if x]))
    return closest_match(language, languages)[1] <= LANGUAGE_MAX_DISTANCE

def get_closest_match(language: Any, languages: Any) -> Optional[Language]:
    match, distance = closest_match(language, list(map(str, languages)))
    if distance > LANGUAGE_MAX_DISTANCE:
        return None
    return Language.get(match)

def numeric_quality(quality: Any) -> int:
    if not quality:
        return 0
    if quality == "SD":
        return 576
    return int(quality)

def try_get(obj: Any, func: callable) -> Any:
    try:
        return func(obj)
    except (AttributeError, IndexError, KeyError, TypeError):
        return None

def short_hash(input: Any) -> str:
    return base_encode(int(md5(str(input).encode()).hexdigest(), 16))

def base_encode(num: int) -> str:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    if num == 0:
        return alphabet[0]
    arr = []
    base = len(alphabet)
    while num:
        num, rem = divmod(num, base)
        arr.append(alphabet[rem])
    return "".join(reversed(arr))

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