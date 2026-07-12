import math
from typing import Optional
from wpgskd.core.tracks.tracks import Track

VIDEO_CODEC_MAP = {
    "AVC": "H.264",
    "HEVC": "H.265",
    "V_VC1": "VC-1",
    "V_MPEGH/ISO/HEVC": "H.265",
    "V_MPEG4/ISO/AVC": "H.264",
    "AV1": "AV1",
    "VP8": "VP8",
    "VP9": "VP9",
}

class VideoTrack(Track):
    def __init__(self, *args, bitrate: int, width: int, height: int, fps: Optional[float] = None,
                 hdr10: bool = False, dvhdr: bool = False, hlg: bool = False, dv: bool = False, 
                 needs_ccextractor: bool = False, mpd_representation_id: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bitrate = int(math.ceil(float(bitrate))) if bitrate else None
        self.width = int(width)
        self.height = int(height)
        self.fps = float(fps) if fps else None
        
        self.hdr10 = bool(hdr10)
        self.dvhdr = bool(dvhdr)
        self.hlg = bool(hlg)
        self.dv = bool(dv)
        
        self.needs_ccextractor = needs_ccextractor
        self.mpd_representation_id = mpd_representation_id

    def get_codec_display(self) -> str:
        if not self.codec:
            return "Unknown"
            
        codec_str = str(self.codec)
        codec_lower = codec_str.lower()
        
        if codec_str in VIDEO_CODEC_MAP:
            return VIDEO_CODEC_MAP[codec_str]
            
        if "avc" in codec_lower or "h264" in codec_lower:
            return "H.264"
        elif "hev" in codec_lower or "hvc" in codec_lower or "h265" in codec_lower or "dvh" in codec_lower:
            return "H.265"
        elif "av1" in codec_lower:
            return "AV1"
        elif "vp09" in codec_lower or "vp9" in codec_lower:
            return "VP9"
        elif "vp08" in codec_lower or "vp8" in codec_lower:
            return "VP8"
        elif "vc-1" in codec_lower or "vc1" in codec_lower:
            return "VC-1"           
        return codec_str

    def __str__(self):
        codec = self.get_codec_display()
        range_str = "DV+HDR" if self.dvhdr else "HDR10" if self.hdr10 else "HLG" if self.hlg else "DV" if self.dv else "SDR"
        fps_str = f"{self.fps:.3f} FPS" if self.fps else "Unknown FPS"
        bitrate_str = f"{self.bitrate // 1000 if self.bitrate else '?'} kb/s"
        enc_str = "Encrypted" if self.encrypted else "Unencrypted"
        
        dur_sec = self.duration_seconds()
        size_bytes = self.size if self.size else self.computed_size_bytes()
        size_str = self.format_size_compact(size_bytes) if size_bytes else None
        dur_str = self.format_hms(dur_sec) if dur_sec else None

        return " | ".join([x for x in [
            "├─ VID",
            codec,
            range_str,
            f"{self.width}x{self.height}",
            bitrate_str,
            fps_str,
            enc_str,
            size_str,
            dur_str
        ] if x])