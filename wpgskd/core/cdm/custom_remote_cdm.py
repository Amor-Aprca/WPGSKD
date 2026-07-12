import logging
import base64
import requests
from typing import List, Optional, Union, Dict, Any
from wpgskd.core.cdm.base import BaseCdm

log = logging.getLogger("RemoteCDM")

class RemoteCdmAdapter(BaseCdm):
    def __init__(self, api_config: Dict[str, Any]):
        self.host = api_config["host"]
        self.key = api_config["key"]
        self.device_name = api_config["device"]
        self._security_level = int(api_config.get("security_level", 3))
        self._system_id = int(api_config.get("system_id", 0))
        self._cdm_type = api_config.get("type", "widevine").lower()
        self.session = requests.Session()
        self.session.headers.update({"X-Secret-Key": self.key})

    @property
    def security_level(self): return self._security_level
    @property
    def system_id(self): return self._system_id
    @property
    def cdm_type(self): return self._cdm_type

    def open(self) -> bytes:
        r = self.session.get(f"{self.host}/{self.device_name}/open").json()
        if r['status'] != 200: raise ValueError(r['message'])
        return bytes.fromhex(r["data"]["session_id"])

    def close(self, session_id: bytes) -> None:
        self.session.get(f"{self.host}/{self.device_name}/close/{session_id.hex()}")

    def get_license_challenge(self, session_id: bytes, pssh_data: Union[str, bytes], privacy_mode: bool = True) -> bytes:
        if isinstance(pssh_data, bytes):
            pssh_data = base64.b64encode(pssh_data).decode()
        
        payload = {
            "session_id": session_id.hex(),
            "init_data": pssh_data,
            "privacy_mode": privacy_mode
        }
        r = self.session.post(f"{self.host}/{self.device_name}/get_license_challenge", json=payload).json()
        if r['status'] != 200: raise ValueError(r['message'])
        return base64.b64decode(r["data"]["challenge_b64"])

    def parse_license(self, session_id: bytes, license_message: Union[str, bytes]) -> None:
        if isinstance(license_message, bytes):
            license_message = base64.b64encode(license_message).decode()
            
        payload = {
            "session_id": session_id.hex(),
            "license_message": license_message
        }
        r = self.session.post(f"{self.host}/{self.device_name}/parse_license", json=payload).json()
        if r['status'] != 200: raise ValueError(r['message'])

    def get_keys(self, session_id: bytes, key_type: Optional[str] = None) -> List[dict]:
        payload = {"session_id": session_id.hex()}
        r = self.session.post(f"{self.host}/{self.device_name}/get_keys", json=payload).json()
        if r['status'] != 200: raise ValueError(r['message'])
        
        keys = r["data"]["keys"]
        if key_type:
            return [k for k in keys if k.get("type") == key_type]
        return keys