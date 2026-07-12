from abc import ABC, abstractmethod
from typing import List, Optional, Union
from uuid import UUID

class BaseCdm(ABC):
    
    @property
    @abstractmethod
    def security_level(self) -> int:
        pass

    @property
    @abstractmethod
    def system_id(self) -> int:
        pass

    @property
    @abstractmethod
    def cdm_type(self) -> str:
        pass

    @abstractmethod
    def open(self) -> bytes:
        pass

    @abstractmethod
    def close(self, session_id: bytes) -> None:
        pass

    @abstractmethod
    def get_license_challenge(self, session_id: bytes, pssh_data: Union[str, bytes], privacy_mode: bool = True) -> bytes:
        pass

    @abstractmethod
    def parse_license(self, session_id: bytes, license_message: Union[str, bytes]) -> None:
        pass

    @abstractmethod
    def get_keys(self, session_id: bytes, key_type: Optional[str] = None) -> List[dict]:
        pass