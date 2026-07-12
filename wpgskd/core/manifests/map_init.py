import logging
import base64
from typing import Optional, Tuple, List
from uuid import UUID

from wpgskd.vendor.pymp4.parser import Box
from pywidevine.license_protocol_pb2 import WidevinePsshData

log = logging.getLogger("MapInit")

def extract_pssh_and_kid(data: bytes) -> Tuple[List[bytes], Optional[str]]:
    pssh_list = []
    kid_hex = None
    
    try:
        for box in _iterate_boxes(data, b"moov"):
            for tenc in _find_boxes(box, b"tenc"):
                if hasattr(tenc, 'key_ID') and tenc.key_ID:
                    kid_hex = tenc.key_ID.hex
                    break
            
            for pssh in _find_boxes(box, b"pssh"):
                if hasattr(pssh, 'init_data') and pssh.init_data:
                    pssh_list.append(Box.build(pssh))
                    
            if kid_hex or pssh_list:
                break
                
    except Exception as e:
        log.debug(f"Failed to parse MP4 boxes for PSSH/KID: {e}")
        
    return pssh_list, kid_hex

def parse_widevine_pssh(pssh_data: bytes) -> Tuple[Optional[bytes], Optional[str]]:
    try:
        box = Box.parse(pssh_data)
        if hasattr(box, 'init_data') and box.init_data:
            cenc_header = WidevinePsshData()
            cenc_header.ParseFromString(box.init_data)
            if cenc_header.key_id:
                kid = cenc_header.key_id[0]
                try:
                    int(kid, 16)
                    kid_hex = kid.decode().lower()
                except ValueError:
                    kid_hex = kid.hex().lower()
                return box, kid_hex
            return box, None
    except Exception:
        pass
    return None, None

def _iterate_boxes(data: bytes, box_type: bytes):
    offset = 0
    while offset + 8 <= len(data):
        try:
            size = int.from_bytes(data[offset:offset+4], "big")
            btype = data[offset+4:offset+8]
            if size < 8: break
            
            if btype == box_type:
                yield data[offset:offset+size]
                
            offset += size
        except Exception:
            offset += 8

def _find_boxes(data: bytes, box_type: bytes):
    offset = 0
    while offset + 8 <= len(data):
        try:
            size = int.from_bytes(data[offset:offset+4], "big")
            btype = data[offset+4:offset+8]
            if size < 8 or offset + size > len(data): break
            
            if btype == box_type:
                box = Box.parse(data[offset:offset+size])
                yield box
                
            offset += size
        except Exception:
            offset += 8