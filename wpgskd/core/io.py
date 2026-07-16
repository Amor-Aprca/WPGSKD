import asyncio
import contextlib
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pproxy
import requests
import yaml
import tqdm

log = logging.getLogger("io")

def load_yaml(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with open(path) as fd:
        return yaml.safe_load(fd)

_ip_info = None

def get_ip_info(session=None, fresh=False) -> dict:
    """Use multiple services to get IP location information."""
    global _ip_info
    if fresh or not _ip_info:
        session = session or httpx
        try:
            resp = session.get("https://ipwho.is/").json()
            if resp.get("success") is not False:
                _ip_info = resp
                return _ip_info
        except Exception:
            pass
        try:
            resp = session.get("http://ip-api.com/json/").json()
            if "countryCode" in resp:
                _ip_info = {"country_code": resp["countryCode"]}
                return _ip_info
        except Exception:
            pass
        logging.getLogger("io").warning("Failed to get IP info. Assuming US.")
        _ip_info = {"country_code": "US"}
    return _ip_info

@contextlib.asynccontextmanager
async def start_pproxy(host, port, username, password):
    rerouted_proxy = "http://localhost:8081"
    server = pproxy.Server(rerouted_proxy)
    remote = pproxy.Connection(f"http+ssl://{host}:{port}#{username}:{password}")
    handler = await server.start_server(dict(rserver=[remote]))
    try:
        yield rerouted_proxy
    finally:
        handler.close()
        await handler.wait_closed()

async def aria2c(uri, out, headers=None, proxy=None):
    """Downloads file(s) using Aria2(c)."""
    executable = shutil.which("aria2c") or shutil.which("aria2")
    if not executable:
        raise EnvironmentError("Aria2c executable not found...")

    arguments = [
        executable, "-c", "--remote-time",
        "-o", os.path.basename(out),
        "-x", "16", "-j", "16", "-s", "16",
        "--allow-overwrite=true", "--auto-file-renaming=false",
        "--retry-wait", "5", "--max-tries", "15",
        "--max-file-not-found", "15", "--summary-interval", "0",
        "--file-allocation", "none" if sys.platform == "win32" else "falloc",
        "--console-log-level", "warn", "--download-result", "hide",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    ]

    for header, value in (headers or {}).items():
        if header.lower() == "accept-encoding": continue
        arguments.extend(["--header", f"{header}: {value}"])

    segmented = isinstance(uri, list)
    segments_dir = f"{out}_segments"

    if segmented:
        uri = "\n".join([
            f"{url}\n\tdir={segments_dir}\n\tout={i:08}.mp4"
            for i, url in enumerate(uri)
        ])

    if proxy:
        arguments.append("--all-proxy")
        if proxy.lower().startswith("https://"):
            auth, hostname = proxy[8:].split("@")
            async with start_pproxy(*hostname.split(":"), *auth.split(":")) as pproxy_:
                arguments.extend([pproxy_, "-d"])
                if segmented:
                    arguments.extend([segments_dir, "-i-"])
                    proc = await asyncio.create_subprocess_exec(*arguments, stdin=subprocess.PIPE)
                    await proc.communicate(uri.encode("utf-8"))
                else:
                    arguments.extend([os.path.dirname(out), uri])
                    proc = await asyncio.create_subprocess_exec(*arguments)
                    await proc.communicate()
        else:
            arguments.append(proxy)

    try:
        if segmented:
            subprocess.run(arguments + ["-d", segments_dir, "-i-"], input=uri, encoding="utf-8", check=True)
        else:
            subprocess.run(arguments + ["-d", os.path.dirname(out), uri], check=True)
    except subprocess.CalledProcessError:
        raise ValueError("Aria2c failed too many times, aborting")

    if segmented:
        with open(out, "wb") as ofd:
            for file in sorted(os.listdir(segments_dir)):
                file_path = os.path.join(segments_dir, file)
                with open(file_path, "rb") as ifd:
                    data = ifd.read()
                # Apple TV+ audio decryption fix
                data = re.sub(b"(tfhd\x00\x02\x00\x1a\x00\x00\x00\x01\x00\x00\x00)\x02", b"\\g<1>\x01", data)
                ofd.write(data)
                os.unlink(file)
        os.rmdir(segments_dir)

async def m3u8re(uri, out, headers=None, proxy=None, key=None):
    out = Path(out)
    if headers:
        headers.update({k: v for k, v in headers.items() if k.lower() != "accept-encoding"})

    executable = shutil.which("m3u8re") or shutil.which("N_m3u8DL-RE")
    if not executable:
        raise EnvironmentError("N_m3u8DL-RE executable not found...")

    if isinstance(uri, list):
        uri = uri[0]

    arguments = [
        executable, uri,
        "--tmp-dir", str(out.parent),
        "--save-dir", str(out.parent),
        "--save-name", out.name.replace('.mp4','').replace('.vtt','').replace('.m4a',''),
        "--auto-subtitle-fix", "False",
        "--thread-count", "32",
        "--log-level", "INFO"
    ]
    
    if key:
        arguments.extend(["--key", key])
        
    if headers:
        arguments.extend(["--header", "\r\n".join([f"{k}: {v}" for k, v in headers.items()])])
        
    if proxy:
        arguments.extend(["--custom-proxy", proxy])

    try:
        subprocess.run(arguments, check=True)
    except subprocess.CalledProcessError:
        raise ValueError("N_m3u8DL-RE failed too many times, aborting")

async def n_m3u8dl_re_dash(manifest_url, save_path, headers=None, proxy=None, track_id=None, kid_key_pairs=None):
    out = Path(save_path)
    executable = shutil.which("N_m3u8DL-RE") or shutil.which("m3u8re")
    if not executable:
        raise EnvironmentError("N_m3u8DL-RE executable was not found.")

    arguments = [
        executable, manifest_url,
        "--tmp-dir", str(out.parent), "--save-dir", str(out.parent),
        "--save-name", out.stem, "--log-level", "INFO",
        "--mux-after-done", "format=mkv",
    ]

    if headers:
        arguments.extend(["--header", "\r\n".join([f"{k}: {v}" for k, v in headers.items()])])

    if proxy:
        arguments.extend(["--custom-proxy", proxy])
    else:
        arguments.append("--no-proxy")

    if track_id:
        if 'video' in out.name.lower():
            arguments.extend(["-sv", f"id={track_id}", "-sa", "best"])
        elif 'audio' in out.name.lower():
            arguments.extend(["-sa", f"id={track_id}"])
    
    if kid_key_pairs:
        for kid, key in kid_key_pairs:
            arguments.extend(["--key", f"{kid}:{key}"])

    try:
        subprocess.run(arguments, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    except subprocess.CalledProcessError as e:
        raise ValueError("N_m3u8DL-RE (fallback) failed, aborting")

    expected_mkv_path = out.with_suffix('.mkv')
    if expected_mkv_path.exists():
        if out.exists() and out.resolve() != expected_mkv_path.resolve():
            out.unlink()
        expected_mkv_path.rename(out)
    elif not out.exists():
        raise FileNotFoundError(f"N_m3u8DL-RE finished, but expected output file '{out}' was not found.")