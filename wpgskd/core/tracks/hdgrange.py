from enum import Enum
from typing import Any

class DynamicRange(Enum):
    SDR = "SDR"
    HDR10 = "HDR10"
    HDR10PLUS = "HDR10+"
    DV = "DV"
    HLG = "HLG"

def detect_dynamic_range(track: Any) -> DynamicRange:
    if getattr(track, 'dv', False):
        if getattr(track, 'hdr10', False):
            if getattr(track, 'dvhdr', False):
                return DynamicRange.HDR10
            return DynamicRange.DV
        return DynamicRange.DV
    if getattr(track, 'hdr10', False):
        return DynamicRange.HDR10
    if getattr(track, 'hlg', False):
        return DynamicRange.HLG
    return DynamicRange.SDR