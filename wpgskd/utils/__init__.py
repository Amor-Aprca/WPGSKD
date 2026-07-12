from langcodes import Language, closest_match
from typing import Any, Optional, Union
import base64
from hashlib import md5

from wpgskd.core.constants import LANGUAGE_MAX_DISTANCE
from wpgskd.vendor.pymp4.parser import Box

from pywidevine.cdm import Cdm 
from pywidevine.license_protocol_pb2 import WidevinePsshData

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