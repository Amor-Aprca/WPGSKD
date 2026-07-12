import os
import re
import sys
import json
import time
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Tuple, List, Optional
from io import TextIOWrapper

from wpgskd.config import directories, filenames
from wpgskd.core.tracks.tracks import Tracks, TextTrack
from wpgskd.core.tracks.title import Title
from wpgskd.utils import is_close_match
from wpgskd.constants import LANGUAGE_MUX_MAP

log = logging.getLogger("Muxer")

class Muxer:

    @staticmethod
    def mux(title: Title, tracks: Tracks, no_sync_subs: bool = False) -> Tuple[str, int]:
        if not shutil.which("mkvmerge"):
            raise EnvironmentError("mkvmerge executable not found in PATH.")

        out_dir = Path(directories.downloads)
        if title.type == Title.Types.TV:
            out_dir = out_dir / title.parse_filename(folder=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        muxed_location = out_dir / f"{title.parse_filename()}.muxed.mkv"
        
        if muxed_location.exists():
            muxed_location.unlink()

        cl = ["mkvmerge", "--output", str(muxed_location)]

        for i, vt in enumerate(tracks.videos):
            location = vt.locate()
            if not location:
                raise ValueError("A Video Track was not downloaded before muxing...")
            cl.extend([
                "--language", "0:und",
                "--disable-language-ietf",
                "--default-track", f"0:{i == 0}",
                "--compression", "0:none",
                "(", location, ")"
            ])

        for i, at in enumerate(tracks.audios):
            location = at.locate()
            if not location:
                raise ValueError("An Audio Track was not downloaded before muxing...")
            
            audio_display = at.get_codec_display()
            if at.atmos and "Atmos" not in audio_display:
                audio_display += " Atmos"

            cl.extend([
                "--track-name", f"0:{at.get_track_name() or audio_display}",
                "--language", f"0:{LANGUAGE_MUX_MAP.get(str(at.language), at.language.to_alpha3())}",
                "--disable-language-ietf",
                "--default-track", f"0:{i == 0}",
                "--compression", "0:none",
                "(", location, ")"
            ])

        subtitles_to_mux = tracks.subtitles if not no_sync_subs else []
        for st in subtitles_to_mux:
            location = st.locate()
            if not location:
                raise ValueError("A Text Track was not downloaded before muxing...")
            
            try:
                if os.path.getsize(location) < 6:
                    continue
            except Exception:
                continue

            try:
                with open(location, "r", encoding="utf-8", errors="ignore") as f:
                    head = f.read(512)
                if re.match(r"CHAPTER\d+=", head.strip(), re.IGNORECASE):
                    continue
            except Exception:
                pass

            default = bool(
                tracks.audios and is_close_match(st.language, [tracks.audios[0].language]) and st.forced
            )

            sub_cmd = [
                "--track-name", f"0:{st.get_track_name() or ''}",
                "--language", f"0:{LANGUAGE_MUX_MAP.get(str(st.language), st.language.to_alpha3())}",
                "--disable-language-ietf",
                "--sub-charset", "0:UTF-8",
                "--forced-track", f"0:{st.forced}",
                "--default-track", f"0:{default}",
                "--compression", "0:none",
            ]
            sub_cmd.extend(["(", location, ")"])
            cl.extend(sub_cmd)

        if tracks.chapters:
            chapters_file = filenames.chapters.format(filename=title.filename)
            tracks.export_chapters(chapters_file)
            cl.extend(["--chapters", chapters_file])

        log.info(f"Muxing tracks into {muxed_location.name}...")
        p = subprocess.Popen(cl, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        in_progress = False
        
        for line in TextIOWrapper(p.stdout, encoding="utf-8"):
            if re.search(r"Using the (?:demultiplexer|output module) for the format", line):
                continue
            if line.startswith("Progress:"):
                in_progress = True
                sys.stdout.write("\r" + line.rstrip('\n'))
            else:
                if in_progress:
                    in_progress = False
                    sys.stdout.write("\n")
                sys.stdout.write(line)
                
        returncode = p.wait()
        return str(muxed_location), returncode

    @staticmethod
    def export_chapters(chapters: list, to_file: str = None) -> str:
        data = "\n".join(map(repr, chapters))
        if to_file:
            os.makedirs(os.path.dirname(to_file) or ".", exist_ok=True)
            with open(to_file, "w", encoding="utf-8") as fd:
                fd.write(data)
        return data

    @staticmethod
    def apply_sync(mkv_path: str):
        sync_log = logging.getLogger("SyncVAT")
        mkvmerge_path = shutil.which("mkvmerge")
        ffprobe_path = shutil.which("ffprobe")

        if not os.path.exists(mkv_path):
            sync_log.error(f"MKV file not found: {mkv_path}")
            return

        sync_log.info("Waiting 2 seconds for file IO...")
        time.sleep(2)

        output_path = os.path.splitext(mkv_path)[0] + ".synced.mkv"

        try:
            result = subprocess.run(
                [mkvmerge_path, "-J", mkv_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, errors="replace"
            )
            mkv_info = json.loads(result.stdout) if result.returncode == 0 else {}

            video_duration = None
            audio_tracks = []

            for track in mkv_info.get("tracks", []):
                track_type = track.get("type")
                properties = track.get("properties", {})
                track_id = track["id"]

                duration_sec = None
                if properties.get("tag_duration"):
                    try:
                        parts = properties["tag_duration"].split(":")
                        if len(parts) == 3:
                            duration_sec = float(parts[2]) + int(parts[1]) * 60 + int(parts[0]) * 3600
                    except Exception:
                        pass

                if duration_sec is None and properties.get("duration"):
                    try:
                        duration_sec = float(properties["duration"]) / 1e9
                    except Exception:
                        pass

                if track_type == "video":
                    if video_duration is None and duration_sec:
                        video_duration = duration_sec
                elif track_type == "audio":
                    if duration_sec:
                        audio_tracks.append({"id": track_id, "duration": duration_sec})

            if not video_duration and ffprobe_path:
                sync_log.info("Video duration missing in mkvmerge, probing with ffprobe...")
                try:
                    ff_cmd = [
                        ffprobe_path, "-v", "error",
                        "-select_streams", "v:0",
                        "-show_entries", "format=duration:stream=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        mkv_path
                    ]
                    ff_res = subprocess.run(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                    valid_durations = []
                    for line in ff_res.stdout.splitlines():
                        line = line.strip()
                        if line and line != 'N/A':
                            try:
                                valid_durations.append(float(line))
                            except ValueError:
                                pass

                    if valid_durations:
                        video_duration = max(valid_durations)
                except Exception as e:
                    sync_log.warning(f"FFprobe failed: {e}")

            if not video_duration:
                sync_log.warning("Could not determine Video Duration. Skipping Sync.")
                return

            sync_log.info(f"Video Duration: {video_duration:.4f}s")

            needs_sync = False
            cmd = [mkvmerge_path, "-o", output_path]

            count = 0
            for audio in audio_tracks:
                if audio["duration"] > video_duration + 0.1:
                    factor = video_duration / audio["duration"]
                    cmd.extend(["--sync", f"{audio['id']}:0,{factor:.9f}"])
                    sync_log.info(
                        f"Syncing Audio {audio['id']}: {audio['duration']:.4f}s -> "
                        f"{video_duration:.4f}s (Factor: {factor:.6f})"
                    )
                    needs_sync = True
                    count += 1

            if not needs_sync:
                sync_log.info("Audio duration matches video, no sync needed.")
                return

            cmd.append(mkv_path)

            sync_log.info(f"Re-muxing to fix {count} audio tracks...")
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

            time.sleep(1)
            if os.path.exists(mkv_path):
                os.unlink(mkv_path)
            os.rename(output_path, mkv_path)
            sync_log.info("Sync completed successfully on final file.")

        except Exception as e:
            sync_log.error(f"SyncVAT Failed: {e}")
            if os.path.exists(output_path):
                try:
                    os.unlink(output_path)
                except Exception:
                    pass