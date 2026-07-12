import logging
import base64
import requests
from typing import Any, Dict, Tuple, Optional
from wpgskd.core.drm.base import BaseDRM
from wpgskd.core.resolver import KeyResolver

log = logging.getLogger("DRM.ClearKey")

class ClearKey(BaseDRM):
    
    def get_keys(self, track: Any, title: Any, session: Any) -> Tuple[Optional[str], Dict[str, str]]:
        if getattr(track, 'key', None):
            kid = KeyResolver._norm(track.kid)
            return track.key, {kid: track.key}
            
        license_url = getattr(track, 'license_url', None)
        if not license_url:
            raise ValueError("Track missing license_url for ClearKey")
            
        kid_hex = track.kid.replace("-", "")
        kid_b64 = base64.b64encode(bytes.fromhex(kid_hex)).decode()
        
        payload = {"kids": [kid_b64], "type": "temporary"}
        
        try:
            res = session.post(license_url, json=payload)
            res.raise_for_status()
            data = res.json()
            
            k_b64 = data.get("keys", [{}])[0].get("k")
            if not k_b64:
                raise ValueError("No key returned from ClearKey server")
                
            key_hex = base64.b64decode(k_b64).hex()
            return key_hex, {kid_hex: key_hex}
            
        except Exception as e:
            raise ValueError(f"ClearKey request failed: {e}")