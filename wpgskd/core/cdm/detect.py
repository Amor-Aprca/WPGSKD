from pathlib import Path
import logging

log = logging.getLogger("CDMDetect")

def detect_cdm_type(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            header = f.read(3)
        
        if header == b"WVD":
            return "widevine"
        elif header == b"PRD":
            return "playready"
        else:
            raise ValueError(f"Unknown CDM file header: {header}")
    except Exception as e:
        log.error(f"Failed to detect CDM type for {path}: {e}")
        raise