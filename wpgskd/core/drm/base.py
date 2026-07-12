from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

class BaseDRM(ABC):
    
    def __init__(self, cdm_provider: Any, service: Any):
        self.cdm_provider = cdm_provider
        self.service = service

    @abstractmethod
    def get_keys(self, track: Any, title: Any, session: Any) -> Tuple[Optional[str], Dict[str, str]]:
        pass