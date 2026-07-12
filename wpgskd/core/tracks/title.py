import re
import logging
from enum import Enum
from typing import Optional, List, Any, Iterator  
from wpgskd.core.tracks.tracks import Tracks

log = logging.getLogger("Title")

class Title:
    class Types(Enum):
        MOVIE = 1
        TV = 2
        SONG = 3

    def __init__(self, id_: Any, type_: Types, name: Optional[str] = None, year: Optional[int] = None,
                 season: Optional[int] = None, episode: Optional[Any] = None, episode_name: Optional[str] = None,
                 original_lang: Optional[str] = None, source: Optional[str] = None, 
                 service_data: Optional[dict] = None, filename: Optional[str] = None):
        
        self.id = id_
        self.type = type_
        self.name = name or ""
        self.year = year or 0
        self.season = season or 0
        self.episode = episode or 0
        self.episode_name = episode_name
        self.original_lang = original_lang or "en"
        self.source = source
        self.service_data = service_data or {}
        self.tracks = Tracks()
        self.filename = filename or self._generate_filename()
        
        self.manifest_url: Optional[str] = None
        self.dash_manifest_url: Optional[str] = None
        self.cbr_manifest_url: Optional[str] = None
        self.cvbr_manifest_url: Optional[str] = None

    def __eq__(self, other):
        return isinstance(other, Title) and self.id == other.id

    def __str__(self):
        if self.type == Title.Types.MOVIE:
            return f"{self.name} ({self.year})" if self.year else self.name
        elif self.type == Title.Types.TV:
            ep_str = f"E{int(self.episode):02}" if isinstance(self.episode, int) else f"E{self.episode}"
            s_str = f"S{int(self.season):02}" if isinstance(self.season, int) else f"S{self.season}"
            return f"{self.name} {s_str}{ep_str}"
        return self.name

    def _generate_filename(self) -> str:
        if self.type == Title.Types.MOVIE:
            base = self.name
            if self.year: base += f" ({self.year})"
        elif self.type == Title.Types.TV:
            s_str = f"S{int(self.season):02}" if isinstance(self.season, int) else f"S{self.season}"
            base = f"{self.name} {s_str}"
        else:
            base = self.name
            
        base = re.sub(r'[\\/:*?"<>|]', "", base)
        return base.replace(" ", ".")

    def parse_filename(self, media_info=None, folder: bool = False) -> str:
        if folder and self.type == Title.Types.TV:
            s_str = f"S{int(self.season):02}" if isinstance(self.season, int) else f"S{self.season}"
            return f"{self.name} {s_str}"
        return self.filename


class Titles(list):
    def __init__(self, *args, **kwargs):
        items = args[0] if args else []
        if items and not isinstance(items, (list, tuple, set)):
            items = [items]
        super().__init__(items, **kwargs)
        self.title_name = self[0].name if self else None

    def order(self):
        self.sort(key=lambda t: int(getattr(t, 'year', 0) or 0))
        self.sort(key=lambda t: getattr(t, 'episode', 0) or 0)
        self.sort(key=lambda t: int(getattr(t, 'season', 0) or 0))
        return self

    def with_wanted(self, wanted: Optional[List[str]]) -> Iterator[Title]:
        for title in self:
            if not wanted or (title.type == Title.Types.TV and f"{title.season}x{title.episode}" in wanted):
                yield title

    def print(self):
        if any(x.type == Title.Types.TV for x in self):
            season_counts = {}
            for x in self:
                s = getattr(x, 'season', 0)
                season_counts[s] = season_counts.get(s, 0) + 1
            info = ", ".join(f"S{s} ({c} eps)" for s, c in sorted(season_counts.items()))
            log.info(f"Title: {self.title_name} | By Season: {info}")
        else:
            log.info(f"Title: {self.title_name}")