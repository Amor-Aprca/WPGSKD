import os
import sys
import re
import shutil
import logging
import subprocess
from typing import Optional, Dict, Any
from io import TextIOWrapper

from wpgskd.core.tracks.tracks import Track
from wpgskd.core.tracks.video import VideoTrack
from wpgskd.core.tracks.audio import AudioTrack

log = logging.getLogger("Decryptor")

class Decryptor:

    @staticmethod
    def find_executable(name: str) -> Optional[str]:
        if name == "packager":
            plat = {"win32": "win", "darwin": "osx"}.get(sys.platform, sys.platform)
            candidates = ["shaka-packager", "packager", f"packager-{plat}"]
            for c in candidates:
                path = shutil.which(c)
                if path: return path
            return None
        if name == "mp4decrypt":
            return shutil.which("mp4decrypt")
        return shutil.which(name)

    @staticmethod
    def decrypt(track: Track, keys: Dict[str, str], engine: str, temp_dir: str) -> Optional[str]:
        src = track.locate()
        if not src or not os.path.exists(src):
            log.error(f"Source file not found for decryption: {src}")
            return None

        dst = os.path.splitext(src)[0] + ".dec.mp4"
        
        if getattr(track, 'smooth', False) or getattr(track, 'encryption_scheme', None) == 'clearkey':
            engine = "mp4decrypt"

        if engine == "packager":
            dec = Decryptor._packager(track, keys, src, dst, temp_dir)
        elif engine == "mp4decrypt":
            dec = Decryptor._mp4decrypt(keys, src, dst)
        else:
            log.error(f"Unsupported decrypter engine: {engine}")
            return None

        return dec

    @staticmethod
    def _packager(track: Track, keys: Dict[str, str], src: str, dst: str, tmp: str) -> Optional[str]:
        exe = Decryptor.find_executable("packager")
        if not exe:
            raise FileNotFoundError("shaka-packager executable not found")

        stream = track.__class__.__name__.lower().replace("track", "")
        
        pk = track.kid.lower().replace("-", "")
        pv = keys.get(pk, next(iter(keys.values()), "")) if keys else ""
        
        if not pv:
            log.error("No valid key provided for shaka-packager")
            return None

        os.makedirs(tmp, exist_ok=True)
        
        cmd = [
            exe,
            f"input={src},stream={stream},output={dst}",
            "--enable_raw_key_decryption", "--keys",
            f"label=0:key_id={pk}:key={pv.lower()}, "
            f"label=1:key_id={'0' * 32}:key={pv.lower()}",
            "--temp_dir", tmp,
        ]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        last = ""
        
        for line in proc.stdout:
            line = line.strip()
            if not line: continue
            
            if re.match(r"^\d+/\d+$", line):
                sys.stdout.write(f"\r   + Decrypting: {line}")
                sys.stdout.flush()
                last = line
            elif "Packaging completed successfully" in line:
                msg = f"{last} - Complete" if last else "Complete"
                sys.stdout.write(f"\r   + Decrypting: {msg}\n")
                sys.stdout.flush()
            elif any(w in line.lower() for w in ("error", "fail", "warning")):
                print(f"\n   ! {line}")
            elif line and not any(t in line for t in ("progress", "%", "[", "]")):
                print(f"\n   + {line}")
                
        proc.wait()
        
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, proc.args)
            
        return dst

    @staticmethod
    def _mp4decrypt(keys: Dict[str, str], src: str, dst: str) -> Optional[str]:
        exe = Decryptor.find_executable("mp4decrypt")
        if not exe:
            raise FileNotFoundError("mp4decrypt executable not found")

        cmd = [exe, "--show-progress"]
        
        for kid, key in keys.items():
            cmd.extend(["--key", f"{kid}:{key.lower()}"])
            
        cmd.extend([src, dst])

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        for line in proc.stdout:
            line = line.strip()
            if not line: continue
            
            if re.search(r"\d+%", line) or re.search(r"\d+/\d+", line):
                sys.stdout.write(f"\r   + Decrypting: {line}")
                sys.stdout.flush()
            elif "Progress" in line:
                continue
            elif any(w in line.lower() for w in ("error", "fail")):
                print(f"\n   ! {line}")
            else:
                print(f"   + {line}")
                
        proc.wait()
        
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, proc.args)
            
        return dst

    @staticmethod
    def repackage(path: str) -> bool:
        if not shutil.which("ffmpeg"):
            log.warning("FFmpeg not found, skipping repackage")
            return False

        fixed = f"{path}_fixed.mkv"
        try:
            proc = subprocess.Popen([
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", path, "-map_metadata", "-1",
                "-fflags", "bitexact", "-codec", "copy", fixed,
            ], stderr=subprocess.PIPE, text=True)
            
            for line in proc.stderr:
                line = line.strip()
                if not line: continue
                if re.search(r"frame=\s*\d+", line):
                    sys.stdout.write(f"\r   + Repackaging: {line[:60]}")
                    sys.stdout.flush()
                elif "Insufficient bits" in line:
                    sys.stdout.write(f"\n   ! {line}\n   + Continuing...")
                    sys.stdout.flush()
                elif "error" in line.lower():
                    print(f"\n   ! {line}")
                    
            proc.wait()
            
            if proc.returncode == 0 and os.path.exists(fixed):
                sys.stdout.write("\r   + Repackaging: Complete\n")
                sys.stdout.flush()
                os.unlink(path)
                os.rename(fixed, path)
                return True
                
            sys.stdout.write("\n")
            log.warning(" - Repackage failed, keeping original file")
            if os.path.exists(fixed):
                os.unlink(fixed)
            return False
            
        except Exception as e:
            sys.stdout.write("\n")
            log.warning(f" - Repackage failed: {e}")
            if os.path.exists(fixed):
                os.unlink(fixed)
            return False