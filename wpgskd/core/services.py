import re
from typing import List

class Services:
    ALIASES = {
        "amzn": "amazon",
        "atvp": "appletvplus",
        "dsnp": "disneyplus",
        "hmax": "hbomax",
        "pmtp": "paramountplus",
        "ytbe": "youtube"
    }

    @classmethod
    def get_tag(cls, service_name: str) -> str:
        if not service_name:
            return "unknown"
            
        tag = service_name.lower()
        return cls.ALIASES.get(tag, tag)

    @classmethod
    def get_tags(cls, service_names: List[str]) -> List[str]:
        return [cls.get_tag(name) for name in service_names]