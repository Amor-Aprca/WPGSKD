import logging
from typing import List, Any
from wpgskd.core.tracks.title import Title, Titles
from wpgskd.core.utilities import humanize_size, format_duration

log = logging.getLogger("Console")

class ConsoleUI:

    @staticmethod
    def print_titles(titles: Titles):
        if not titles:
            return

        is_tv = any(x.type == Title.Types.TV for x in titles)
        
        if is_tv:
            seasons = {}
            for t in titles:
                s = getattr(t, 'season', 0)
                seasons.setdefault(s, []).append(t)
                
            breakdown = ", ".join(f"S{s}({len(seasons[s])})" for s in sorted(seasons.keys()))
            log.info(f"{len(seasons)} seasons, {breakdown}")
        else:
            label = f"{len(titles)} Movie{['s', ''][len(titles) == 1]}"
            log.info(label)
            for m in titles:
                name = getattr(m, 'name', str(m))
                year = getattr(m, 'year', None)
                log.info(f"  {name} ({year or '?'})")
                
    @staticmethod
    def print_tracks(tracks: Any, title: Title = None):
        if not tracks:
            return

        for v in tracks.videos:
            codec = v.get_codec_display()
            
            range_str = "SDR"
            if getattr(v, 'dvhdr', False): range_str = "DV+HDR"
            elif getattr(v, 'dv', False): range_str = "DV"
            elif getattr(v, 'hdr10', False): range_str = "HDR10"
            elif getattr(v, 'hlg', False): range_str = "HLG"
            
            res_str = f"{v.width}x{v.height}"
            bitrate_str = f"{v.bitrate // 1000 if v.bitrate else '?'} kb/s"
            fps_str = f"{v.fps:.3f} FPS" if v.fps else "N/A"
            
            dur_sec = v.duration_seconds()
            size_bytes = v.size if v.size else v.computed_size_bytes()
            size_str = humanize_size(size_bytes) if size_bytes else "N/A"
            dur_str = format_duration(dur_sec) if dur_sec else "N/A"
                    
            enc_str = "Encrypted" if v.encrypted else "Unencrypted"
            
            log.info(f"├─ VID | {codec} | {range_str} | {res_str} | {bitrate_str} | {fps_str} | {size_str} | {dur_str} | {enc_str}")

        for a in tracks.audios:
            codec = a.get_codec_display()
            ch_str = a.channels or "?"
            bitrate_str = f"{a.bitrate // 1000 if a.bitrate else '?'} kb/s"
            lang_str = str(a.language)
            
            desc_str = " (Descriptive)" if a.descriptive else ""
            orig_str = " [Original]" if a.is_original_lang else ""
            
            dur_sec = a.duration_seconds()
            size_bytes = a.size if a.size else a.computed_size_bytes()
            size_str = humanize_size(size_bytes) if size_bytes else "N/A"
            dur_str = format_duration(dur_sec) if dur_sec else "N/A"
                    
            enc_str = "Encrypted" if a.encrypted else "Unencrypted"
            
            log.info(f"├─ AUD | {codec} | {ch_str} | {bitrate_str} | {lang_str}{orig_str}{desc_str} | {size_str} | {dur_str} | {enc_str}")

        for t in tracks.subtitles:
            codec = t.codec or "vtt"
            
            flags = []
            if t.is_original_lang: flags.append("orig")
            if t.forced: flags.append("Forced")
            if t.sdh: flags.append("SDH")
            if t.cc: flags.append("CC")
            flag_str = " ".join(flags)
            
            lang_str = str(t.language)
            
            parts = ["├─ SUB", codec, lang_str]
            if flag_str:
                parts.append(flag_str)
            log.info(" | ".join(parts))