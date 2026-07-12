import logging
import os
import re 
from enum import Enum
from typing import Optional, List, Any, Iterator
from langcodes import Language

from wpgskd.utils import is_close_match, get_closest_match

log = logging.getLogger("Tracks")

class Track:
    class Descriptor(Enum):
        URL = 1
        M3U = 2
        MPD = 3
        ISM = 4
        DASH = 5
        HLS = 6

    def __init__(self, id_: str, source: str, url: Any, codec: str, language: Any = None, 
                 descriptor: Descriptor = Descriptor.URL, encrypted: bool = False, 
                 pssh: Any = None, pr_pssh: Any = None, kid: str = None, key: str = None, 
                 needs_proxy: bool = False, needs_repack: bool = False, 
                 encryption_scheme: Any = None, **kwargs):
        
        self.id = id_
        self.source = source
        self.url = url
        self.codec = codec
        self.language = Language.get(language or "und")
        self.descriptor = descriptor
        self.encrypted = encrypted
        self.encryption_scheme = encryption_scheme
        self.pssh = pssh
        self.pr_pssh = pr_pssh
        self.kid = kid
        self.key = key
        self.needs_proxy = needs_proxy
        self.needs_repack = needs_repack
        self.duration = kwargs.get("duration")
        self.size = kwargs.get("size")
        
        self.is_original_lang = False
        self._location: Optional[str] = None
        self.extra = kwargs.get("extra", {})

    def __repr__(self):
        return f"{self.__class__.__name__}(id={self.id}, lang={self.language}, codec={self.codec})"

    def __eq__(self, other):
        return isinstance(other, Track) and self.id == other.id

    def get_track_name(self) -> Optional[str]:
        if self.language is None:
            return None
        return None 

    def locate(self) -> Optional[str]:
        return self._location

    def swap(self, target_path: str) -> bool:
        if not os.path.exists(target_path) or not self._location:
            return False
        try:
            os.unlink(self._location)
            os.rename(target_path, self._location)
            return True
        except Exception:
            return False

    def delete(self):
        if self._location and os.path.exists(self._location):
            try:
                os.unlink(self._location)
            except Exception:
                pass
        self._location = None

    def get_pssh(self, session=None) -> bool:
        if self.descriptor == self.Descriptor.M3U and not getattr(self, '_sub_m3u8_parsed', False):
            self._sub_m3u8_parsed = True
            from wpgskd.core.manifests.m3u8 import parse_media_playlist
            
            data = parse_media_playlist(self.url, session)
            
            wv_pssh = data.get("pssh")
            pr_pssh = data.get("pr_pssh")
            kid = data.get("kid")
            
            if (not wv_pssh and not pr_pssh) and data.get("init_url"):
                try:
                    from wpgskd.core.manifests.map_init import extract_pssh_and_kid
                    if not session:
                        session = requests.Session()
                    resp = session.get(data["init_url"], stream=True)
                    chunk = next(resp.iter_content(20000), b"")
                    pssh_list, kid_hex = extract_pssh_and_kid(chunk)
                    if pssh_list:
                        wv_pssh = pssh_list[0]
                    if kid_hex:
                        kid = kid_hex
                except Exception:
                    pass

            if wv_pssh:
                self.pssh = wv_pssh
            if pr_pssh:
                self.pr_pssh = pr_pssh
            if kid and not self.kid:
                self.kid = kid
                
            if not wv_pssh and not pr_pssh and not data.get("aes_key_uri"):
                self.encrypted = False
                self.encryption_scheme = None
                return False
                
            if not self.pssh and isinstance(self.extra, dict) and self.extra.get("master_pssh"):
                self.pssh = self.extra["master_pssh"]
            if not self.pr_pssh and isinstance(self.extra, dict) and self.extra.get("master_pr_pssh"):
                self.pr_pssh = self.extra["master_pr_pssh"]
                
        return bool(self.pssh or self.pr_pssh)
        
    def get_kid(self, session=None) -> bool:
        if self.kid:
            return True
        return bool(self.kid)

    @staticmethod
    def pt_to_sec(d):
        if isinstance(d, (int, float)):
            return float(d)
        if not d:
            return None
        if d[0:2] == "P0":
            d = d.replace("P0Y0M0DT", "PT")
        if d[0:2] != "PT":
            raise ValueError("Input data is not a valid time string.")
        d = d[2:].upper()
        m = re.findall(r"([\d.]+.)", d)
        return sum(
            float(x[0:-1]) * {"H": 60 * 60, "M": 60, "S": 1}[x[-1].upper()]
            for x in m
        )

    def duration_seconds(self):
        cand = getattr(self, "duration", None)
        if cand is None:
            return None
        if isinstance(cand, (int, float)):
            return float(cand)
        try:
            return float(cand)
        except Exception:
            pass
        try:
            return self.pt_to_sec(str(cand))
        except Exception:
            return None

    def computed_size_bytes(self):
        try:
            bitrate = getattr(self, 'bitrate', None)
            if not bitrate:
                return None
            dur = self.duration_seconds()
            if not dur or dur <= 0:
                return None
            return int((float(bitrate) * float(dur)) / 8.0)
        except Exception:
            return None

    @staticmethod
    def format_hms(seconds):
        if seconds is None:
            return None
        try:
            s = int(round(float(seconds)))
        except Exception:
            return None
        h, rem = divmod(s, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02}h{m:02}m{s:02}s"

    @staticmethod
    def format_size_compact(num_bytes):
        try:
            size = float(num_bytes)
        except Exception:
            return ""
        units = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size >= 1024 and i < len(units) - 1:
            size /= 1024.0
            i += 1
        return f"{size:.2f} {units[i]}"

class TextTrack(Track):
    def __init__(self, *args, cc: bool = False, sdh: bool = False, forced: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc = cc
        self.sdh = sdh
        self.forced = forced

    def get_track_name(self) -> Optional[str]:
        name = super().get_track_name() or ""
        flag = "CC" if self.cc else "SDH" if self.sdh else "Forced" if self.forced else ""
        if flag:
            name += f" ({flag})" if name else flag
        return name or None

    def convert_to_srt(self, strip_sdh: bool = True) -> Optional[str]:
        from wpgskd.core.tracks.subtitles import SubtitleProcessor
        if not self._location:
            log.warning("Cannot convert subtitle, track not downloaded yet.")
            return None
            
        if self.sdh and strip_sdh is None:
            strip_sdh = True
            
        new_path = SubtitleProcessor.convert_subtitle_to_srt(self._location, strip_sdh)
        if new_path and new_path != self._location:
            self._location = new_path
            self.codec = "srt"
        return self._location


class Tracks:
    def __init__(self, *tracks: Track):
        self.videos: List[Any] = []  # VideoTrack
        self.audios: List[Any] = []  # AudioTrack
        self.subtitles: List[TextTrack] = []
        self.chapters: List[Any] = []

        if tracks:
            self.add(list(tracks))

    def __iter__(self) -> Iterator[Track]:
        return iter(self.videos + self.audios + self.subtitles)

    def add(self, tracks: Any, warn_only: bool = True):
        if tracks is None:
            return
            
        if isinstance(tracks, Tracks):
            tracks = list(tracks) + tracks.chapters
        elif isinstance(tracks, Track):
            tracks = [tracks]
            
        existing_ids = {t.id for t in self}
        
        for track in tracks:
            if track.id in existing_ids:
                if not warn_only:
                    raise ValueError(f"Duplicate Track ID: {track.id}")
                continue
            
            existing_ids.add(track.id)
            
            cls_name = track.__class__.__name__
            if cls_name == "VideoTrack":
                self.videos.append(track)
            elif cls_name == "AudioTrack":
                self.audios.append(track)
            elif cls_name == "TextTrack":
                self.subtitles.append(track)
            elif cls_name == "MenuTrack":
                self.chapters.append(track)

    def sort_videos(self, by_language: Optional[List[str]] = None):
        if not self.videos: return
        def range_priority(x):
            if getattr(x, 'dv', False): return 4
            if getattr(x, 'hdr10', False) or getattr(x, 'dvhdr', False): return 3
            if getattr(x, 'hlg', False): return 1
            return 2 # SDR
        self.videos.sort(key=lambda x: (range_priority(x), float(x.bitrate or 0.0)), reverse=True)

    def sort_audios(self, by_language: Optional[List[str]] = None):
        if not self.audios: return
        self.audios.sort(key=lambda x: float(x.bitrate or 0.0), reverse=True)
        self.audios.sort(key=lambda x: "" if x.descriptive else str(x.language))

        if by_language:
            for lang in reversed(by_language):
                if str(lang) == "all":
                    lang = next((x.language for x in self.audios if x.is_original_lang), "")
                if not lang: continue
                self.audios.sort(key=lambda x: "" if is_close_match(lang, [x.language]) else str(x.language))
                
    def sort_subtitles(self, by_language: Optional[List[str]] = None):
        if not self.subtitles: return
        self.subtitles.sort(key=lambda x: str(x.language) + ("-cc" if x.cc else "") + ("-sdh" if x.sdh else ""))
        self.subtitles.sort(key=lambda x: not x.forced)
        if by_language:
            for lang in reversed(by_language):
                if str(lang) == "all":
                    lang = next((x.language for x in self.subtitles if x.is_original_lang), "")
                if not lang: continue
                self.subtitles.sort(key=lambda x: "" if is_close_match(lang, [x.language]) else str(x.language))

    def sort_chapters(self):
        if not self.chapters: return
        self.chapters.sort(key=lambda x: x.number)

    def select_videos(self, by_quality=None, by_vbitrate=None, by_range=None, one_only=True, by_worst=False, by_codec=None):
        videos = self.videos
        if by_quality:
            q_videos = [x for x in videos if x.height == by_quality]
            if not q_videos: q_videos = [x for x in videos if int(x.width * (9/16)) == by_quality]
            if not q_videos and by_quality == "SD": q_videos = [x for x in videos if (x.width, x.height) < (1024, 576)]
            if not q_videos and by_quality == "HD720": q_videos = [x for x in videos if (x.width, x.height) < (1482, 620)]
            if not q_videos: raise ValueError(f"No {by_quality}p video track.")
            videos = q_videos
            
        if by_vbitrate:
            videos = [x for x in videos if int(x.bitrate or 0) <= int(by_vbitrate * 1001)]
        if by_worst:
            videos.sort(key=lambda x: float(x.bitrate or 0.0))
        if by_codec:
            target = by_codec.upper()
            c_videos = []
            for x in videos:
                raw = (x.codec or "").lower()
                if any(k in raw for k in ["hev", "hvc", "dvh"]):
                    std = "H265"
                elif "avc" in raw:
                    std = "H264"
                elif "av01" in raw or "dav1" in raw:
                    std = "AV1"
                else:
                    std = raw.upper()
                if std == target: c_videos.append(x)
            if not c_videos: raise ValueError(f"No {by_codec} video tracks.")
            videos = c_videos
        if by_range:
            target_range = by_range.upper()
            if target_range == "DV+HDR":
                videos = [x for x in videos if getattr(x, 'dv', False) and getattr(x, 'hdr10', False)]
            elif target_range == "DV":
                videos = [x for x in videos if getattr(x, 'dv', False)]
            elif target_range == "HDR10":
                videos = [x for x in videos if getattr(x, 'hdr10', False) and not getattr(x, 'dv', False)]
            elif target_range == "HLG":
                videos = [x for x in videos if getattr(x, 'hlg', False)]
            elif target_range == "SDR":
                videos = [x for x in videos if not x.hdr10 and not x.dv and not x.hlg and not getattr(x, 'dvhdr', False)]
            else:
                raise ValueError(f"Unsupported range: {by_range}")
                
            if not videos: raise ValueError(f"No {by_range} video track.")
            
        if one_only and videos:
            self.videos = [videos[0]]
        else:
            self.videos = videos

    def select_videos_multi(self, ranges: list[str], by_quality=None, by_vbitrate=None, by_worst=False):
        videos = self.videos
        
        for r in ranges:
            r_upper = r.upper()
            if r_upper == "DV":
                videos = [x for x in videos if getattr(x, 'dv', False)]
            elif r_upper == "HDR10":
                videos = [x for x in videos if getattr(x, 'hdr10', False)]
            elif r_upper == "HLG":
                videos = [x for x in videos if getattr(x, 'hlg', False)]
            elif r_upper == "DVHDR": 
                videos = [x for x in videos if getattr(x, 'dvhdr', False)]

        if not videos:
            raise ValueError(f"No video tracks matching all ranges: {ranges}")

        if by_quality:
            q_videos = [x for x in videos if x.height == by_quality]
            if not q_videos: q_videos = [x for x in videos if int(x.width * (9/16)) == by_quality]
            if not q_videos and by_quality == "SD": q_videos = [x for x in videos if (x.width, x.height) < (1024, 576)]
            if not q_videos and by_quality == "HD720": q_videos = [x for x in videos if (x.width, x.height) < (1482, 620)]
            if not q_videos: raise ValueError(f"No {by_quality}p video track in {ranges}.")
            videos = q_videos

        if by_vbitrate:
            videos = [x for x in videos if int(x.bitrate or 0) <= int(by_vbitrate * 1001)]

        if by_worst:
            videos.sort(key=lambda x: float(x.bitrate or 0.0))
        else:
            videos.sort(key=lambda x: float(x.bitrate or 0.0), reverse=True)

        if videos:
            self.videos = [videos[0]]
        else:
            self.videos = videos

    def select_audios(self, by_language=None, by_bitrate=None, with_atmos=False, with_descriptive=True, by_channels=None, by_codec=None):
        audios = self.audios
        if not with_descriptive:
            audios = [x for x in audios if not x.descriptive]
        if by_codec:
            target = by_codec.upper()
            c_audios = []
            for x in audios:
                raw = (x.codec or "").lower()
                std = "EC3" if any(k in raw for k in ["ec-3", "eac3"]) else "AC3" if "ac-3" in raw else "AAC" if "aac" in raw else raw.upper()
                if std == target: c_audios.append(x)
            if c_audios: audios = c_audios
        if with_atmos:
            atmos = [x for x in audios if x.atmos]
            if atmos: audios = atmos
        if by_channels:
            ch_audios = [x for x in audios if x.channels == by_channels]
            if ch_audios: audios = ch_audios
        if by_bitrate:
            audios = [x for x in audios if int(x.bitrate or 0) <= int(by_bitrate * 1000)]
        if by_language:
            filtered = []
            for lang in by_language:
                if str(lang) == "all":
                    filtered.extend(audios)
                elif str(lang) == "orig":
                    orig_langs = [str(x.language).split("-")[0] for x in audios if x.is_original_lang]
                    if not orig_langs:
                        filtered.extend(audios)
                    else:
                        for x in audios:
                            if str(x.language).split("-")[0] in orig_langs:
                                filtered.append(x)
                else:
                    base_lang = str(lang).split("-")[0]
                    for x in audios:
                        if str(x.language).split("-")[0] == base_lang:
                            filtered.append(x)
            
            seen_ids = set()
            deduped = []
            for x in filtered:
                if x.id not in seen_ids:
                    seen_ids.add(x.id)
                    deduped.append(x)
            
            best_per_lang = {}
            for x in deduped:
                bitrate = float(x.bitrate or 0.0)
                lang_key = str(x.language).split("-")[0]
                if lang_key not in best_per_lang or bitrate > best_per_lang[lang_key][1]:
                    best_per_lang[lang_key] = (x, bitrate)
                    
            audios = [v[0] for v in best_per_lang.values()]
            
        self.audios = audios
                      
    def select_subtitles(self, by_language=None, with_forced=None):
        subs = self.subtitles
        if by_language:
            filtered = []
            for lang in by_language:
                if str(lang) == "all":
                    filtered.extend(subs)
                elif str(lang) == "orig":
                    filtered.extend([x for x in subs if x.is_original_lang])
                else:
                    match = get_closest_match(lang, [x.language for x in subs])
                    if match:
                        filtered.extend([x for x in subs if x.language == match])
            
            seen_ids = set()
            deduped = []
            for x in filtered:
                if x.id not in seen_ids:
                    seen_ids.add(x.id)
                    deduped.append(x)
            subs = deduped
            
        if with_forced is False:
            subs = [x for x in subs if not x.forced]
            
        self.subtitles = subs           
    
    @staticmethod
    def from_mpd(*args, **kwargs):
        from wpgskd.core.manifests.dash import parse as parse_mpd
        return parse_mpd(*args, **kwargs)

    @staticmethod
    def from_m3u8(*args, **kwargs):
        from wpgskd.core.manifests.hls import parse as parse_hls
        return parse_hls(*args, **kwargs)

    @staticmethod
    def from_ism(*args, **kwargs):
        from wpgskd.core.manifests.ism import parse as parse_ism
        return parse_ism(*args, **kwargs)        