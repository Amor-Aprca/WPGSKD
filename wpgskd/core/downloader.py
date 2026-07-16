import re
import os
import sys
import shutil
import logging
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Any

import requests

from wpgskd.constants import EncryptionScheme
from wpgskd.core.tracks.tracks import Track
from wpgskd.core.io import aria2c, m3u8re

log = logging.getLogger("Downloader")

class Downloader:

    def __init__(self, session: requests.Session):
        self.session = session

    def download(self, track: Track, out_dir: str, name: str = None, headers: dict = None, 
                 proxy: str = None, title_ref: Any = None, all_keys: dict = None):

        if track.__class__.__name__ == "TextTrack" and isinstance(track.url, list):
            os.makedirs(out_dir, exist_ok=True)
            re_name = (name or "{type}_{id}_{enc}").format(
                type=track.__class__.__name__,
                id=track.id,
                enc="dec" if not track.encrypted else "enc"
            )
            save_path = os.path.join(out_dir, self._get_filename(track, re_name))
            self._download_and_merge_vtt(track.url, save_path, headers, proxy)
            track._location = save_path
            return

        if os.path.isfile(out_dir):
            raise ValueError("Path must be to a directory and not to a file")

        os.makedirs(out_dir, exist_ok=True)

        merged_headers = {}
        if headers:
            merged_headers.update(headers)
        if isinstance(getattr(track, 'extra', None), dict):
            track_headers = track.extra.get("headers")
            if isinstance(track_headers, dict):
                merged_headers.update(track_headers)
        headers = merged_headers or None

        re_name = (name or "{type}_{id}_{enc}").format(
            type=track.__class__.__name__,
            id=track.id,
            enc="enc" if track.encrypted else "dec"
        )

        if track.source.lower() == "abematv":
            self._download_abematv(track, out_dir, re_name)
            return

        if getattr(track, 'manifest_url', None) and getattr(track, 'mpd_representation_id', None):
            save_path = os.path.join(out_dir, self._get_filename(track, re_name))
            self._download_dash_manifest(track, save_path, headers, proxy)
            track._location = save_path
            return

        if track.descriptor == Track.Descriptor.ISM or getattr(track, 'smooth', False):
            self._download_ism(track, out_dir, re_name, headers, proxy)
            return

        if track.descriptor == Track.Descriptor.M3U and track.encryption_scheme == EncryptionScheme.AES_128:
            save_path = os.path.join(out_dir, self._get_filename(track, re_name))
            self._download_m3u8(track, save_path, headers, proxy)
            track._location = save_path
            return

        first_url = track.url[0] if isinstance(track.url, list) else track.url
        if track.descriptor == Track.Descriptor.M3U and isinstance(first_url, str) and ".m3u8" in first_url:
            save_path = os.path.join(out_dir, self._get_filename(track, re_name))
            self._download_m3u8(track, save_path, headers, proxy)
            track._location = save_path
            return

        if isinstance(track.url, list) and ".m3u8" in first_url:
            save_path = os.path.join(out_dir, self._get_filename(track, re_name))
            self._download_m3u8(track, save_path, headers, proxy)
            track._location = save_path
            return

        save_path = os.path.join(out_dir, self._get_filename(track, re_name))
        try:
            req_headers = headers if track.source not in ["ATVP", "iT"] else {}
            asyncio.run(aria2c(
                track.url, save_path,
                req_headers,
                proxy if track.needs_proxy else None
            ))
            track._location = save_path
        except (ValueError, subprocess.CalledProcessError) as e:
            dash_url = getattr(title_ref, 'dash_manifest_url', None) if title_ref else None
            if dash_url:
                log.warning(f"aria2c download failed. Attempting fallback with N_m3u8DL-RE...")
                try:
                    self._fallback_n_m3u8dl_re(track, dash_url, save_path, headers, proxy, all_keys)
                    track._location = save_path
                except Exception as fallback_e:
                    log.error(f"Fallback download with N_m3u8DL-RE also failed: {fallback_e}")
                    raise e
            else:
                raise e

    def _get_filename(self, track: Track, re_name: str) -> str:
        is_ass = hasattr(track, 'codec') and track.codec and track.codec.lower() in ['ass', 'ssa']

        if is_ass:
            return f"{re_name}.ass"
        elif track.__class__.__name__ == "TextTrack":
            ext = "vtt"
            if hasattr(track, 'codec') and track.codec:
                c = track.codec.lower()
                if c in ["ttml", "stpp", "dfxp"]:
                    ext = "ttml"
                elif c == "srt":
                    ext = "srt"
            return f"{re_name}.{ext}"
        elif track.__class__.__name__ == "AudioTrack" and track.source in ["iT", "ATVP", "TVer", "NHKPlus"]:
            return f"{re_name}.m4a"
        else:
            return f"{re_name}.mp4"

    def _download_and_merge_vtt(self, urls: list, save_path: str, headers: dict, proxy: str):
        log.info(f"Downloading and merging {len(urls)} subtitle segments...")
        merged_vtt = ""
        
        req_headers = headers if headers else {}
        
        proxies = None
        if proxy:
            proxies = {"http": proxy, "https": proxy}

        for i, url in enumerate(urls):
            try:
                res = self.session.get(url, headers=req_headers, proxies=proxies, timeout=30)
                res.raise_for_status()
                content = res.content.decode('utf-8', errors='ignore')
                
                lines = content.splitlines()
                current_vtt = ""
                for line in lines:
                    if line.strip() == "WEBVTT" and i > 0:
                        continue
                    if line.startswith("X-TIMESTAMP-MAP"):
                        continue
                    current_vtt += line + "\n"

                if i == 0:
                    merged_vtt = current_vtt
                else:
                    if current_vtt.startswith("\n"):
                        current_vtt = current_vtt[1:]
                    merged_vtt += current_vtt
                    
            except Exception as e:
                log.error(f" - Failed to download subtitle segment {i}: {e}")
                raise

        merged_vtt = re.sub(r'\n{3,}', '\n\n', merged_vtt).strip() + "\n"
        
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(merged_vtt)   

    def _download_abematv(self, track: Track, out_dir: str, re_name: str):
        base_name = "VideoTrack_master_enc"
        muxed_location = os.path.join(out_dir, f"{base_name}.muxed.mkv")

        if os.path.exists(muxed_location):
            log.info(f"AbemaTV: Found pre-muxed file at {muxed_location}")
            track._location = muxed_location
            return

        video_path = os.path.join(out_dir, f"{base_name}.mp4")
        audio_path = os.path.join(out_dir, f"{base_name}.m4a")

        if os.path.exists(video_path) and os.path.exists(audio_path):
            log.info("Muxing AbemaTV tracks (RE output)...")
            cmd = [shutil.which("mkvmerge"), "-o", muxed_location, video_path, audio_path]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
            try:
                os.unlink(video_path)
                os.unlink(audio_path)
            except Exception:
                pass
            track._location = muxed_location
        elif os.path.exists(video_path):
            log.info("AbemaTV: Found single video file, using as muxed.")
            os.rename(video_path, muxed_location)
            track._location = muxed_location
        else:
            raise IOError("Missing RE output files for AbemaTV")

    def _download_m3u8(self, track: Track, save_path: str, headers: dict, proxy: str):
        log.info(f"Downloading HLS stream using N_m3u8DL-RE...")
        
        key = None
        if track.encryption_scheme == EncryptionScheme.AES_128:
            pass
        elif track.encryption_scheme == EncryptionScheme.CLEARKEY and track.key:
            key = f"{track.kid}:{track.key}"

        try:
            asyncio.run(m3u8re(
                track.url[0] if isinstance(track.url, list) else track.url,
                save_path,
                headers,
                proxy if track.needs_proxy else None,
                key=key
            ))
        except Exception as e:
            log.error(f"N_m3u8DL-RE failed: {e}")
            raise

    def _download_dash_manifest(self, track: Track, save_path: str, headers: dict, proxy: str):
        log.info(f"Downloading DASH manifest stream using N_m3u8DL-RE...")
        executable = shutil.which("N_m3u8DL-RE") or shutil.which("m3u8re")
        if not executable:
            raise EnvironmentError("N_m3u8DL-RE executable not found...")

        mpd_url = getattr(track, 'manifest_url', None)
        if not mpd_url:
            raise RuntimeError("MPD manifest URL missing for track")

        out_dir = Path(save_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            executable,
            mpd_url,
            "--save-name", Path(save_path).stem,
            "--save-dir", str(out_dir),
            "--tmp-dir", str(out_dir),
            "--auto-subtitle-fix", "False",
            "--log-level", "ERROR",
        ]

        if hasattr(track, "mpd_representation_id") and track.mpd_representation_id:
            cls_name = track.__class__.__name__
            if cls_name == "VideoTrack":
                cmd += ["--select-video", f"id={track.mpd_representation_id}"]
            elif cls_name == "AudioTrack":
                cmd += ["--select-audio", f"id={track.mpd_representation_id}"]
            elif cls_name == "TextTrack":
                cmd += ["--select-subtitle", f"id={track.mpd_representation_id}"]
        else:
            if track.__class__.__name__ == "TextTrack":
                cmd += ["--select-subtitle", f"lang={track.language}"]

        if track.needs_proxy and proxy:
            cmd += ["--custom-proxy", proxy]
        else:
            cmd += ["--use-system-proxy", "False"]

        if track.encryption_scheme == EncryptionScheme.CLEARKEY and getattr(track, 'key', None) and getattr(track, 'kid', None):
            cmd += ["--key", f"{track.kid}:{track.key}"]

        try:
            subprocess.run(cmd, check=True)
        except Exception as e:
            raise e

    def _download_ism(self, track: Track, out_dir: str, re_name: str, headers: dict, proxy: str):
        log.info(f"Downloading ISM stream using N_m3u8DL-RE...")
        executable = shutil.which("N_m3u8DL-RE") or shutil.which("m3u8re")
        if not executable:
            raise EnvironmentError("N_m3u8DL-RE executable not found...")

        first_url = track.url[0] if isinstance(track.url, list) else track.url
        ism_url = first_url.rsplit('/', 1)[0] + "/manifest"
        ism_url = ism_url.split('?')[0] 
        
        cmd = [
            executable,
            ism_url,
            "--save-name", re_name,
            "--save-dir", out_dir,
            "--tmp-dir", out_dir,
            "--auto-subtitle-fix", "True",
            "--log-level", "ERROR",
        ]
        
        if track.needs_proxy and proxy:
            cmd += ["--custom-proxy", proxy]
        else:
            cmd += ["--use-system-proxy", "False"]

        try:
            subprocess.run(cmd, check=True)
            files = list(Path(out_dir).glob(f"{re_name}*"))
            if files:
                track._location = str(files[0])
            else:
                raise IOError("ISM download produced no file")
        except Exception as e:
            raise e

    def _fallback_n_m3u8dl_re(self, track: Track, dash_manifest_url: str, save_path: str, headers: dict, proxy: str, all_keys: dict):
        executable = shutil.which("N_m3u8DL-RE") or shutil.which("m3u8re")
        if not executable:
            raise EnvironmentError("N_m3u8DL-RE executable not found...")

        cmd = [
            executable,
            dash_manifest_url,
            "--save-name", Path(save_path).stem,
            "--save-dir", str(Path(save_path).parent),
            "--tmp-dir", str(Path(save_path).parent),
            "--log-level", "INFO",
        ]

        if track.encrypted and all_keys and track.kid in all_keys:
            cmd.extend(["--key", f"{track.kid}:{all_keys[track.kid]}"])

        subprocess.run(cmd, check=True, capture_output=True, text=True)
