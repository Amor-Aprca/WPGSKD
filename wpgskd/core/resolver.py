import logging
import traceback
from typing import Optional, Tuple, Dict, Any
from uuid import UUID

from wpgskd.core.cdm.loader import CdmProvider
from wpgskd.core.vaults import Vaults
from wpgskd.core.vault import InsertResult
from wpgskd.core.tracks.video import VideoTrack

try:
    from wpgskd.utils.monalisa import MonaLisa
    MONALISA_AVAILABLE = True
except ImportError:
    MONALISA_AVAILABLE = False
    MonaLisa = None

log = logging.getLogger("Resolver")

class KeyResolver:
    def __init__(self, vaults: Vaults, cdm_provider: CdmProvider, use_cache: bool = True, use_cdm: bool = True):
        self.vaults = vaults
        self.cdm_provider = cdm_provider
        self.use_cache = use_cache
        self.use_cdm = use_cdm
        self._license_cache = {}

    def resolve(self, track: Any, title: Any, service: Any, service_name: str, session: Any = None) -> Tuple[Optional[str], Dict[str, str]]:
        all_keys: Dict[str, str] = {}

        if MONALISA_AVAILABLE and getattr(track, 'monalisa', False) and getattr(track, 'key', None):
            log.info(f" + KEY: {track.key} (From MonaLisa)")
            if track.kid:
                all_keys[self._norm(track.kid)] = track.key
            return track.key, all_keys

        if self.use_cache and not getattr(track, 'key', None):
            track.key, vault_used = self.vaults.get(track.kid, title.id)
            if track.key:
                log.debug(f" + KEY: {track.key} (From {vault_used.name} Vault)")
                self._sync_vault(track.kid, track.key, title.id, service_name, vault_used)
                all_keys[self._norm(track.kid)] = track.key
                return track.key, all_keys
        if self.use_cdm and not getattr(track, 'key', None):
            try:
                content_keys = self._license(track, title, service, service_name, session)
                if content_keys:
                    all_keys.update(content_keys)
                    primary_key = self._match(track, content_keys, service_name)
                    if primary_key:
                        self._cache_all(content_keys, service_name, title.id)
                        return primary_key, all_keys
            except Exception as e:
                log.debug(traceback.format_exc())
                raise ValueError(f"CDM license error: {e}")

        return None, all_keys

    def _license(self, track: Any, title: Any, service: Any, service_name: str, session: Any) -> Optional[Dict[str, str]]:
        cdm = self.cdm_provider.cdm_instance
        
        if self.cdm_provider.cdm_instance.cdm_type == "playready":
            return self._pr_license(cdm, track, title, service)
            
        return self._wv_license(cdm, track, title, service, service_name)

    def _wv_license(self, cdm: Any, track: Any, title: Any, service: Any, service_name: str) -> Dict[str, str]:
        pssh_data = getattr(track, 'pssh', None)
        if not pssh_data:
            raise ValueError("Track missing PSSH for Widevine CDM")
            
        pssh_key = str(pssh_data)
        if pssh_key in self._license_cache:
            return self._license_cache[pssh_key]
            
        sid = cdm.open()
        try:
            challenge = cdm.get_license_challenge(sid, pssh_data, privacy_mode=True)
            license_res = service.license(
                challenge=challenge, 
                title=title, 
                track=track, 
                session_id=sid,
                drm_type="widevine"
            )
            cdm.parse_license(sid, license_res)
            
            keys_list = cdm.get_keys(sid)
            result = {}
            for k in keys_list:
                kid = self._norm(k.get('kid'))
                key = k.get('key')
                if kid and key and kid != "00" * 16:
                    result[kid] = key.lower()
            
            self._license_cache[pssh_key] = result
            return result
            
        except Exception as e:
            raise ValueError(f"Widevine license request failed: {e}")
        finally:
            cdm.close(sid)

    def _pr_license(self, cdm: Any, track: Any, title: Any, service: Any) -> Dict[str, str]:
        pr_pssh = getattr(track, 'pr_pssh', None)
        if not pr_pssh:
            raise ValueError("Track missing PR_PSSH for PlayReady CDM")
            
        pssh_key = str(pr_pssh)
        if pssh_key in self._license_cache:
            return self._license_cache[pssh_key]
            
        try:
            from pyplayready.system.pssh import PSSH as PRPSSH
            wrm = PRPSSH(pr_pssh).wrm_headers[0]
        except Exception:
            raise ValueError("Failed to parse WRM Header from PR_PSSH")

        sid = cdm.open()
        try:
            challenge = cdm.get_license_challenge(sid, wrm).encode('utf-8')
            license_res = service.license(
                challenge=challenge, 
                title=title, 
                track=track, 
                session_id=sid,
                drm_type="playready"
            )
            
            if isinstance(license_res, bytes):
                license_res = license_res.decode('utf-8', errors='ignore')
                
            try:
                cdm.parse_license(sid, license_res)
            except Exception as parse_e:
                log.error(f"Failed to parse PlayReady license. Response preview: {license_res[:500]}")
                raise parse_e
            
            keys_list = cdm.get_keys(sid)
            result = {}
            for k in keys_list:
                kid = self._norm(k.get('kid'))
                key = k.get('key')
                if kid and key and kid != "00" * 16:
                    result[kid] = key.lower()

            self._license_cache[pssh_key] = result
            return result
            
        except Exception as e:
            raise ValueError(f"PlayReady license request failed: {e}")
        finally:
            cdm.close(sid)
                        
    def _match(self, track: Any, keys: Dict[str, str], service_name: str) -> Optional[str]:
        target_kid = self._norm(track.kid) if track.kid else None
        
        filtered_keys = {k: v for k, v in keys.items() if k not in ("0" * 32, "b770d5b4bb6b594daf985845aae9aa5f")}
        if not filtered_keys:
            filtered_keys = keys
            
        if not filtered_keys:
            return None

        for kid, key in filtered_keys.items():
            log.debug(f" + {kid}:{key}")

        if target_kid and target_kid in filtered_keys:
            return filtered_keys[target_kid]

        if service_name == "YouTubeMovies" and isinstance(track, VideoTrack) and filtered_keys:
            real_kid = next(iter(filtered_keys))
            log.info(f" + YouTube mapping: virtual {track.kid} -> real {real_kid}")
            track.kid = real_kid
            return filtered_keys[real_kid]

        if not target_kid:
            log.warning(f" - Track has no KID, using fallback key")
        else:
            log.warning(f" - No exact KID match for {track.kid}")
            log.warning(f" - Available: {list(filtered_keys.keys())}")

        if filtered_keys:
            fallback_kid = next(iter(filtered_keys))
            log.info(f" + Using fallback key from KID: {fallback_kid[:8]}...")
            if not track.kid:
                track.kid = fallback_kid
            return filtered_keys[fallback_kid]

        log.warning(f" - No exact KID match for {track.kid}")
        log.warning(f" - Available: {list(filtered_keys.keys())}")

        if filtered_keys:
            fallback_kid = next(iter(filtered_keys))
            log.info(f" + Using fallback key from KID: {fallback_kid[:8]}...")
            return filtered_keys[fallback_kid]
            
        return None

    def _sync_vault(self, kid: str, key: str, title_id: str, service_name: str, source_vault: Any) -> None:
        for v in self.vaults.vaults:
            if v is source_vault:
                continue
            try:
                res = v.insert_key(self.vaults.service, kid, key, title_id, commit=True)
                if res == InsertResult.SUCCESS:
                    log.debug(f" + Cached to {v.name} vault")
            except Exception:
                pass

    def _cache_all(self, keys: Dict[str, str], service_name: str, title_id: str) -> None:
        for v in self.vaults.vaults:
            try:
                added, existed = 0, 0
                for kid, key in keys.items():
                    res = v.insert_key(self.vaults.service, kid, key, title_id, commit=False)
                    if res == InsertResult.SUCCESS:
                        added += 1
                    elif res == InsertResult.ALREADY_EXISTS:
                        existed += 1
                v.commit()
                if added > 0:
                    log.debug(f" + Cached {added}/{len(keys)} keys to {v.name}")
                if existed > 0 and added == 0:
                    log.debug(f" + {existed}/{len(keys)} keys already existed in {v.name}")
            except Exception:
                pass

    @staticmethod
    def _norm(kid: Any) -> str:
        if hasattr(kid, 'hex'):
            return kid.hex.lower()
        if isinstance(kid, UUID):
            return kid.hex.lower()
        return str(kid).replace("-", "").replace("_", "").lower()