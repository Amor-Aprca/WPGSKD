import os
import re
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from io import BytesIO

from wpgskd.vendor.pymp4.parser import Box

log = logging.getLogger("Subtitles")

try:
    from subby import WebVTTConverter, SMPTEConverter, WVTTConverter, ISMTConverter, CommonIssuesFixer, SDHStripper
    SUBBY_AVAILABLE = True
except ImportError:
    SUBBY_AVAILABLE = False
    log.warning("subby library not found. Subtitle conversion will be limited.")

class SubtitleProcessor:
    _SDH_PATTERNS = [
        r'\[[^\]]*\]',      # [text]
        r'\([^\)]*\)',      # (text)
        r'\{[^\}]*\}',      # {text}
        r'<[^>]*>',         # <text>
        r'♪[^♪]*♪',         # ♪text♪
        r'[\*_][^\*_]+[\*_]',  # *text* or _text_
    ]

    @staticmethod
    def extract_mdat_text(data: bytes, codec: str) -> bytes:
        codec_lower = codec.lower()
        plain_text_codecs = {"vtt", "webvtt", "webvtt-lssdh-ios8", "ttml", "ttml2", "dfxp", "smpte"}

        if codec_lower in plain_text_codecs:
            return data

        collected = []
        try:
            for box_type, payload in SubtitleProcessor._iter_boxes(data):
                if box_type != b"mdat":
                    continue
                if codec_lower in ["wvtt", "stpp"]:
                    cues_data = SubtitleProcessor._extract_wvtt_text_from_mdat(payload)
                    if cues_data and len(cues_data) > 10:
                        collected.append(cues_data)
                    else:
                        clean = payload.lstrip(b"\x00").strip()
                        if clean and len(clean) > 10:
                            collected.append(clean)
                else:
                    clean = payload.lstrip(b"\x00").strip()
                    if clean and len(clean) > 10:
                        collected.append(clean)
        except Exception as e:
            log.debug(f"Error extracting MDAT: {e}")

        if not collected:
            return data
            
        result = b"\n".join(collected)
        if b"WEBVTT" not in result and b"-->" in result:
            lines = result.split(b'\n')
            for i, line in enumerate(lines):
                if b"-->" in line:
                    lines.insert(0, b"WEBVTT")
                    lines.insert(1, b"")
                    result = b'\n'.join(lines)
                    break
                    
        return result.replace(b'\x00', b'')

    @staticmethod
    def convert_to_srt(data: bytes, codec: str) -> Optional[Any]:
        if not SUBBY_AVAILABLE:
            return None

        codec_lower = codec.lower()
        converter = None
        
        if codec_lower in ["dfxp", "ttml", "ttml2", "smpte"]:
            converter = SMPTEConverter()
        elif codec_lower in ["vtt", "webvtt", "webvtt-lssdh-ios8"]:
            converter = WebVTTConverter()
        elif codec_lower == "wvtt":
            converter = WVTTConverter()
        elif codec_lower in ("cmfc", "stpp", "dash", "ism-C", "timed text"):
            converter = ISMTConverter()
        else:
            return None

        try:
            if isinstance(data, bytes):
                return converter.from_bytes(data)
            return converter.from_string(data)
        except Exception as e:
            log.warning(f"Failed to convert {codec} to SRT: {e}")
            return None

    @staticmethod
    def convert_subtitle_to_srt(save_path: str, strip_sdh: bool = True) -> Optional[str]:
        codec = ""
        if save_path.endswith(".vtt"): codec = "vtt"
        elif save_path.endswith(".ttml"): codec = "ttml"
        else: codec = "unknown"

        if codec.lower() in ["ass", "ssa"]:
            log.info(f" + ASS/SSA subtitle kept in original format")
            return save_path

        if codec.lower() == "ttml":
            log.info(f" + Converting TTML to SRT using subby...")
            try:
                from subby import SMPTEConverter
                converter = SMPTEConverter()
                with open(save_path, "rb") as fd:
                    srt_obj = converter.from_bytes(fd.read())
                
                srt_path = os.path.splitext(save_path)[0] + '.srt'
                srt_obj.save(srt_path)
                
                if os.path.exists(save_path):
                    os.unlink(save_path)
                log.info(f" + Subtitle converted to SRT: {os.path.basename(srt_path)}")
                return srt_path
            except Exception as e:
                log.warning(f" - TTML conversion failed: {e}")
                return save_path

        with open(save_path, "rb") as fd:
            raw = fd.read()

        if len(raw) < 10:
            log.warning(f" - Subtitle file too small ({len(raw)} bytes), skipping conversion")
            return save_path

        if codec.lower() in ["wvtt", "stpp"]:
            log.info(f" + Extracting text from {codec.upper()} container...")
            extracted = SubtitleProcessor.extract_mdat_text(raw, codec)
            if extracted and len(extracted) > 10:
                try:
                    vtt_content = extracted.decode('utf-8', errors='ignore')
                    srt_content = SubtitleProcessor.convert_vtt_to_srt(vtt_content, strip_sdh)
                    if srt_content and srt_content.strip():
                        srt_path = os.path.splitext(save_path)[0] + '.srt'
                        with open(srt_path, 'w', encoding='utf-8') as f:
                            f.write(srt_content)
                        if os.path.exists(save_path):
                            os.unlink(save_path)
                        log.info(f" + Subtitle converted to SRT: {os.path.basename(srt_path)}")
                        return srt_path
                except Exception as e:
                    log.warning(f" - Failed to decode extracted content: {e}")

        elif codec.lower() in ["vtt", "webvtt"]:
            try:
                if raw.startswith(b'\x00\x00\x00') or (len(raw) > 4 and raw[:4] == b'mdat'):
                    log.info(" + Detected binary VTT, extracting from MDAT...")
                    extracted = SubtitleProcessor.extract_mdat_text(raw, "vtt")
                    vtt_content = extracted.decode('utf-8', errors='ignore')
                else:
                    vtt_content = raw.decode('utf-8', errors='ignore')

                srt_content = SubtitleProcessor.convert_vtt_to_srt(vtt_content, strip_sdh)
                if srt_content and srt_content.strip():
                    srt_path = os.path.splitext(save_path)[0] + '.srt'
                    with open(srt_path, 'w', encoding='utf-8') as f:
                        f.write(srt_content)
                    if os.path.exists(save_path) and save_path != srt_path:
                        try: os.unlink(save_path)
                        except: pass
                    log.info(f" + Subtitle converted to SRT: {os.path.basename(srt_path)}")
                    return srt_path
            except Exception as e:
                log.warning(f" - VTT conversion failed: {e}")

        return save_path

    @staticmethod
    def convert_vtt_to_srt(vtt_content: str, strip_sdh: bool = True) -> str:
        lines = []
        counter = 1
        vtt_content = vtt_content.replace('\r\n', '\n')
        blocks = re.split(r'\n\s*\n', vtt_content)

        for block in blocks:
            block_lines = block.strip().split('\n')
            if not block_lines: continue

            first_line = block_lines[0].strip() if block_lines else ''
            if first_line == 'WEBVTT' or first_line.startswith('WEBVTT'): continue
            if first_line == 'STYLE': continue

            timestamp_line = None
            text_lines = []
            settings = ''

            for line in block_lines:
                line = line.strip()
                if '-->' in line:
                    timestamp_line = line
                    if ' line:' in line or ' position:' in line or ' align:' in line:
                        settings = line[line.find('-->') + 3:].strip()
                elif line and not line.isdigit() and '-->' not in line:
                    clean_line = re.sub(r'<(?!/?(?:i|b|u|s|ruby|rt|c))[^>]+>', '', line)
                    clean_line = re.sub(r'&nbsp;', ' ', clean_line)
                    if clean_line.strip():
                        if strip_sdh:
                            clean_line = SubtitleProcessor.strip_sdh_brackets(clean_line)
                        if clean_line.strip():
                            text_lines.append(clean_line)

            if timestamp_line and text_lines:
                ts_parts = timestamp_line.split('-->')
                if len(ts_parts) == 2:
                    start = ts_parts[0].strip().replace('.', ',')
                    end = ts_parts[1].split()[0].strip().replace('.', ',') if ts_parts[1] else ''
                    
                    def normalize_timestamp(ts):
                        if not ts: return ts
                        parts = ts.replace(',', ':').split(':')
                        if len(parts) == 2: return f"00:{parts[0].zfill(2)}:{parts[1].zfill(2)}"
                        elif len(parts) == 3: return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:{parts[2].zfill(2)}"
                        return ts

                    start = normalize_timestamp(start)
                    end = normalize_timestamp(end)

                    if ',' in start:
                        main, ms = start.split(',')
                        ms = ms.ljust(3, '0')[:3]
                        start = f"{main},{ms}"
                    if ',' in end:
                        main, ms = end.split(',')
                        ms = ms.ljust(3, '0')[:3]
                        end = f"{main},{ms}"

                    text = '\n'.join(text_lines)
                    if strip_sdh:
                        text = SubtitleProcessor.strip_sdh_brackets(text)

                    if text.strip():
                        lines.append(str(counter))
                        lines.append(f"{start} --> {end}")
                        lines.append(text)
                        lines.append("")
                        counter += 1

        return '\n'.join(lines)

    @staticmethod
    def strip_sdh_brackets(text: str) -> str:
        for pattern in SubtitleProcessor._SDH_PATTERNS:
            text = re.sub(pattern, '', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @staticmethod
    def _iter_boxes(data: bytes):
        offset = 0
        while offset + 8 <= len(data):
            box_size = int.from_bytes(data[offset:offset + 4], "big")
            box_type = data[offset + 4:offset + 8]
            if box_size < 8: break
            payload = data[offset + 8: offset + box_size]
            yield box_type, payload
            offset += box_size

    @staticmethod
    def _extract_wvtt_text_from_mdat(mdat_payload: bytes) -> bytes:
        cues = []
        offset = 0
        while offset + 8 <= len(mdat_payload):
            inner_size = int.from_bytes(mdat_payload[offset:offset + 4], "big")
            inner_type = mdat_payload[offset + 4:offset + 8]
            if inner_size < 8: break

            if inner_type == b"vttc":
                inner_payload = mdat_payload[offset + 8: offset + inner_size]
                cue_data = SubtitleProcessor._parse_vttc_box(inner_payload)
                if cue_data: cues.append(cue_data)
            offset += inner_size

        if not cues: return b""
        return SubtitleProcessor._reconstruct_vtt_from_cues(cues)

    @staticmethod
    def _parse_vttc_box(data: bytes) -> Optional[Dict]:
        result = {"start": None, "end": None, "text": [], "settings": ""}
        offset = 0
        while offset + 8 <= len(data):
            box_size = int.from_bytes(data[offset:offset + 4], "big")
            box_type = data[offset + 4:offset + 8]
            if box_size < 8: break
            payload = data[offset + 8: offset + box_size]

            if box_type == b"payl":
                text = payload.strip(b"\x00").strip()
                if text:
                    try:
                        text_str = text.decode('utf-8', errors='ignore').replace('\x00', '')
                        if text_str.strip(): result["text"].append(text_str)
                    except: pass
            elif box_type == b"sttg":
                try: result["settings"] = payload.decode('utf-8', errors='ignore').strip()
                except: pass
            elif box_type == b"idnt":
                try:
                    ident = payload.decode('utf-8', errors='ignore')
                    if '-->' in ident:
                        parts = ident.split('-->')
                        if len(parts) == 2:
                            result["start"] = parts[0].strip()
                            result["end"] = parts[1].strip()
                except: pass
            offset += box_size
        return result if result["text"] else None

    @staticmethod
    def _reconstruct_vtt_from_cues(cues: List[Dict]) -> bytes:
        vtt_lines = ["WEBVTT", ""]
        for i, cue in enumerate(cues):
            if not cue["start"] or not cue["end"]:
                start_sec = i * 4
                end_sec = start_sec + 4
                start = f"{start_sec // 3600:02d}:{(start_sec % 3600) // 60:02d}:{start_sec % 60:02d}.000"
                end = f"{end_sec // 3600:02d}:{(end_sec % 3600) // 60:02d}:{end_sec % 60:02d}.000"
            else:
                start, end = cue["start"], cue["end"]

            timestamp_line = f"{start} --> {end}"
            if cue["settings"]: timestamp_line += f" {cue['settings']}"
            vtt_lines.append(timestamp_line)

            for text in cue["text"]:
                text = re.sub(r'<c[^>]*>', '', text)
                text = re.sub(r'</c>', '', text)
                text = re.sub(r'<ruby>', '', text)
                text = re.sub(r'</ruby>', '', text)
                text = re.sub(r'<rt>', '', text)
                text = re.sub(r'</rt>', '', text)
                text = re.sub(r'<[0-9:]+>', '', text)
                lines = text.split('\n')
                for line in lines:
                    if line.strip(): vtt_lines.append(line.strip())
            vtt_lines.append("")

        return '\n'.join(vtt_lines).encode('utf-8')
