import asyncio
import hashlib
import logging
import urllib.parse
from typing import Optional

import requests
from langcodes import Language
from langcodes.tag_parser import LanguageTagError

from wpgskd.config import directories
from wpgskd.core.tracks import AudioTrack, TextTrack, Track, Tracks, VideoTrack
from wpgskd.utils.io import aria2c
from wpgskd.utils.xml import load_xml

log = logging.getLogger("ISMParser")

def _probe_ism_fps(url, session, timescale=10000000):
    try:
        s = session or requests
        res = s.get(url, timeout=10)
        res.raise_for_status()
        data = res.content
        
        def find_box_pos(data, target, start=0):
            pos = start
            while pos < len(data) - 8:
                size = int.from_bytes(data[pos:pos+4], 'big')
                btype = data[pos+4:pos+8]
                if size == 0: break
                if btype == target:
                    return pos, size
                if size < 8: break
                pos += size
            return -1, 0
            
        moof_pos, moof_size = find_box_pos(data, b'moof')
        if moof_pos == -1: return None
        
        traf_pos, traf_size = find_box_pos(data, b'traf', moof_pos + 8)
        if traf_pos == -1: return None
        
        trun_pos, trun_size = find_box_pos(data, b'trun', traf_pos + 8)
        if trun_pos == -1: return None
        
        version = data[trun_pos + 8]
        flags = int.from_bytes(data[trun_pos + 9 : trun_pos + 12], 'big')
        sample_count = int.from_bytes(data[trun_pos + 12 : trun_pos + 16], 'big')
        
        offset = trun_pos + 16
        if flags & 0x000001:  # data_offset_present
            offset += 4
        if flags & 0x000004:  # first_sample_flags_present
            offset += 4
            
        if flags & 0x000100:  # sample_duration_present
            total_duration = 0
            for _ in range(sample_count):
                total_duration += int.from_bytes(data[offset : offset + 4], 'big')
                offset += 4
                if flags & 0x000200:  # sample_size_present
                    offset += 4
                if flags & 0x000400:  # sample_flags_present
                    offset += 4
                if flags & 0x000800:  # sample_composition_time_present
                    offset += 4 if version == 0 else 8
            if total_duration > 0:
                fps = (sample_count * timescale) / total_duration
                return round(fps, 3)
                
        tfhd_pos, tfhd_size = find_box_pos(data, b'tfhd', traf_pos + 8)
        if tfhd_pos != -1:
            tfhd_flags = int.from_bytes(data[tfhd_pos + 9 : tfhd_pos + 12], 'big')
            tfhd_offset = tfhd_pos + 16 
            
            if tfhd_flags & 0x000001:  
                tfhd_offset += 8
            if tfhd_flags & 0x000002: 
                tfhd_offset += 4
                
            if tfhd_flags & 0x000008: 
                default_dur = int.from_bytes(data[tfhd_offset : tfhd_offset + 4], 'big')
                if default_dur > 0:
                    return round(timescale / default_dur, 3)
                    
    except Exception as e:
        log.warning(f"Failed to probe ISM FPS via raw bytes: {e}")
    return None

def parse(url: str = None, data: str = None, source: str = None, session: requests.Session = None, downloader: str = None) -> Tracks:
    if not data:
        if downloader is None:
            r = (session or requests).get(url)
            url = r.url  
            data = r.content
        elif downloader == "aria2c":
            out = directories.temp / url.split("/")[-1]
            asyncio.run(aria2c((url, out)))
            data = out.read_bytes()
            out.unlink(missing_ok=True)
        else:
            raise ValueError(f"Unsupported downloader: {downloader}")

    root = load_xml(data)
    if root.tag != "SmoothStreamingMedia":
        raise ValueError("Non-ISM document provided to ISM parser")

    tracks = []
    base_url = url
    duration = int(root.attrib.get("Duration", 0))
    root_timescale = int(root.get("TimeScale", 10000000))
    duration_sec = duration / root_timescale if root_timescale else 0
    
    if session is None:
        session = requests.Session()

    for stream_index in root.findall("StreamIndex"):
        stream_fps = None
        fps_probed = False    
        for ql in stream_index.findall("QualityLevel"):
            content_type = stream_index.get("Type")
            if not content_type:
                raise ValueError("No content type value could be found")
                
            codec = ql.get("FourCC")
            if codec == "TTML":
                codec = "STPP"

            track_lang = None
            if lang := (stream_index.get("Language") or "").strip():
                try:
                    t = Language.get(lang.split("-")[0])
                    if t == Language.get("und") or not t.is_valid():
                        raise LanguageTagError()
                except LanguageTagError:
                    pass
                else:
                    track_lang = Language.get(lang)

            protections = root.xpath(".//ProtectionHeader")
            pr_protections = [
                x for x in protections
                if (x.get("SystemID") or "").lower() == "9a04f079-9840-4286-ab92-e65be0885f95"
            ]
            protections = pr_protections
            encrypted = bool(protections)
            pssh = None
            pr_pssh = None
            kid = None
            
            if pr_protections:
                import base64
                import re
                from uuid import UUID
                for protection in pr_protections:
                    pr_pssh_text = "".join(protection.itertext())
                    if pr_pssh_text:
                        pr_pssh = pr_pssh_text
                        try:
                            raw_bytes = base64.b64decode(pr_pssh_text)
                            clean_str = raw_bytes.replace(b'\x00', b'').decode('utf-8', errors='ignore')
                            kid_match = re.search(r'<KID>([a-zA-Z0-9+/=]+)</KID>', clean_str)
                            if kid_match:
                                kid_bytes = base64.b64decode(kid_match.group(1))
                                if len(kid_bytes) == 16:
                                    kid = UUID(bytes_le=kid_bytes).hex
                        except Exception:
                            pass
                        break

            track_url = []
            fragment_ctx = {
                "time": 0,
            }
            stream_fragments = stream_index.findall("c")
            for stream_fragment_index, stream_fragment in enumerate(stream_fragments):
                fragment_ctx["time"] = int(stream_fragment.get("t", fragment_ctx["time"]))
                fragment_repeat = int(stream_fragment.get("r", 1))
                fragment_ctx["duration"] = int(stream_fragment.get("d"))
                
                if not fragment_ctx["duration"]:
                    try:
                        next_fragment_time = int(stream_index[stream_fragment_index + 1].attrib["t"])
                    except IndexError:
                        next_fragment_time = duration
                    fragment_ctx["duration"] = (next_fragment_time - fragment_ctx["time"]) / fragment_repeat
                    
                for _ in range(fragment_repeat):
                    track_url.append(
                        urllib.parse.urljoin(
                            base_url, stream_index.get("Url").format_map({
                                "bitrate": ql.get("Bitrate"),
                                "start time": str(fragment_ctx["time"]),
                            }),
                        )
                    )
                    fragment_ctx["time"] += fragment_ctx["duration"]

            if content_type == "video" and not fps_probed and track_url:
                stream_name = stream_index.get("Name") or "video"
                log.info(f" + Probing FPS from first fragment for stream: {stream_name}")
                stream_fps = _probe_ism_fps(track_url[0], session, root_timescale)
                fps_probed = True
                if stream_fps:
                    log.info(f" + Detected FPS: {stream_fps}")
                else:
                    log.warning(" + Could not detect FPS from fragment.")

            track_id = hashlib.md5(
                f"{codec}-{track_lang}-{ql.get('Bitrate') or 0}-{ql.get('Index') or 0}".encode(),
            ).hexdigest()

            if content_type == "video":
                vt = VideoTrack(
                    id_=track_id,
                    source=source,
                    url=track_url,
                    codec=codec or "",
                    language=track_lang,
                    bitrate=ql.get("Bitrate"),
                    width=int(ql.get("MaxWidth") or 0) or stream_index.get("MaxWidth"),
                    height=int(ql.get("MaxHeight") or 0) or stream_index.get("MaxHeight"),
                    fps=stream_fps,
                    hdr10=False,
                    hlg=False,
                    dv=(codec and codec.lower() in ("dvhe", "dvh1")),
                    descriptor=Track.Descriptor.ISM,
                    encrypted=encrypted,
                    pr_pssh=pr_pssh,
                    pssh=pssh,
                    kid=kid,
                    duration=duration_sec,
                    extra=(ql, stream_index, root),
                )
                vt.smooth = True
                tracks.append(vt)

            elif content_type == "audio":
                at = AudioTrack(
                    id_=track_id,
                    source=source,
                    url=track_url,
                    codec=codec or "",
                    language=track_lang,
                    bitrate=ql.get("Bitrate"),
                    channels=None,
                    descriptor=Track.Descriptor.ISM,
                    encrypted=encrypted,
                    pr_pssh=pr_pssh,
                    pssh=pssh,
                    kid=kid,
                    duration=duration_sec,
                    extra=(ql, stream_index, root),
                )
                at.smooth = True
                tracks.append(at)

            elif content_type == "text":
                tt = TextTrack(
                    id_=track_id,
                    source=source,
                    url=track_url,
                    codec=codec or "ttml",
                    language=track_lang,
                    descriptor=Track.Descriptor.ISM,
                    encrypted=encrypted,
                    pr_pssh=pr_pssh,
                    pssh=pssh,
                    kid=kid,
                    duration=duration_sec,
                    extra=(ql, stream_index, root),
                )
                tt.smooth = True
                tracks.append(tt)

    tracks_obj = Tracks()
    tracks_obj.add(tracks, warn_only=True)

    return tracks_obj