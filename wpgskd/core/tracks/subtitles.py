import os
import re
import io
import logging
import math
import datetime
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import UserList, deque
from typing import Optional, List, Dict, Any, Tuple
from io import BytesIO
from functools import partial
import html

import srt
from srt import Subtitle

try:
    import tinycss
    from langcodes import Language
except ImportError:
    tinycss = None
    Language = None

from wpgskd.vendor.pymp4.parser import MP4
from wpgskd.vendor.pymp4.util import BoxUtil

log = logging.getLogger("Subtitles")

class SubRipFile(UserList):
    def __init__(self, data: list[srt.Subtitle] | None = None):
        self.data: list[srt.Subtitle] = data or []

    @classmethod
    def from_string(cls, source: str):
        return cls(list(srt.parse(source, ignore_errors=True)))

    def clean_indexes(self):
        self.data = list(srt.sort_and_reindex(self.data))

    def offset(self, offset: datetime.timedelta):
        for line in self.data:
            line.start += offset
            line.end += offset

    def export(self, eol: str | None = None) -> str:
        return srt.compose(self.data, eol=eol)

    def save(self, path: Path, encoding: str = 'utf-8-sig', eol: str | None = None):
        with path.open(mode='wb') as fp:
            fp.write(srt.compose(self.data, eol=eol).encode(encoding))

    def __eq__(self, other):
        if not isinstance(other, SubRipFile):
            raise NotImplementedError
        return self.export(eol='\n') == other.export(eol='\n')

def timestamp_from_ms(duration: float | int) -> str:
    seconds, miliseconds = divmod(float(duration), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return "%02d:%02d:%02d.%03d" % (hours, minutes, seconds, miliseconds)

def ms_from_timestamp(timestamp: str) -> int:
    timestamp = re.sub(r'[;\.\,]', r':', timestamp.replace('T:', ''))
    hours, minutes, seconds, miliseconds = map(int, timestamp.split(':'))
    miliseconds += hours * 3600000
    miliseconds += minutes * 60000
    miliseconds += seconds * 1000
    return miliseconds

def timedelta_from_timestamp(timestamp: str) -> datetime.timedelta:
    return datetime.timedelta(seconds=ms_from_timestamp(timestamp) / 1000)

def timedelta_from_ms(duration: float | int) -> datetime.timedelta:
    return datetime.timedelta(seconds=duration / 1000)

def line_duration(line: Subtitle):
    return abs(line.end - line.start)

TAGS = r'[<{][/\\]?[a-z0-9.]+[}>]'
POSITION_TAGS = r'^{\\an[0-9]}'
FRONT_OPTIONAL_TAGS_WITH_HYPHEN = rf'^\s*({TAGS})?\s*(-)?\s*({TAGS})?\s*'
TIME_LOOKAHEAD = r'(?![0-9]{2})'

SPEAKER = rf'({FRONT_OPTIONAL_TAGS_WITH_HYPHEN})\s*(Mc[A-Z][a-zA-Z]+|[A-Z0-9\&\[\]\.#\' ]+\s*|[A-Z][a-z]+):{TIME_LOOKAHEAD} ?'
SPEAKER_PARENTHESES = rf'({FRONT_OPTIONAL_TAGS_WITH_HYPHEN})\s*(?:[A-Z0-9\&\[\]\.#\' ]+\s*|[A-Z][a-z]+)(?: \([a-zA-Z ]+\)): ?'

FRONT_NOTES = r'(?:♪+\s+)'
BACK_NOTES = r'(?:\s+♪+)'

DESCRIPTION_BRACKET = r'\[(?:[^\]]|\s)*\]'
DESCRIPTION_PARENTHESES = r'\((?:[^\)]|\s)*\)'
FULL_LINE_DESCIRPTION_BRACKET = rf'^-?\s*{FRONT_NOTES}?\[[^\]]+\]{BACK_NOTES}?$'
NEW_LINE_DESCRIPTION_BRACKET = rf'^(?:{TAGS})?-?\s*{FRONT_NOTES}?{DESCRIPTION_BRACKET}(?:{TAGS})?{BACK_NOTES}?$'
FRONT_DESCRIPTION_BRACKET = rf'^(?:{SPEAKER}|{SPEAKER_PARENTHESES})?({FRONT_OPTIONAL_TAGS_WITH_HYPHEN}){DESCRIPTION_BRACKET}:?'
END_DESCRIPTION_BRACKET = rf'\s*{DESCRIPTION_BRACKET}\s*$'
FULL_LINE_DESCIRPTION_PARENTHESES = rf'^-?\s*{FRONT_NOTES}?\([^\)]+\){BACK_NOTES}?$'
NEW_LINE_DESCRIPTION_PARENTHESES = rf'^(?:{TAGS})?-?\s*{FRONT_NOTES}?{DESCRIPTION_PARENTHESES}{BACK_NOTES}?(?:{TAGS})?$'
FRONT_DESCRIPTION_PARENTHESES = rf'^({FRONT_OPTIONAL_TAGS_WITH_HYPHEN})(?:{SPEAKER}|{SPEAKER_PARENTHESES})?{DESCRIPTION_PARENTHESES}:?'
END_DESCRIPTION_PARENTHESES = rf'\s*{DESCRIPTION_PARENTHESES}:?\s*$'
INLINE_DESCRIPTION = r'(?:<[a-z]+>)?[\[(][A-Z]+[)\]](?:</[a-z]+>)?'

class BaseConverter:
    def from_file(self, file: Path) -> SubRipFile:
        with file.open(mode='rb') as stream:
            return self.parse(stream)

    def from_string(self, data: str) -> SubRipFile:
        return self.parse(BytesIO(data.encode('utf-8')))

    def from_bytes(self, data: bytes) -> SubRipFile:
        return self.parse(BytesIO(data))

    def parse(self, stream) -> SubRipFile:
        raise NotImplementedError

class WebVTTConverter(BaseConverter):
    def parse(self, stream) -> SubRipFile:
        srt = SubRipFile()
        looking_for_text = False
        looking_for_style = False
        text = []
        position = None
        line_number = 1
        styles = {}
        current_style = []
        css_parser = tinycss.make_parser('page3') if tinycss else None

        for line in stream:
            line = line.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n').strip()
            if any(line.startswith(word) for word in ('WEBVTT', 'NOTE', '/*', 'X-TIMESTAMP-MAP')):
                continue

            if line == '':
                if looking_for_style and current_style and css_parser:
                    stylesheet = css_parser.parse_stylesheet('\n'.join(current_style))
                    for rule in stylesheet.rules:
                        ft = next((e for e in rule.selector if e.type == 'FUNCTION'), None)
                        if not ft: continue
                        name = next((t for t in ft.content if t.type == 'IDENT'), None)
                        if not name: continue
                        styles[name.value] = {}
                        for dec in rule.declarations:
                            styles[name.value][dec.name] = dec.value.as_css()
                    current_style = []
                    looking_for_style = False

                if not text:
                    continue

                srt[-1].content = '\n'.join(text)
                text = []
                looking_for_text = False

            elif 'STYLE' in line:
                looking_for_style = True
            elif looking_for_style:
                current_style.append(line)
            elif ' --> ' in line:
                parts = line.strip().split()
                position = self._get_position([p for p in parts[3:] if ':' in p])
                start, _, end, *_ = parts
                if start.count(':') == 1: start = f'00:{start}'
                if end.count(':') == 1: end = f'00:{end}'

                srt.append(Subtitle(index=line_number, start=timedelta_from_timestamp(start), end=timedelta_from_timestamp(end), content=''))
                looking_for_text = True
                line_number += 1
            elif looking_for_text:
                line = html.unescape(line)
                line = re.sub(r'<v\s+[^>]+>', '', line)
                if position is not None and position < 25:
                    line = '{\\an8}' + line
                    position = None
                text.append(line.strip())

        if text:
            srt[-1].content += '\n'.join(text)

        for line in srt:
            line.content = re.sub(r'<c.([a-zA-Z0-9]+)>([^<]+)<\/c>', 
                                  partial(self._replace_italics, styles=styles), line.content)
            line.content = re.sub(r'</?(?!/?i)[^>\s]+>', '', line.content)

        return srt

    @staticmethod
    def _get_position(cue_settings: list[str]) -> Optional[float]:
        if not cue_settings or cue_settings == ['None']: return None
        for key, val in (pos.split(':') for pos in cue_settings):
            if key == 'line' and (val := val.split(',')[0])[-1] == '%':
                return float(val[:-1])
        return None

    @staticmethod
    def _replace_italics(match: re.Match, styles: dict[str, dict[str, str]]) -> str:
        if (s := styles.get(match[1])) and s.get('font-style') == 'italic':
            return f'<i>{match[2]}</i>'
        return match[0]

class SMPTEConverter(BaseConverter):
    """DFXP/TTML/TTML2 subtitle converter"""
    def parse(self, stream) -> SubRipFile:
        data = stream.read().decode('utf-8-sig')
        if data.count('</tt>') == 1:
            return _SMPTEConverter(data).srt

        smpte_subs = [s + '</tt>' for s in data.strip().split('</tt>') if s]
        srt = SubRipFile([])
        for sub in smpte_subs:
            srt.extend(_SMPTEConverter(sub).srt)
        return srt

class _SMPTEConverter:
    def __init__(self, data: str):
        self.logger = logging.getLogger(__name__)
        
        data = re.sub(r'<\?xml[^>]*\?>', '', data)
        data = re.sub(r'\sxmlns(?::[a-zA-Z\-]+)?="[^"]*"', '', data)
        data = data.replace('ttp:', '').replace('tts:', '').replace('xml:', '')
        
        try:
            self.root = ET.fromstring(data)
            for elem in self.root.iter():
                if isinstance(elem.tag, str) and "}" in elem.tag:
                    elem.tag = elem.tag.split("}", 1)[1]
        except ET.ParseError as e:
            self.logger.error(f"TTML parse error: {e}")
            self.root = None

        self.srt = SubRipFile([])
        if self.root is None:
            return
            
        self.tickrate = int(self.root.get('tickRate', 0))
        self.frame_duration = 1
        if (rate := self.root.get('frameRate')) is not None:
            try:
                num, denom = map(int, self.root.get('frameRateMultiplier', '1 1').split())
                framerate = (int(rate) * num) / denom
                self.frame_duration = (1 / framerate) * 1000
            except ValueError:
                pass

        self.italics = {}
        self.an8 = {}
        self.all_span_italics = 'fontStyle="italic"' not in data

        self._parse_styles()
        self._convert()

    def _convert(self):
        p_elements = self.root.findall(".//p")
        if not p_elements:
            p_elements = [
                e for e in self.root.iter()
                if isinstance(e.tag, str) and e.tag.split("}")[-1] == "p"
            ]

        if not p_elements:
            self.logger.warning("TTML parse: No <p> elements found in document.")
            return

        for num, line in enumerate(p_elements, 1):
            line_text = ''
            begin = line.get('begin')
            end = line.get('end')
            if not begin or not end: continue

            try:
                if begin.endswith('t'): begin = self._convert_ticks(begin)
                elif begin.endswith('ms'): begin = timestamp_from_ms(begin[:-2])
                else: begin = self._parse_timestamp(begin)

                if end.endswith('t'): end = self._convert_ticks(end)
                elif end.endswith('ms'): end = timestamp_from_ms(end[:-2])
                else: end = self._parse_timestamp(end)
            except Exception as e:
                self.logger.warning(f"TTML parse: Failed to parse timestamp for line {num}: {e}")
                continue

            srt_line = Subtitle(index=num, start=timedelta_from_timestamp(begin), end=timedelta_from_timestamp(end), content='')
            line_text = self._parse_element(line)

            if self._is_italic(line) and line_text.strip():
                line_text = line_text.replace('<i>', '').replace('</i>', '')
                line_text = '<i>%s</i>' % line_text.strip()
            if self._is_an8(line) and line_text.strip():
                line_text = '{\\an8}%s' % line_text.strip()

            srt_line.content = line_text.strip().strip('\n')
            if srt_line.content:
                self.srt.append(srt_line)

    def _parse_styles(self):
        for style in self.root.findall('.//style'):
            sid = style.get('id')
            if sid: self.italics[sid] = self._is_italic(style)
        for region in self.root.findall('.//region'):
            rid = region.get('id')
            if rid: self.an8[rid] = self._is_an8(region)

    def _parse_element(self, element):
        element_text = ""
        if element.text:
            element_text += element.text

        for child in element:
            tag = child.tag.split("}")[-1] if isinstance(child.tag, str) else ""
            element_text += self._parse_element(child)

            if tag == "br":
                element_text += "\n"

            if child.tail:
                element_text += child.tail

        if self._is_italic(element) and element_text.strip():
            element_text = element_text.replace("<i>", "").replace("</i>", "")
            element_text = "<i>%s</i>" % element_text.strip()

        if self._is_an8(element) and element_text.strip():
            element_text = "{\\an8}%s" % element_text.strip()

        return element_text
        
    def _is_italic(self, element):
        if element is None: return False
        if element.get('fontStyle') == 'italic': return True
        style_id = element.get('style')
        if style_id and self.italics.get(style_id): return True
        tag = element.tag.split("}")[-1] if isinstance(element.tag, str) else ""

        if self.all_span_italics and tag == "span" and not element.attrib:
            return True
        return False

    def _is_an8(self, element):
        if element.get('displayAlign') == 'before': return True
        region_id = element.get('region')
        if region_id and self.an8.get(region_id): return True
        return False

    def _convert_ticks(self, ticks):
        ticks = int(ticks[:-1])
        offset = 1.0 / self.tickrate if self.tickrate else 0
        seconds = (offset * ticks) * 1000
        return timestamp_from_ms(seconds)

    def _parse_timestamp(self, timestamp):
        regex = r'([0-9]{2}):([0-9]{2}):([0-9]{2})[:\.,]?([0-9]{0,3})?'
        parsed = re.search(regex, timestamp)
        if not parsed: return "00:00:00.000"
        hours, minutes, seconds = int(parsed.group(1)), int(parsed.group(2)), int(parsed.group(3))
        miliseconds = 0
        if fraction := parsed.group(4):
            if timestamp[-len(fraction)-1] == ':':
                miliseconds = int(self.frame_duration * int(fraction))
            else:
                miliseconds = int(float(f"0.{fraction}") * 1000)
        return "%02d:%02d:%02d.%03d" % (hours, minutes, seconds, miliseconds)

class SAMIConverter(BaseConverter):
    def parse(self, stream) -> SubRipFile:
        return _SAMIConverter(stream.read().decode('utf-8-sig')).srt

class _SAMIConverter(html.parser.HTMLParser):
    def __init__(self, subtitle):
        super().__init__()
        self.lines = []
        self.tags = []
        self.srt = SubRipFile([])
        self.line_list = []
        self.feed(self._correct_tags(subtitle))
        self._convert()

    def handle_starttag(self, tag, attrs_org):
        attrs = {k: v for k, v in attrs_org}
        if tag == 'sync':
            self.lines.append({'text': '', **attrs})
        self.tags.append({'name': tag, 'attrs': attrs})

    def handle_data(self, data):
        if not self.tags: return
        last_tag = self.tags[-1]['name']
        if last_tag == 'br': self.lines[-1]['text'] += '\n'
        elif last_tag == 'i' and data.strip(): self.lines[-1]['text'] += f'<i>{data}</i>'
        elif last_tag != 'sync' and self.lines: self.lines[-1]['text'] += data

    def _convert(self):
        for line in self.lines:
            if not line.get('text', '').strip():
                end_time = float(line['start'])
                if self.line_list: self.line_list[-1]['end'] = end_time
                continue
            if not line.get('end'): line['end'] = float(line['start']) + 4000
            self.line_list.append({'start': float(line['start']), 'end': float(line['end']), 'content': line['text'].strip()})

        for num, line in enumerate(self.line_list):
            self.srt.append(Subtitle(index=num, start=timedelta_from_ms(line['start']), end=timedelta_from_ms(line['end']), content=line['content']))

    @staticmethod
    def _correct_tags(data):
        data = data.replace('<i/>', '<i>').replace(';>', '>').replace('<br>', '\n').replace('<br/>', '\n').replace('<br >', '\n')
        return data

class WVTTConverter(BaseConverter):
    def parse(self, stream) -> SubRipFile:
        sample_durations = deque()
        vtt_lines = []
        timescale = 0

        for box in MP4.parse(stream.read()):
            if box.type == b'moov':
                for mdhd in BoxUtil.find(box, b'mdhd'): timescale = mdhd.timescale; break
                for stsd in BoxUtil.find(box, b'stsd'):
                    wvtt = stsd.entries[0]
                    header = [box.config for box in wvtt.children if box.type == b'vttC'][0]
                    vtt_lines.append(f'{header}\n\n')
                    break
            if box.type == b'moof':
                start_offset = 0
                duration = 0
                for tfdt in BoxUtil.find(box, b'tfdt'): start_offset = tfdt.baseMediaDecodeTime; break
                for trun in BoxUtil.find(box, b'trun'):
                    for sample in trun.sample_info:
                        start_offset += sample.sample_composition_time_offsets or 0
                        duration += sample.sample_duration or 0
                        sample_durations.append({'start_ms': (start_offset / timescale) * 1000, 'end_ms': ((start_offset + duration) / timescale) * 1000})
            if box.type == b'mdat':
                for vtt_box in MP4.parse(box.data):
                    settings = next((box.settings for box in BoxUtil.find(vtt_box, b'sttg')), None)
                    cue_text = next((box.cue_text for box in BoxUtil.find(vtt_box, b'payl')), None)
                    try: sample_duration = sample_durations.popleft()
                    except IndexError: continue
                    start_ms = end_ms = sample_duration['end_ms']
                    end_ms = sample_duration['end_ms']
                    if vtt_box.type == b'vtte': continue
                    vtt_lines.append(f'{timestamp_from_ms(start_ms)} --> {timestamp_from_ms(end_ms)} {settings}\n{cue_text}\n\n')

        return WebVTTConverter().from_string(''.join(vtt_lines))

class ISMTConverter(BaseConverter):
    def parse(self, stream) -> SubRipFile:
        srt = SubRipFile([])
        for box in MP4.parse(stream.read()):
            if box.type == b'mdat':
                new = SMPTEConverter().from_bytes(box.data)
                if srt and new and srt[-1].start > new[0].start: new.offset(srt[-1].end)
                srt.extend(new)
        return srt

class BilibiliJSONConverter(BaseConverter):
    def parse(self, stream) -> SubRipFile:
        import json
        json_data = json.load(stream)
        srt = SubRipFile()
        for i, line in enumerate(json_data['body']):
            if line['location'] != 2:
                line['content'] = ('{\\an%s}' % line['location']) + line['content']
            srt.append(Subtitle(index=i, start=datetime.timedelta(seconds=line['from']), end=datetime.timedelta(seconds=line['to']), content=line['content']))
        return srt

class LegacyTTMLConverter:
    TOP_MARKER = '{\\an8}'

    def __init__(self, shift=0, source_fps=23.976, scale_factor=1, subtitle_language=None):
        self.shift = shift
        self.source_fps = source_fps
        self.scale_factor = scale_factor
        self.subtitle_language = subtitle_language
        self.entries = []
        self._tc = self._init_timestamp_converter()

    class _TimestampConverter:
        def __init__(self, frame_rate=23.976, tick_rate=1):
            self.frame_rate = frame_rate
            self.tick_rate = tick_rate

        def timeexpr_to_ms(self, time_expr):
            delims = ''.join([i for i in time_expr if not i.isdigit()])
            fn_map = {
                '::': self.frame_timestamp_to_ms, ':::': self.frame_timestamp_to_ms,
                '::.': self.fraction_timestamp_to_ms,
                'h': self.offset_hours_to_ms, 'm': self.offset_minutes_to_ms,
                's': self.offset_seconds_to_ms, 'ms': self.offset_ms_to_ms,
                't': self.offset_ticks_to_ms, 'f': self.offset_frames_to_ms
            }
            return fn_map.get(delims, lambda x: 0)(time_expr)

        def _hhmmss_to_ms(self, hh, mm, ss): return hh * 3600 * 1000 + mm * 60 * 1000 + ss * 1000
        def subrip_to_ms(self, ts):
            hh, mm, ss, ms = re.split(r'[:,]', ts)
            return int(int(hh) * 3.6e6 + int(mm) * 60000 + int(ss) * 1000 + int(ms))
        def ms_to_subrip(self, ms):
            hh = int(ms / 3.6e6); mm = int((ms % 3.6e6) / 60000); ss = int((ms % 60000) / 1000); ms = int(ms % 1000)
            return '{:02d}:{:02d}:{:02d},{:03d}'.format(hh, mm, ss, ms)
        def ms_to_ssa(self, ms):
            hh = int(ms / 3.6e6); mm = int((ms % 3.6e6) / 60000); ss = int((ms % 60000) / 1000); ms = int(ms % 1000)
            return '{:01d}:{:02d}:{:02d}.{:02d}'.format(hh, mm, ss, int(ms / 10))
        def frames_to_ms(self, frames): return int(int(frames) * (1000 / self.frame_rate))
        def offset_frames_to_ms(self, time): return int(int(float(time[:-1])) * (1000 / self.frame_rate))
        def offset_ticks_to_ms(self, time): return (1.0 / self.tick_rate * int(time[:-1])) * 1000
        def offset_hours_to_ms(self, time): return int(3.6e6 * float(time[:-1]))
        def offset_minutes_to_ms(self, time): return int(60 * 1000 * float(time[:-1]))
        def offset_seconds_to_ms(self, time): return int(1000 * float(time[:-1]))
        def offset_ms_to_ms(self, time): return int(time[:-2])
        def fraction_timestamp_to_ms(self, ts):
            hh, mm, ss, fraction = re.split(r'[:.]', ts)
            return self._hhmmss_to_ms(int(hh), int(mm), int(ss)) + int(fraction[:3])
        def frame_timestamp_to_ms(self, ts):
            hh, mm, ss, frames = [int(i) for i in ts.split('.')[0].split(':')]
            return self._hhmmss_to_ms(hh, mm, ss) + self.frames_to_ms(frames)

    def _init_timestamp_converter(self):
        return self._TimestampConverter(self.source_fps)

    def parse_ttml_from_string(self, doc: str):
        try:
            from defusedxml import minidom
        except ImportError:
            from xml.dom import minidom

        del self.entries[:]
        ttml_dom = minidom.parseString(doc.encode('utf-8'))
        tt_element = ttml_dom.getElementsByTagNameNS('*', 'tt')[0]
        
        if (ttp_val := getattr(tt_element.attributes.get('ttp:frameRate'), 'value', None)):
            self._tc.frame_rate = float(ttp_val)
        if (ttp_val := getattr(tt_element.attributes.get('ttp:tickRate'), 'value', None)):
            self._tc.tick_rate = int(ttp_val)

        lines = [i for i in ttml_dom.getElementsByTagNameNS('*', 'p') if 'begin' in i.attributes.keys()]
        for p in lines:
            ms_begin = self._tc.timeexpr_to_ms(p.attributes['begin'].value)
            ms_end = self._tc.timeexpr_to_ms(p.attributes['end'].value)
            dialogue = self._extract_dialogue(p.childNodes)
            position = 'top' if p.getAttribute('region') in self._get_top_regions(ttml_dom) else 'bottom'
            self.entries.append({'ms_begin': ms_begin, 'ms_end': ms_end, 'text': dialogue, 'position': position})
        
        if self.scale_factor != 1:
            for e in self.entries: e['ms_begin'] *= self.scale_factor; e['ms_end'] *= self.scale_factor
        if self.shift:
            for e in self.entries: e['ms_begin'] += self.shift; e['ms_end'] += self.shift

    @staticmethod
    def _get_top_regions(ttml_dom):
        top_regions = []
        for region in ttml_dom.getElementsByTagName('region'):
            if region.getAttribute('tts:displayAlign') == 'before':
                if rid := region.getAttribute('xml:id'): top_regions.append(rid)
        return top_regions

    def _extract_dialogue(self, nodes, styles=[]):
        dialogue = []
        for node in nodes:
            if node.nodeType == node.TEXT_NODE:
                text = re.sub(r'^\s{4,}', '', node.nodeValue.replace('\n', ''))
                fmt = '{ot}{f}{et}'.format(et='</i>', ot='<i>', f='{}')
                for style in styles: dialogue.append(fmt.format(text))
            elif node.localName == 'br': dialogue.append('\n')
            elif node.localName == 'span':
                if node.getAttribute('style') == 'italic' or node.parentNode.getAttribute('style') == 'AmazonDefaultStyle':
                    dialogue += self._extract_dialogue(node.childNodes, ['i'])
                else:
                    dialogue += self._extract_dialogue(node.childNodes, [])
        return ''.join(dialogue)

    def generate_srt(self) -> str:
        res = ''
        for i, e in enumerate(self.entries, 1):
            text = e['text'].replace("\n", "\r\n")
            if e['position'] == 'top': text = self.TOP_MARKER + text
            res += '{}\r\n{} --> {}\r\n{}\r\n\r\n'.format(i, self._tc.ms_to_subrip(e['ms_begin']), self._tc.ms_to_subrip(e['ms_end']), text)
        return res

    def generate_ssa(self) -> str:
        res = "[Script Info]\r\nScriptType: v4.00+\r\nPlayResX: 1280\r\nPlayResY: 720\r\n\r\n[V4+ Styles]\r\nFormat: Name,Fontname,Fontsize,PrimaryColour,BackColour,Bold,Italic,Alignment\r\nStyle: Default,Arial,50,&H00EEEEEE,&H40000000,0,0,2\r\n\r\n[Events]\r\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\r\n"
        for e in self.entries:
            text = e['text']
            text = re.sub(r'<i.*?>', '{\\\\i1}', text); text = re.sub(r'</i>', '{\\\\i0}', text)
            text = text.replace('\n', '\\\\N')
            if e['position'] == 'top': text = self.TOP_MARKER + text
            res += 'Dialogue: 0,{},{},Default,,0,0,0,,{}\r\n'.format(self._tc.ms_to_ssa(e['ms_begin']), self._tc.ms_to_ssa(e['ms_end']), text)
        return res

class BaseProcessor:
    def from_srt(self, srt: SubRipFile, language: str | None = None) -> Tuple[SubRipFile, bool]:
        return self.process(srt, language)
    def from_file(self, file: Path, language: str | None = None) -> Tuple[SubRipFile, bool]:
        with file.open(mode='r', encoding='utf-8') as stream: return self.from_string(stream.read(), language)
    def from_string(self, data: str, language: str | None = None) -> Tuple[SubRipFile, bool]:
        return self.process(SubRipFile.from_string(data), language)
    def process(self, srt: SubRipFile, language: str | None = None) -> Tuple[SubRipFile, bool]:
        raise NotImplementedError

class RTLFixer(BaseProcessor):
    RTL_LANGUAGES = ('ar', 'fa', 'he', 'ps', 'syc', 'ug', 'ur')
    RTL_CHAR = '\u202b'
    def process(self, srt, language=None):
        corrected = self._correct_subtitles(srt)
        return srt, corrected != srt
    def _correct_subtitles(self, srt):
        for line in srt:
            line.content = RTL_CHAR + line.content.replace("\n", f"\n{RTL_CHAR}")
        return srt

class CommonIssuesFixer(BaseProcessor):
    remove_gaps = True
    def process(self, srt, language=None):
        fixed = self._fix_time_codes(srt)
        corrected = self._correct_subtitles(fixed)
        if language and Language and Language.get(language).language in RTLFixer.RTL_LANGUAGES:
            corrected, _ = RTLFixer().process(corrected, language=language)
        return corrected, corrected != srt

    def _correct_subtitles(self, srt: SubRipFile) -> SubRipFile:
        def _fix_line(line):
            line = re.sub(r' {2,}', ' ', line)
            line = unicodedata.normalize('NFKC', line)
            line = line.replace(r'â™ª', '♪').replace(r'‐', r'-').replace(r'♫', r'♪')
            line = re.sub(r'^((?:{\\an8})?(?:<i>)?)(- ?)?[#\*]{1,}(?=\s+)', r'\1\2♪', line, flags=re.M)
            line = re.sub(r'(\{\\an[0-9]\}){1,}', r'{\\an8}', line)
            line = re.sub(r'</?(?!i>)[a-z]+>', '', line)
            line = re.sub(r'(<[a-z]>) {1,}', r'\1', line)
            line = re.sub(r'(<[a-z]>)\n', r'\n\1', line)
            line = re.sub(r'\n(</[a-z]>)', r'\1\n', line)
            line = re.sub(r"^(<i>|\{\\an8\})?-+(?='?[\w\"\[\(\<\{\.\$♪])", r"\1- ", line, flags=re.M)
            line = re.sub(r'(.*)([^\.\sA-Z][!\.;:?])(?<!(?:Mr|Ms)\.)(?<!Mrs\.)([A-Z][^.])', r'- \1\2\n- \3', line)
            return line.strip()

        for line in srt:
            for _ in range(2):
                line.content = html.unescape(line.content)
            for _ in range(2):
                line.content = _fix_line(line.content).strip()
                line.content = line.content.strip('\n')

        combined = self._combine_timecodes(srt)
        return self._remove_gaps(combined) if self.remove_gaps else combined

    def _combine_timecodes(self, srt: SubRipFile) -> SubRipFile:
        subs_copy = SubRipFile([])
        for line in srt:
            if not subs_copy: subs_copy.append(line); continue
            if line_duration(subs_copy[-1]) == line_duration(line) and subs_copy[-1].start == line.start and subs_copy[-1].end == line.end:
                if subs_copy[-1].content != line.content: subs_copy[-1].content += '\n' + line.content
            elif 0 < round((line.start - subs_copy[-1].end).total_seconds() * 1000) <= 85 and line.content.startswith(subs_copy[-1].content) and self.remove_gaps:
                subs_copy[-1].end = line.end; subs_copy[-1].content = line.content
            else:
                subs_copy.append(line)
        subs_copy.clean_indexes()
        return subs_copy or srt

    def _remove_gaps(self, srt: SubRipFile) -> SubRipFile:
        subs_copy = SubRipFile([])
        for line in srt:
            if not subs_copy: subs_copy.append(line); continue
            elif 1 < round((line.start - subs_copy[-1].end).total_seconds() * 1000) <= 85:
                line.start = subs_copy[-1].end
                subs_copy[-1].end -= datetime.timedelta(milliseconds=1)
                subs_copy.append(line)
            else: subs_copy.append(line)
        subs_copy.clean_indexes()
        return subs_copy or srt

    @staticmethod
    def _fix_time_codes(srt: SubRipFile) -> SubRipFile:
        offset = 0
        for line in srt:
            hours, _ = divmod(line.start.seconds, 3600)
            hours += line.start.days * 24
            if not offset and hours > 23: offset = hours
            if offset:
                line.start -= datetime.timedelta(hours=offset); line.end -= datetime.timedelta(hours=offset)
        return srt

class SDHStripper(BaseProcessor):
    def process(self, srt, language=None):
        stripped = [line for line in srt]
        stripped = self._clean_full_line_descriptions(stripped)
        stripped = self._clean_new_line_descriptions(stripped)
        stripped = self._clean_inline_descriptions(stripped)
        stripped = self._clean_speaker_names(stripped)
        stripped = self._strip_notes(stripped)
        stripped = self._remove_extra_hyphens(stripped)
        stripped = SubRipFile([line for line in stripped if line.content])
        stripped.clean_indexes()
        return stripped, stripped != srt

    def _clean_full_line_descriptions(self, srt):
        for line in srt:
            text = re.sub(TAGS, r'', line.content)
            for regex in (FULL_LINE_DESCIRPTION_BRACKET, FULL_LINE_DESCIRPTION_PARENTHESES):
                text = re.sub(regex, r'', text, flags=re.S).strip()
            if text: yield line

    def _clean_new_line_descriptions(self, srt):
        for line in srt:
            position = re.match(POSITION_TAGS, line.content.strip())
            for regex in (NEW_LINE_DESCRIPTION_BRACKET, NEW_LINE_DESCRIPTION_PARENTHESES):
                line.content = re.sub(regex, r'', line.content, flags=re.M).strip()
            if position and position[0] not in line.content: line.content = position[0] + line.content
            yield line

    def _clean_inline_descriptions(self, srt):
        for line in srt:
            line.content = re.sub(FRONT_DESCRIPTION_BRACKET, r'\10', line.content, flags=re.M)
            line.content = re.sub(FRONT_DESCRIPTION_PARENTHESES, r'\1', line.content, flags=re.M)
            for regex in (END_DESCRIPTION_BRACKET, END_DESCRIPTION_PARENTHESES, INLINE_DESCRIPTION):
                line.content = re.sub(regex, r'', line.content, flags=re.M).strip()
            yield line

    def _clean_speaker_names(self, srt):
        for line in srt:
            for regex in (SPEAKER_PARENTHESES, SPEAKER):
                line.content = re.sub(regex, r'\2\3', line.content, flags=re.M).strip()
            yield line

    def _strip_notes(self, srt):
        for line in srt:
            if not re.match(r'^♪+$', re.sub(r'\s*', r'', re.sub(TAGS, r'', line.content).strip())): yield line

    def _remove_extra_hyphens(self, srt):
        for line in srt:
            splits = len(re.findall(r'^(<i>|\{\\an8\})?-\s*', line.content, flags=re.M))
            if splits == 1: line.content = re.sub(r'^(<i>|\{\\an8\})?-\s*', r'\1', line.content.strip())
            yield line

class SubtitleProcessor:
    _SDH_PATTERNS = [
        r'\[[^\]]*\]', r'\([^\)]*\)', r'\{[^\}]*\}', r'<[^>]*>', r'♪[^♪]*♪', r'[\*_][^\*_]+[\*_]',
    ]

    @staticmethod
    def extract_mdat_text(data: bytes, codec: str) -> bytes:
        codec_lower = codec.lower()
        plain_text_codecs = {"vtt", "webvtt", "webvtt-lssdh-ios8", "ttml", "ttml2", "dfxp", "smpte"}
        if codec_lower in plain_text_codecs: return data

        collected = []
        try:
            offset = 0
            while offset + 8 <= len(data):
                box_size = int.from_bytes(data[offset:offset + 4], "big")
                box_type = data[offset + 4:offset + 8]
                if box_size < 8: break
                if box_type == b"mdat":
                    payload = data[offset + 8: offset + box_size]
                    if codec_lower in ["wvtt", "stpp"]:
                        cues_data = SubtitleProcessor._extract_wvtt_text_from_mdat(payload)
                        if cues_data and len(cues_data) > 10: collected.append(cues_data)
                    else:
                        clean = payload.lstrip(b"\x00").strip()
                        if clean and len(clean) > 10: collected.append(clean)
                offset += box_size
        except Exception as e:
            log.debug(f"Error extracting MDAT: {e}")

        if not collected: return data
        result = b"\n".join(collected)
        if b"WEBVTT" not in result and b"-->" in result:
            lines = result.split(b'\n')
            for i, line in enumerate(lines):
                if b"-->" in line: lines.insert(0, b"WEBVTT"); lines.insert(1, b""); result = b'\n'.join(lines); break
        return result.replace(b'\x00', b'')

    @staticmethod
    def convert_subtitle_to_srt(save_path: str, strip_sdh: bool = True) -> Optional[str]:
        with open(save_path, "rb") as fd: raw = fd.read()
        if len(raw) < 10:
            log.warning(f" - Subtitle file too small ({len(raw)} bytes), skipping conversion")
            return save_path

        stripped_raw = raw.lstrip()
        is_ttml = stripped_raw.startswith(b'<?xml') or stripped_raw.startswith(b'<tt')
        is_vtt = stripped_raw.startswith(b'WEBVTT')
        
        codec = ""
        if is_ttml:
            codec = "ttml"
        elif is_vtt:
            codec = "vtt"
        elif save_path.endswith(".vtt") or save_path.endswith(".webvtt"):
            codec = "vtt"
        elif save_path.endswith(".ttml") or save_path.endswith(".dfxp"):
            codec = "ttml"
        elif save_path.endswith(".ass") or save_path.endswith(".ssa"):
            codec = "ass"
        else:
            codec = "unknown"

        if codec.lower() in ["ass", "ssa"]:
            log.info(f" + ASS/SSA subtitle kept in original format")
            return save_path

        srt_obj = None
        if codec.lower() in ["wvtt", "stpp"]:
            log.info(f" + Extracting text from {codec.upper()} container...")
            extracted = SubtitleProcessor.extract_mdat_text(raw, codec)
            if extracted and len(extracted) > 10:
                try:
                    vtt_content = extracted.decode('utf-8', errors='ignore')
                    srt_obj = WebVTTConverter().from_string(vtt_content)
                except Exception as e:
                    log.warning(f" - Failed to decode extracted content: {e}")

        elif codec.lower() in ["vtt", "webvtt"]:
            try:
                if raw.startswith(b'\x00\x00\x00') or (len(raw) > 4 and raw[:4] == b'mdat'):
                    extracted = SubtitleProcessor.extract_mdat_text(raw, "vtt")
                    vtt_content = extracted.decode('utf-8', errors='ignore')
                else:
                    vtt_content = raw.decode('utf-8', errors='ignore')
                srt_obj = WebVTTConverter().from_string(vtt_content)
            except Exception as e:
                log.warning(f" - VTT conversion failed: {e}")

        elif codec.lower() in ["ttml", "dfxp", "smpte"]:
            try:
                srt_obj = SMPTEConverter().from_bytes(raw)
            except Exception as e:
                log.warning(f" - TTML conversion failed: {e}")

        if srt_obj is not None:
            if len(srt_obj) == 0:
                log.warning(f" - Subtitle parsed but empty, skipping conversion")
                return save_path
            try:
                fixer = CommonIssuesFixer()
                fixer.remove_gaps = True
                srt_obj, _ = fixer.from_srt(srt_obj)
                if strip_sdh:
                    stripper = SDHStripper()
                    srt_obj, status = stripper.from_srt(srt_obj)
                    if status:
                        srt_obj, _ = fixer.from_srt(srt_obj)
                
                srt_path = os.path.splitext(save_path)[0] + '.srt'
                srt_obj.save(Path(srt_path))
                if os.path.exists(save_path) and save_path != srt_path:
                    try: os.unlink(save_path)
                    except: pass
                log.info(f" + Subtitle converted to SRT: {os.path.basename(srt_path)}")
                return srt_path
            except Exception as e:
                log.warning(f" - Post-processing subtitle failed: {e}")
        
        return save_path

    @staticmethod
    def convert_ttml_to_ssa(ttml_data: str, language: str = None) -> str:
        converter = LegacyTTMLConverter(subtitle_language=language)
        converter.parse_ttml_from_string(ttml_data)
        return converter.generate_ssa()

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
                start_sec = i * 4; end_sec = start_sec + 4
                start = f"{start_sec // 3600:02d}:{(start_sec % 3600) // 60:02d}:{start_sec % 60:02d}.000"
                end = f"{end_sec // 3600:02d}:{(end_sec % 3600) // 60:02d}:{end_sec % 60:02d}.000"
            else:
                start, end = cue["start"], cue["end"]

            timestamp_line = f"{start} --> {end}"
            if cue["settings"]: timestamp_line += f" {cue['settings']}"
            vtt_lines.append(timestamp_line)

            for text in cue["text"]:
                text = re.sub(r'<c[^>]*>', '', text); text = re.sub(r'</c>', '', text)
                text = re.sub(r'<ruby>', '', text); text = re.sub(r'</ruby>', '', text)
                text = re.sub(r'<rt>', '', text); text = re.sub(r'</rt>', '', text)
                text = re.sub(r'<[0-9:]+>', '', text)
                lines = text.split('\n')
                for line in lines:
                    if line.strip(): vtt_lines.append(line.strip())
            vtt_lines.append("")

        return '\n'.join(vtt_lines).encode('utf-8')