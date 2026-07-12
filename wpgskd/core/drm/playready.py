import logging
import base64
from typing import Any, Dict, Tuple, Optional
from wpgskd.core.drm.base import BaseDRM
from wpgskd.core.resolver import KeyResolver

log = logging.getLogger("DRM.PlayReady")

class PlayReady(BaseDRM):
    
    def get_keys(self, track: Any, title: Any, session: Any) -> Tuple[Optional[str], Dict[str, str]]:
        cdm = self.cdm_provider.cdm_instance
        
        if cdm.cdm_type != "playready":
            raise ValueError("CDM is not a PlayReady CDM")
            
        pr_pssh = getattr(track, 'pr_pssh', None)
        if not pr_pssh:
            raise ValueError("Track missing PR_PSSH for PlayReady CDM")
            
        try:
            from pyplayready.system.pssh import PSSH as PRPSSH
            wrm = PRPSSH(pr_pssh).wrm_headers[0]
        except Exception:
            raise ValueError("Failed to parse WRM Header from PR_PSSH")

        sid = cdm.open()
        try:
            challenge = cdm.get_license_challenge(sid, wrm).encode('utf-8')
            license_res = self.service.license(
                challenge=challenge, title=title, track=track, session_id=sid
            )
            
            if isinstance(license_res, bytes):
                if b"<License>" in license_res:
                    license_res = base64.b64encode(license_res).decode()
                else:
                    license_res = base64.b64decode(license_res).decode()
                    
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
            raise ValueError(f"PlayReady license request failed: {e}")
        finally:
            cdm.close(sid)