import logging
from typing import Any, Dict, Tuple, Optional
from wpgskd.core.drm.base import BaseDRM
from wpgskd.core.resolver import KeyResolver

log = logging.getLogger("DRM.Widevine")

class Widevine(BaseDRM):
    
    def get_keys(self, track: Any, title: Any, session: Any) -> Tuple[Optional[str], Dict[str, str]]:
        cdm = self.cdm_provider.cdm_instance
        
        if cdm.cdm_type != "widevine":
            raise ValueError("CDM is not a Widevine CDM")
            
        pssh_data = getattr(track, 'pssh', None)
        if not pssh_data:
            raise ValueError("Track missing PSSH for Widevine CDM")
            
        sid = cdm.open()
        try:
            challenge = cdm.get_license_challenge(sid, pssh_data, privacy_mode=True)
            license_res = self.service.license(
                challenge=challenge, title=title, track=track, session_id=sid
            )
            cdm.parse_license(sid, license_res)
            
            keys_list = cdm.get_keys(sid)
            result = {}
            target_kid = KeyResolver._norm(track.kid)
            
            for k in keys_list:
                kid = KeyResolver._norm(k.get('kid'))
                key = k.get('key')
                if kid and key and kid != "00" * 16:
                    result[kid] = key.lower()

            primary_key = result.get(target_kid)
            if not primary_key and result:
                primary_key = next(iter(result.values()))
                log.warning(f"No exact KID match for {track.kid}, using fallback key.")
                
            return primary_key, result
            
        except Exception as e:
            raise ValueError(f"Widevine license request failed: {e}")
        finally:
            cdm.close(sid)