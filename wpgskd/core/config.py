import logging
from pathlib import Path
from typing import Any, Optional, List
from dataclasses import dataclass, field

log = logging.getLogger("CoreConfig")

@dataclass
class CoreConfig:
    cdm_name: str = "default"
    decrypter: str = "packager"
    profile: str = "default"
    
    quality: Optional[Any] = None
    vcodec: str = "H264"
    acodec: Optional[str] = None
    vbitrate: Optional[int] = None
    abitrate: Optional[int] = None
    atmos: bool = False
    channels: Optional[str] = None
    range_: str = "SDR"
    wanted: Optional[List[str]] = None
    alang: List[str] = field(default_factory=lambda: ["orig"])
    slang: List[str] = field(default_factory=lambda: ["all"])
    
    audio_only: bool = False
    subs_only: bool = False
    chapters_only: bool = False
    no_subs: bool = False
    no_audio: bool = False
    no_video: bool = False
    no_chapters: bool = False
    audio_description: bool = False
    no_mux: bool = False
    mux: bool = False
    worst: bool = False
    sync_vat: bool = False
    no_sync_subs: bool = False
    
    use_cache: bool = True
    use_cdm: bool = True
    export: bool = False
    keys_only: bool = False
    
    temp_dir: Path = None
    out_dir: Path = None
    
    def apply_overrides(self, **kwargs):
        for key, value in kwargs.items():
            if value is not None and hasattr(self, key):
                setattr(self, key, value)