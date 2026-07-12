import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from Crypto.Random import get_random_bytes

from wpgskd.core.cdm.base import BaseCdm
from wpgskd.core.cdm.detect import detect_cdm_type

log = logging.getLogger("CDMLoader")

class CdmProvider:
    def __init__(self, cdm_name: str, device_dir: Path, cdm_api_config: Optional[Dict[str, Any]] = None):
        self.cdm_name = cdm_name
        self.device_dir = device_dir
        self.cdm_api_config = cdm_api_config or {}
        self._cdm_instance: Optional[BaseCdm] = None

    @property
    def cdm_instance(self) -> BaseCdm:
        if self._cdm_instance is None:
            self._cdm_instance = self._load_cdm()
        return self._cdm_instance

    @property
    def is_playready(self) -> bool:
        return self.cdm_instance.cdm_type == "playready"
        
    @property
    def is_widevine(self) -> bool:
        return self.cdm_instance.cdm_type == "widevine"
        
    def _load_cdm(self) -> BaseCdm:
        local_path = self.device_dir / self.cdm_name
        if local_path.is_file():
            return self._load_local_cdm(local_path)

        for ext in ['.wvd', '.prd']:
            path_with_ext = self.device_dir / f"{self.cdm_name}{ext}"
            if path_with_ext.is_file():
                return self._load_local_cdm(path_with_ext)

        dev_dir = self.device_dir / self.cdm_name
        if dev_dir.is_dir():
            if (dev_dir / 'zgpriv.dat').is_file() and (dev_dir / 'bgroupcert.dat').is_file():
                prd_path = self._create_playready_device(dev_dir)
                if prd_path:
                    return self._load_local_cdm(prd_path)
            
            return self._load_local_dir(dev_dir)

        if self.cdm_name in self.cdm_api_config:
            return self._load_remote_cdm(self.cdm_api_config[self.cdm_name])

        raise ValueError(f"CDM '{self.cdm_name}' not found locally or in API config.")

    def _load_local_cdm(self, path: Path) -> BaseCdm:
        cdm_type = detect_cdm_type(path)
        
        if cdm_type == "widevine":
            try:
                from pywidevine.cdm import Cdm as PyWidevineCdm
                from pywidevine.device import Device as PyWidevineDevice
                device = PyWidevineDevice.load(path)
                return WidevineCdmAdapter(PyWidevineCdm.from_device(device))
            except ImportError:
                log.warning("pywidevine not installed, falling back to built-in legacy widevine.")
                from pywidevine.cdm import Cdm as LegacyWVCdm
                from pywidevine.device import LocalDevice as LegacyWVDevice
                device = LegacyWVDevice.load(path)
                return WidevineCdmAdapter(LegacyWVCdm(device))
            
        elif cdm_type == "playready":
            try:
                from pyplayready.cdm import Cdm as PyPlayReadyCdm
                from pyplayready.device import Device as PyPlayReadyDevice
                device = PyPlayReadyDevice.load(path)
                return PlayReadyCdmAdapter(PyPlayReadyCdm.from_device(device))
            except ImportError:
                log.warning("pyplayready not installed, falling back to built-in legacy playready.")
                from pyplayready.cdm import Cdm as LegacyPRCdm
                from pyplayready.device import Device as LegacyPRDevice
                device = LegacyPRDevice.load(path)
                return PlayReadyCdmAdapter(LegacyPRCdm.from_device(device))
        else:
            raise ValueError(f"Unsupported CDM file format: {path.suffix}")

    def _load_local_dir(self, path: Path) -> BaseCdm:
        if not path.is_dir():
            raise ValueError(f"CDM directory not found at: {path}")
            
        log.debug(f"Loading CDM from directory: {path}")
        from pywidevine.device import LocalDevice as LegacyWVDevice
        from pywidevine.cdm import Cdm as LegacyWVCdm
        device = LegacyWVDevice.from_dir(str(path))
        return WidevineCdmAdapter(LegacyWVCdm(device))

    def _create_playready_device(self, device_dir: Path) -> Optional[Path]:
        try:
            from pyplayready.crypto.ecc_key import ECCKey
            from pyplayready.system.bcert import CertificateChain, Certificate
            from pyplayready.device import Device as DevicePR
        except ImportError:
            log.error("Built-in pyplayready not available, cannot generate .prd from directory.")
            return None

        group_key_path = device_dir / 'zgpriv.dat'
        group_cert_path = device_dir / 'bgroupcert.dat'
        infofile = device_dir / 'PR.json'

        if infofile.is_file():
            try:
                with open(infofile, 'r') as f:
                    info = json.load(f)
                if "expiry" in info and datetime.fromisoformat(info["expiry"]) > datetime.now():
                    existing = device_dir / info["device"]
                    if existing.is_file():
                        log.info(f" + Loading existing generated PlayReady device: {info['device']}")
                        return existing
            except Exception:
                pass

        log.info(" + Generating new PlayReady Device (.prd) from directory...")
        try:
            enc_key = ECCKey.generate()
            sig_key = ECCKey.generate()

            gk_obj = ECCKey.load(group_key_path)
            chain = CertificateChain.load(group_cert_path)

            new_cert = Certificate.new_leaf_cert(
                cert_id=get_random_bytes(16),
                security_level=chain.get_security_level(),
                client_id=get_random_bytes(16),
                signing_key=sig_key,
                encryption_key=enc_key,
                group_key=gk_obj,
                parent=chain,
            )
            chain.prepend(new_cert)

            device = DevicePR(
                group_key=gk_obj.dumps(),
                encryption_key=enc_key.dumps(),
                signing_key=sig_key.dumps(),
                group_certificate=chain.dumps(),
            )

            expiry = (datetime.now() + timedelta(days=3650)).isoformat()
            raw = device.dumps()
            out_path = device_dir / f"{device.get_name()}_{raw[:4].hex()}.prd"

            if out_path.exists():
                log.error(f"Device file already exists: {out_path}")
                return None

            out_path.write_bytes(raw)

            with open(infofile, 'w') as f:
                json.dump({
                    "expiry": expiry,
                    "device": out_path.name,
                    "SecurityLevel": device.security_level,
                    "created": datetime.now().isoformat(),
                }, f)

            log.info(f" + Created PlayReady Device: {out_path.name}")
            return out_path

        except Exception as e:
            log.error(f"Failed to generate PlayReady device: {e}")
            return None

    def _load_remote_cdm(self, api_config: Dict[str, Any]) -> BaseCdm:
        from wpgskd.core.cdm.custom_remote_cdm import RemoteCdmAdapter
        log.info(f"Loading Remote CDM: {api_config.get('name')}")
        return RemoteCdmAdapter(api_config)

    def log_info(self):
        cdm = self.cdm_instance
        log.info(f" + CDM Type: {cdm.cdm_type.upper()}")
        log.info(f" + Security Level: L{cdm.security_level}")
        if cdm.system_id:
            log.info(f" + System ID: {cdm.system_id}")

class WidevineCdmAdapter(BaseCdm):
    def __init__(self, cdm_instance):
        self._cdm = cdm_instance

    @property
    def security_level(self): return self._cdm.security_level
    @property
    def system_id(self): return self._cdm.system_id
    @property
    def cdm_type(self): return "widevine"

    def open(self): return self._cdm.open()
    def close(self, session_id): self._cdm.close(session_id)
    
    def get_license_challenge(self, session_id, pssh_data, privacy_mode=True):
        try:
            from pywidevine.pssh import PSSH
            from wpgskd.vendor.pymp4.parser import Box as Pymp4Box
            if hasattr(pssh_data, 'type') and hasattr(pssh_data, 'init_data') and not isinstance(pssh_data, PSSH):
                pssh_bytes = Pymp4Box.build(pssh_data)
                pssh_data = PSSH(pssh_bytes)
        except Exception:
            pass
            
        if hasattr(self._cdm, 'get_license_challenge'):
            import inspect
            sig = inspect.signature(self._cdm.get_license_challenge)
            if 'service_name' in sig.parameters:
                return self._cdm.get_license_challenge(session_id, pssh_data, service_name="default")
            return self._cdm.get_license_challenge(session_id, pssh_data, privacy_mode=privacy_mode)

    def parse_license(self, session_id, license_message):
        self._cdm.parse_license(session_id, license_message)

    def get_keys(self, session_id, key_type="CONTENT"):
        keys = self._cdm.get_keys(session_id)
        result = []
        for k in keys:
            kid = k.kid.hex if hasattr(k.kid, 'hex') else str(k.kid).replace("-", "")
            key = k.key.hex() if isinstance(k.key, bytes) else str(k.key)
            result.append({"kid": kid, "key": key, "type": k.type})
        
        if key_type:
            return [k for k in result if k['type'] == key_type]
        return result

class PlayReadyCdmAdapter(BaseCdm):
    def __init__(self, cdm_instance):
        self._cdm = cdm_instance

    @property
    def security_level(self): return self._cdm.security_level
    @property
    def system_id(self): return 1 
    @property
    def cdm_type(self): return "playready"

    def open(self): return self._cdm.open()
    def close(self, session_id): self._cdm.close(session_id)
    
    def get_license_challenge(self, session_id, pssh_data, privacy_mode=True):
        return self._cdm.get_license_challenge(session_id, pssh_data)

    def parse_license(self, session_id, license_message):
        self._cdm.parse_license(session_id, license_message)

    def get_keys(self, session_id, key_type=None):
        keys = self._cdm.get_keys(session_id)
        result = []
        for k in keys:
            kid = k.key_id.hex if hasattr(k.key_id, 'hex') else str(k.key_id).replace("-", "")
            key = k.key.hex() if isinstance(k.key, bytes) else str(k.key)
            result.append({"kid": kid, "key": key, "type": "CONTENT"})
        return result