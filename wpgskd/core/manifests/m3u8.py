import base64
import logging
from typing import List, Optional, Tuple, Any
import requests
import m3u8

from wpgskd.core.utilities import Cdm
from wpgskd.vendor.pymp4.parser import Box
from wpgskd.constants import EncryptionScheme

log = logging.getLogger("M3U8Parser")

def parse_media_playlist(url: str, session: requests.Session = None) -> dict:
    if not session:
        session = requests.Session()

    result = {
        "pssh": None,
        "pr_pssh": None,
        "kid": None,
        "aes_key_uri": None,
        "aes_iv": None,
        "init_url": None,
        "segments": []
    }

    try:
        res = session.get(url)
        res.raise_for_status()
        playlist = m3u8.loads(res.text, uri=url)
    except Exception as e:
        log.error(f"Failed to fetch/parse M3U8 playlist {url}: {e}")
        return result

    if playlist.segment_map:
        seg_map = playlist.segment_map
        init_uri = None
        if isinstance(seg_map, dict):
            init_uri = seg_map.get("uri")
        elif hasattr(seg_map, "uri"):
            init_uri = seg_map.uri
            
        if init_uri:
            result["init_url"] = init_uri if init_uri.startswith("http") else f"{playlist.base_uri}{init_uri}"

    for segment in playlist.segments:
        result["segments"].append(segment.absolute_uri)

    keys = playlist.session_keys or playlist.keys
    if not keys:
        return result

    widevine_urn = "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"

    for key in keys:
        if not key or not key.method:
            continue
            
        method = key.method.upper()
        
        if method in ("SAMPLE-AES", "SAMPLE-AES-CTR") and key.keyformat and key.keyformat.lower() == widevine_urn:
            if key.uri and "base64," in key.uri:
                pssh_b64 = key.uri.split("base64,")[-1]
                try:
                    pssh_data = base64.b64decode(pssh_b64)
                    try:
                        result["pssh"] = Box.parse(pssh_data)
                    except Exception:
                        result["pssh"] = Box.parse(Box.build(dict(
                            type=b"pssh", version=0, flags=0, system_ID=Cdm.uuid, init_data=pssh_data
                        )))
                except Exception as e:
                    log.debug(f"Failed to decode Widevine PSSH from M3U8: {e}")


        elif method in ("SAMPLE-AES", "SAMPLE-AES-CTR") and key.keyformat and "playready" in key.keyformat.lower():
            if key.uri and "base64," in key.uri:
                result["pr_pssh"] = key.uri.split("base64,")[-1]

        elif method == "SAMPLE-AES" and key.keyformat and "apple" in key.keyformat.lower():
            result["aes_key_uri"] = key.uri

        elif method == "AES-128":
            result["aes_key_uri"] = key.absolute_uri
            if key.iv:
                result["aes_iv"] = bytes.fromhex(key.iv.replace("0x", ""))
            else:
                pass

    return result


def fetch_pssh_and_kid_from_m3u8(url: str, session: requests.Session = None) -> Tuple[Optional[Any], Optional[str]]:
    data = parse_media_playlist(url, session)
    
    pssh = data.get("pssh")
    kid = data.get("kid")
    
    if (not pssh or not kid) and data.get("init_url"):
        try:
            from wpgskd.core.manifests.map_init import extract_pssh_and_kid
            if not session:
                session = requests.Session()
            resp = session.get(data["init_url"], stream=True)
            chunk = next(resp.iter_content(20000), b"")
            pssh_list, kid_hex = extract_pssh_and_kid(chunk)
            if not pssh and pssh_list:
                pssh = pssh_list[0]
            if not kid and kid_hex:
                kid = kid_hex
        except Exception as e:
            log.debug(f"Failed to extract PSSH/KID from init.mp4 ({data['init_url']}): {e}")
            
    return pssh, kid

def fetch_aes_keys_from_m3u8(url: str, session: requests.Session = None) -> Tuple[Optional[str], Optional[bytes]]:
    data = parse_media_playlist(url, session)
    return data.get("aes_key_uri"), data.get("aes_iv")