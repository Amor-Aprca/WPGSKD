import base64
import re
import logging
from hashlib import md5
import m3u8

from wpgskd.core.tracks import AudioTrack, TextTrack, Track, Tracks, VideoTrack
from wpgskd.constants import EncryptionScheme
from wpgskd.core.utilities import Cdm
from wpgskd.vendor.pymp4.parser import Box

log = logging.getLogger("HLSParser")

def parse(master, source=None, session=None):
    """
    Convert a Variant Playlist M3U8 document to a Tracks object with Video, Audio and
    Subtitle Track objects. This is not an M3U8 parser, use https://github.com/globocom/m3u8
    to parse, and then feed the parsed M3U8 object.

    :param master: M3U8 object of the `m3u8` project: https://github.com/globocom/m3u8
    :param source: Source tag for the returned tracks.
    """
    if not master.is_variant:
        raise ValueError("Tracks.from_m3u8: Expected a Variant Playlist M3U8 document...")

    # Get PSSH if available
    # Uses master.session_keys instead of master.keys as master.keys is ONLY EXT-X-KEYS and
    # doesn't include EXT-X-SESSION-KEYS which is what's used for variant playlist M3U8.
    widevine_urn = "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"
    widevine_keys = [x.uri for x in master.session_keys
                     if x.keyformat and x.keyformat.lower() == widevine_urn]
    pssh = widevine_keys[0].split(",")[-1] if widevine_keys else None

    pr_keys = [x.uri for x in master.session_keys
               if x.keyformat and "playready" in x.keyformat.lower()]
    pr_pssh = pr_keys[0].split(",")[-1] if pr_keys else None

    if pssh:
        pssh = base64.b64decode(pssh)
        try:
            pssh = Box.parse(pssh)
        except Exception:
            pssh = Box.parse(Box.build(dict(
                type=b"pssh",
                version=0,
                flags=0,
                system_ID=Cdm.uuid,
                init_data=pssh
            )))

    # Also check top-level keys (non-session) as fallback
    if not pssh and not pr_pssh:
        widevine_top = [x.uri for x in master.keys
                        if x.keyformat and x.keyformat.lower() == widevine_urn]
        if widevine_top:
            pssh_raw = widevine_top[0].split(",")[-1]
            pssh_raw = base64.b64decode(pssh_raw)
            try:
                pssh = Box.parse(pssh_raw)
            except Exception:
                pssh = Box.parse(Box.build(dict(
                    type=b"pssh",
                    version=0,
                    flags=0,
                    system_ID=Cdm.uuid,
                    init_data=pssh_raw
                )))

        pr_top = [x.uri for x in master.keys
                  if x.keyformat and "playready" in x.keyformat.lower()]
        if pr_top:
            pr_pssh = pr_top[0].split(",")[-1]

    # Determine default encryption scheme
    default_scheme = EncryptionScheme.NONE
    if pssh:
        default_scheme = EncryptionScheme.WIDEVINE
    elif pr_pssh:
        default_scheme = EncryptionScheme.PLAYREADY

    # Check for AES-128 keys at master level
    aes128_keys = [x for x in (master.keys + master.session_keys)
                   if x.method and x.method.upper() == "AES-128"]
    if aes128_keys and not pssh and not pr_pssh:
        default_scheme = EncryptionScheme.AES_128

    has_encryption = bool(pssh or pr_pssh or aes128_keys or master.keys or master.session_keys)

    tracks_obj = Tracks()

    # ==================== VIDEO TRACKS ====================
    for x in master.playlists:
        stream_info = x.stream_info
        
        codec_str = _safe_get_codec(stream_info)
        resolution = _safe_get_resolution(stream_info)

        tracks_obj.add(VideoTrack(
            id_=md5(str(x).encode()).hexdigest()[0:7],
            source=source,
            url=("" if re.match("^https?://", x.uri) else x.base_uri) + x.uri,
            codec=codec_str,
            language=None,  # playlists don't state the language, fallback must be used
            bitrate=_safe_get_bitrate(stream_info),
            width=resolution[0],
            height=resolution[1],
            fps=_safe_get_frame_rate(stream_info),
            hdr10=(not _is_dv(codec_str) and _safe_get_video_range(stream_info) != "SDR"),
            hlg=False,
            dv=_is_dv(codec_str),
            descriptor=Track.Descriptor.M3U,
            encryption_scheme=default_scheme,
            encrypted=has_encryption,
            extra={"original": x, "master_pssh": pssh, "master_pr_pssh": pr_pssh} 
        ))

    # ==================== AUDIO + SUBTITLE TRACKS ====================
    if hasattr(master, 'media') and master.media:
        for x in master.media:
            # === AUDIO ===
            if x.type == "AUDIO" and x.uri:
                channels = x.channels if hasattr(x, 'channels') else None
                group_id = x.group_id if hasattr(x, 'group_id') else None
                bitrate = 0
                
                if group_id:
                    br_match = re.search(r'_(\d+)$', group_id)
                    if br_match:
                        bitrate = int(br_match.group(1)) * 1000
                    
                    if not channels:
                        ch_match = re.search(r'(\d+)ch', group_id)
                        if ch_match:
                            channels = f"{ch_match.group(1)}.0"

                characteristics = x.characteristics or "" if hasattr(x, 'characteristics') else ""

                tracks_obj.add(AudioTrack(
                    id_=md5(str(x).encode()).hexdigest()[0:6],
                    source=source,
                    url=("" if re.match("^https?://", x.uri) else x.base_uri) + x.uri,
                    codec=_safe_get_audio_codec(x),
                    language=x.language,
                    bitrate=bitrate,
                    channels=channels,
                    atmos=(channels or "").endswith("/JOC"),
                    descriptive="public.accessibility.describes-video" in characteristics,
                    descriptor=Track.Descriptor.M3U,
                    encryption_scheme=default_scheme,
                    encrypted=has_encryption,
                    extra={"original": x, "master_pssh": pssh, "master_pr_pssh": pr_pssh} 
                ))

            # === SUBTITLES ===
            elif x.type == "SUBTITLES" and x.uri:
                forced = x.forced == "YES" if hasattr(x, 'forced') else False
                characteristics = x.characteristics or "" if hasattr(x, 'characteristics') else ""
                name = x.name if hasattr(x, 'name') else ""
                group_id = x.group_id if hasattr(x, 'group_id') else ""
                
                is_cc = "cc" in name.lower() or "cc" in group_id.lower()

                tracks_obj.add(TextTrack(
                    id_=md5(str(x).encode()).hexdigest()[0:6],
                    source=source,
                    url=("" if re.match("^https?://", x.uri) else x.base_uri) + x.uri,
                    codec="vtt",
                    language=x.language,
                    forced=forced,
                    sdh="public.accessibility.describes-music-and-sound" in characteristics or is_cc,
                    descriptor=Track.Descriptor.M3U,
                    encryption_scheme=default_scheme,
                    encrypted=has_encryption,
                    extra={"original": x, "master_pssh": pssh, "master_pr_pssh": pr_pssh} 
                ))

    if tracks_obj.videos:
        try:
            from wpgskd.core.session import SessionBuilder
            s = session or SessionBuilder.build()
        except ImportError:
            import requests as req_mod
            s = session or req_mod.Session()
            
        first_video = tracks_obj.videos[0]
        try:
            sub_url = first_video.url
            if isinstance(sub_url, list):
                sub_url = sub_url[0]
            res = s.get(sub_url, timeout=10)
            res.raise_for_status()
            sub_m3u8 = m3u8.loads(res.text, uri=sub_url)
            
            total_duration = sum(seg.duration for seg in sub_m3u8.segments if seg.duration)
            fps = _infer_fps_from_segments(sub_m3u8.segments)
            
            if total_duration:
                for v in tracks_obj.videos:
                    v.duration = total_duration
                    if fps:
                        v.fps = fps
                    if v.bitrate:
                        v.size = int((float(v.bitrate) * total_duration) / 8)
                        
                for a in tracks_obj.audios:
                    a.duration = total_duration
                    if a.bitrate:
                        a.size = int((float(a.bitrate) * total_duration) / 8)

            if not has_encryption and sub_m3u8.keys:
                has_encryption = True
                for key in sub_m3u8.keys:
                    if key.method and key.method.upper() in ("SAMPLE-AES", "SAMPLE-AES-CTR"):
                        keyformat = key.keyformat
                        if keyformat and "edef8ba9-79d6-4ace-a3c8-27dcd51d21ed" in keyformat:
                            if not pssh and key.uri and "base64," in key.uri:
                                try:
                                    pssh_raw = key.uri.split("base64,")[-1]
                                    pssh_data = base64.b64decode(pssh_raw)
                                    try:
                                        pssh = Box.parse(pssh_data)
                                    except Exception:
                                        pssh = Box.parse(Box.build(dict(
                                            type=b"pssh", version=0, flags=0, system_ID=Cdm.uuid, init_data=pssh_data
                                        )))
                                except Exception as e:
                                    log.debug(f"Failed to decode Widevine PSSH from sub-manifest: {e}")
                        
                        if not pr_pssh and keyformat and "9a04f079-9840-4286-ab92-e65be0885f95" in keyformat:
                            if key.uri and "base64," in key.uri:
                                pr_pssh = key.uri.split("base64,")[-1]

                if has_encryption:
                    default_scheme = EncryptionScheme.WIDEVINE if pssh else EncryptionScheme.PLAYREADY if pr_pssh else EncryptionScheme.SAMPLE_AES
                    for track in tracks_obj:
                        track.encrypted = True
                        track.encryption_scheme = default_scheme
                        if isinstance(track.extra, dict):
                            if pssh and not track.extra.get("master_pssh"):
                                track.extra["master_pssh"] = pssh
                            if pr_pssh and not track.extra.get("master_pr_pssh"):
                                track.extra["master_pr_pssh"] = pr_pssh
                        else:
                            track.extra = {"master_pssh": pssh, "master_pr_pssh": pr_pssh}
                            
        except Exception as e:
            log.warning(f"Failed to probe HLS sub-manifest for duration/fps: {e}")

    return tracks_obj

def _safe_get_codec(stream_info):
    """Safely extract codec from stream_info, handling None values."""
    try:
        if hasattr(stream_info, 'codecs') and stream_info.codecs:
            return stream_info.codecs.split(",")[0].split(".")[0]
        return "h264"
    except (AttributeError, TypeError, IndexError):
        return "h264"

def _safe_get_resolution(stream_info):
    """Safely extract resolution from stream_info, handling None values."""
    try:
        if hasattr(stream_info, 'resolution') and stream_info.resolution:
            return stream_info.resolution
        return (0, 0)
    except (TypeError, AttributeError):
        return (0, 0)

def _safe_get_frame_rate(stream_info):
    """Safely extract frame rate from stream_info, handling None values."""
    try:
        if hasattr(stream_info, 'frame_rate') and stream_info.frame_rate:
            return stream_info.frame_rate
        return None
    except (TypeError, AttributeError):
        return None

def _safe_get_video_range(stream_info):
    """Safely extract video range from stream_info, handling None values."""
    try:
        if hasattr(stream_info, 'video_range') and stream_info.video_range:
            return stream_info.video_range.strip('"')
        return "SDR"
    except (TypeError, AttributeError):
        return "SDR"

def _safe_get_bitrate(stream_info):
    """Safely extract bitrate from stream_info, handling None values."""
    try:
        if hasattr(stream_info, 'average_bandwidth') and stream_info.average_bandwidth:
            return stream_info.average_bandwidth
        if hasattr(stream_info, 'bandwidth') and stream_info.bandwidth:
            return stream_info.bandwidth
        return 0
    except (TypeError, AttributeError):
        return 0

def _safe_get_audio_codec(media):
    """Safely extract audio codec from media entry."""
    try:
        if hasattr(media, 'codecs') and media.codecs:
            return media.codecs.split(",")[0].split(".")[0]
        if hasattr(media, 'group_id') and media.group_id:
            return media.group_id.replace("audio-", "").split("-")[0].split(".")[0]
        return "aac"
    except (AttributeError, TypeError, IndexError):
        return "aac"

def _is_dv(codec_str):
    """Check if codec indicates Dolby Vision."""
    try:
        if codec_str:
            return codec_str.split(".")[0] in ("dvhe", "dvh1")
        return False
    except (AttributeError, IndexError):
        return False
        
def _infer_fps_from_segments(segments):
    if not segments:
        return None
    
    durations = [seg.duration for seg in segments if seg.duration and seg.duration > 0]
    if not durations:
        return None
    
    avg_duration = sum(durations) / len(durations)
    
    for fps in [23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0]:
        frames = avg_duration * fps
        if abs(frames - round(frames)) < 0.15:
            return fps
    
    return None        
