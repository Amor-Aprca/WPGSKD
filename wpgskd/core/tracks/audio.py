import math
from typing import Optional
from wpgskd.core.tracks.tracks import Track

AUDIO_CODEC_MAP = {
    "E-AC-3": "DD+",
    "E-AC-3 JOC": "DD+ Atmos",
    "AC-3": "DD",
    "AAC": "AAC",
    "AAC LC": "AAC",
    "FLAC": "FLAC",
    "Opus": "Opus",
    "DTS": "DTS",
    "DTS-HD": "DTS-HD",
    "DTS-HD MA": "DTS-HD.MA",
    "DTS XLL": "DTS-HD.MA",
    "MLP FBA": "TrueHD",
    "MLP FBA 16-ch": "TrueHD Atmos",
}

class AudioTrack(Track):
    def __init__(self, *args, bitrate: int, channels: Optional[str] = None,
                 descriptive: bool = False, atmos: bool = False, 
                 mpd_representation_id: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bitrate = int(math.ceil(float(bitrate))) if bitrate else None
        self.channels = self.parse_channels(channels) if channels else None
        self.descriptive = bool(descriptive)
        self.atmos = bool(atmos)
        self.mpd_representation_id = mpd_representation_id

    @staticmethod
    def parse_channels(channels: str) -> str:
        if channels in ["A000", "a000"]: return "2.0"
        if channels in ["F801", "f801"]: return "5.1"
        try:
            ch = str(float(channels))
            if ch == "6.0": return "5.1"
            return ch
        except ValueError:
            return str(channels)

    def get_codec_display(self) -> str:
        if not self.codec:
            return "Unknown"
            
        codec_str = str(self.codec)
        codec_lower = codec_str.lower()
        
        display_name = codec_str
        
        if codec_str in AUDIO_CODEC_MAP:
            display_name = AUDIO_CODEC_MAP[codec_str]
        elif "ec-3" in codec_lower or "eac3" in codec_lower:
            display_name = "DDP"
        elif "ac-3" in codec_lower or "ac3" in codec_lower:
            display_name = "DD"
        elif "mp4a" in codec_lower or "aac" in codec_lower:
            display_name = "AAC"
        elif "opus" in codec_lower:
            display_name = "Opus"
        elif "flac" in codec_lower:
            display_name = "FLAC"
        elif "dts" in codec_lower:
            display_name = "DTS"
            
        if self.atmos and "Atmos" not in display_name:
            display_name += " Atmos"
            
        return display_name

    def get_track_name(self) -> Optional[str]:
        track_name = super().get_track_name() or ""
        flag = "Descriptive" if self.descriptive else ""
        if flag:
            if track_name:
                flag = f" ({flag})"
            track_name += flag
        return track_name or None

    def __str__(self):
        dur_sec = self.duration_seconds()
        size_bytes = self.size if self.size else self.computed_size_bytes()
        size_str = self.format_size_compact(size_bytes) if size_bytes else None
        dur_str = self.format_hms(dur_sec) if dur_sec else None
        
        codec_display = self.get_codec_display()
        if self.atmos and "Atmos" not in codec_display:
            codec_display = f"{codec_display} Atmos"
            
        return " | ".join([x for x in [
            "├─ AUD",
            codec_display,
            f"{self.channels}" if self.channels else None,
            f"{self.bitrate // 1000 if self.bitrate else '?'} kb/s",
            f"{self.language}",
            " ".join([self.get_track_name() or "", "[Original]" if self.is_original_lang else ""]).strip(),
            size_str,
            dur_str
        ] if x])