from __future__ import annotations

import re
import click
import requests
import datetime as dt
from langcodes import Language
from m3u8 import loads as m3u8loads
from urllib.parse import urljoin
from time import time

from wpgskd.core.tracks import Title, Tracks, AudioTrack, TextTrack, MenuTrack, VideoTrack, Track
from wpgskd.servicookies.BaseService import BaseService

class TVer(BaseService):
    """
    Service code for TVer streaming service (https://tver.jp/).
    基于 yt-dlp 逻辑，动态获取 Streaks API Key，完美绕过 403。
    """

    ALIASES = ["TVer"]
    TITLE_RE = r"^(?:https?://tver\.jp/)?(?:episodes/|series/)?(?P<id>[a-zA-Z0-9]{8,})"
    GEOFENCE = []
    APP_VER = "6.32.0"

    @staticmethod
    @click.command(name="TVer", short_help="https://tver.jp")
    @click.argument("title", type=str, required=False)
    @click.pass_context
    def cli(ctx, **kwargs):
        return TVer(ctx, **kwargs)

    def __init__(self, ctx, title: str):
        super().__init__(ctx=ctx)
        self.parse_title(ctx=ctx, title=title)
        self.platform_uid: str = None
        self.platform_token: str = None
        self.original_url = title
        self._video_info_cache = {}
        self._streaks_api_info = {}
        self.configure()

    def configure(self) -> None:
        self.log.info(" + Authenticating with TVer platform (Web)...")
        self.session.headers.update({
            "Origin": "https://tver.jp",
            "Referer": "https://tver.jp/",
            "x-tver-platform-type": "web"
        })
        try:
            # 1. 获取 Web Token
            auth_req = self.session.post(
                "https://platform-api.tver.jp/v2/api/platform_users/browser/create",
                data={"device_type": "pc"}
            )
            auth_req.raise_for_status()
            result = auth_req.json().get("result", {})
            self.platform_uid = result.get("platform_uid")
            self.platform_token = result.get("platform_token")
            if not self.platform_uid or not self.platform_token:
                raise ValueError("Missing tokens")
            
            # 2. 获取动态 Streaks API Key 映射表 (关键！)
            self.log.info(" + Fetching Streaks API keys...")
            streaks_req = self.session.get("https://player.tver.jp/player/streaks_info_v2.json")
            streaks_req.raise_for_status()
            self._streaks_api_info = streaks_req.json()
            
        except Exception as e:
            self.log.exit(f" - Failed to initialize: {e}")

    def _get_streaks_api_key(self, project_id: str) -> str:
        """根据项目ID和当前月份动态获取对应的 Streaks API Key"""
        try:
            # 计算当前日本时间对应的 key index (1-6)
            jst_now = dt.datetime.fromtimestamp(time(), dt.timezone(dt.timedelta(hours=9)))
            key_idx = jst_now.month % 6 or 6
            key_name = f"key0{key_idx}"
            
            project_info = self._streaks_api_info.get(project_id, {})
            api_keys = project_info.get("api_key", {})
            api_key = api_keys.get(key_name)
            
            if not api_key:
                self.log.warn(f" + No Streaks API key found for {project_id}/{key_name}, using fallback.")
                # Fallback 尝试 key01
                api_key = api_keys.get("key01") or list(api_keys.values())[0]
                
            return api_key
        except (KeyError, IndexError):
            self.log.exit(f" - Invalid Streaks API info structure for project {project_id}")
            return None

    def _get_video_info(self, episode_id: str, version: int = 5) -> dict:
        if episode_id not in self._video_info_cache:
            info_url = f"https://statics.tver.jp/content/episode/{episode_id}.json"
            req = self.session.get(info_url, params={'v': version})
            req.raise_for_status()
            self._video_info_cache[episode_id] = req.json()
        return self._video_info_cache[episode_id]

    def _parse_codecs(self, codecs_str: str) -> tuple[str, str]:
        v_codec, a_codec = "h264", "aac"
        if not codecs_str: return v_codec, a_codec
        for c in codecs_str.split(","):
            c = c.strip().strip('"')
            if c.startswith("avc1") or c.startswith("avc3"): v_codec = "h264"
            elif c.startswith("hvc1") or c.startswith("hev1"): v_codec = "h265"
            elif c.startswith("av01"): v_codec = "av1"
            elif c.startswith("mp4a"): a_codec = "aac"
            elif c.startswith("ec-3"): a_codec = "eac3"
        return v_codec, a_codec

    def _map_season_number(self, season_title: str, fallback_idx: int) -> int:
        """
        根据 TVer 的 season title 映射逻辑季数。
        - 含有 "予告" -> S0 (特典/预告)
        - 含有 "本編" -> S1 (正片)
        - 含有 "解説放送版" -> S2 (解说版)
        - 其他 -> 按顺序递增 (S3, S4...)
        """
        if "予告" in season_title or "ダイジェスト" in season_title:
            return 0
        if "本編" in season_title:
            return 1
        if "解説放送版" in season_title:
            return 2
        
        # 兜底：如果没有匹配到关键词，从3开始递增
        return fallback_idx + 3

    def _parse_episode_title(self, title: str) -> tuple[int, str | None]:
        """
        解析剧集标题，提取集数和副标题。
        返回: (集数, 副标题)
        """
        if not title:
            return 0, None

        # Pattern 1: 第X話 「副标题」 or 第X期 「副标题」
        match = re.match(r'第(\d+)[話期]\s*「(.+)」', title)
        if match:
            return int(match.group(1)), match.group(2).strip()

        # Pattern 2: 第X話 副标题
        match = re.match(r'第(\d+)[話期]\s*(.*)', title)
        if match:
            return int(match.group(1)), match.group(2).strip() or None

        # Pattern 3: #X 「副标题」 or ＃X 「副标题」
        match = re.match(r'[#＃](\d+)\s*「(.+)」', title)
        if match:
            return int(match.group(1)), match.group(2).strip()

        # Pattern 4: #X 副标题
        match = re.match(r'[#＃](\d+)\s*(.*)', title)
        if match:
            return int(match.group(1)), match.group(2).strip() or None

        # 如果都不匹配，可能是电影/特别篇，返回0
        return 0, title

    def get_titles(self) -> list[Title]:
        titles = []
        is_series = "series/" in self.original_url

        if is_series:
            series_id = self.title
            self.log.info(f" + Fetching seasons for series {series_id}...")
            
            try:
                # 1. 获取版本列表
                seasons_res = self.session.get(
                    f"https://service-api.tver.jp/api/v1/callSeriesSeasons/{series_id}",
                    params={"app_ver": self.APP_VER}
                )
                seasons_res.raise_for_status()
                seasons_data = seasons_res.json()
                
                seasons_list = seasons_data.get("result", {}).get("contents", [])
                
                # 2. 优先寻找 "本編" (正片)，如果没有则取第一个版本
                target_season = None
                for season_content in seasons_list:
                    season_info = season_content.get("content", {})
                    if season_content.get("type") == "season" and "本編" in season_info.get("title", ""):
                        target_season = season_content
                        break
                
                # 兜底：如果没有任何版本叫"本編"，取列表里的第一个
                if not target_season and seasons_list:
                    target_season = seasons_list[0]
                    
                if target_season:
                    season_info = target_season.get("content", {})
                    season_id = season_info.get("id")
                    season_title = season_info.get("title", "Unknown")
                    
                    self.log.info(f" + Fetching episodes for Season: {season_title}")
                    
                    # 3. 获取该版本下的剧集
                    episodes_res = self._call_platform_api(
                        f"v1/callSeasonEpisodes/{season_id}",
                        series_id,
                        f"Getting episodes for {season_title}"
                    )
                    
                    if episodes_res:
                        for ep_wrap in episodes_res.get("result", {}).get("contents", []):
                            if ep_wrap.get("type") != "episode":
                                continue
                                
                            ep = ep_wrap.get("content", {})
                            ep_title = ep.get("title", "")
                            series_name = ep.get("seriesTitle", "")
                            
                            # 解析标题
                            ep_num, ep_name = self._parse_episode_title(ep_title)
                            
                            titles.append(Title(
                                id_=ep.get("id"),
                                type_=Title.Types.TV if ep_num > 0 else Title.Types.MOVIE,
                                name=series_name,
                                season=1, # 正片统一映射为 S01
                                episode=ep_num,
                                episode_name=ep_name or ep_title,
                                original_lang="ja",
                                source=self.ALIASES[0],
                            ))
                        
            except Exception as e:
                self.log.exit(f" - Failed to get series episodes: {e}")
        else:
            episode_id = self.title
            episode_res = self._call_platform_api(
                f"v1/callEpisode/{episode_id}",
                episode_id,
                "Get Episode Info"
            )
            if not episode_res:
                self.log.exit(f" - Could not retrieve episode info for {episode_id}")

            episode_content = episode_res.get("result", {}).get("episode", {}).get("content", {})
            
            if episode_content:
                ep_title = episode_content.get("title", "")
                series_name = episode_content.get("seriesTitle", "")
                
                # 🔴 使用正则解析标题
                ep_num, ep_name = self._parse_episode_title(ep_title)
                
                titles.append(Title(
                    id_=episode_id,
                    type_=Title.Types.TV if ep_num > 0 else Title.Types.MOVIE,
                    name=series_name,
                    season=1,
                    episode=ep_num,
                    episode_name=ep_name or ep_title,
                    original_lang="ja",
                    source=self.ALIASES[0],
                ))

        if not titles:
            self.log.exit(f" - No titles found for ID: {self.title}")
        return titles

    def get_tracks(self, title: Title) -> Tracks:
        tracks = Tracks()
        episode_id = title.id
        try:
            video_info = self._get_video_info(episode_id)
            streaks_info = video_info.get("streaks", {})
            project_id = streaks_info.get("projectID")
            video_ref_id = streaks_info.get("videoRefID")

            if not all([project_id, video_ref_id]):
                self.log.exit(" - Missing Streaks projectID or videoRefID")

            if not video_ref_id.startswith('ref:'):
                video_ref_id = f"ref:{video_ref_id}"

            # 🔴 核心：动态获取该项目的 Streaks API Key
            api_key = self._get_streaks_api_key(project_id)
            streaks_headers = {
                "Origin": "https://tver.jp",
                "Referer": "https://tver.jp/",
                "X-Streaks-Api-Key": api_key,
            }

            # 请求 Playback 数据 (不带 ati！)
            playback_url = f"https://playback.api.streaks.jp/v1/projects/{project_id}/medias/{video_ref_id}"
            playback_res = self.session.get(playback_url, headers=streaks_headers)
            playback_res.raise_for_status()
            playback_data = playback_res.json()

            sources = playback_data.get("sources", [])
            if not sources:
                self.log.exit(" - No video sources in playback response")
            master_m3u8_url = sources[0].get("src")

            # 后续 m3u8 解析和 Track 创建逻辑保持不变...
            master = m3u8loads(self.session.get(master_m3u8_url, headers=streaks_headers).text, uri=master_m3u8_url)
            
            valid_playlists = [p for p in master.playlists if getattr(p.stream_info, 'pathway_id', None) == "475"]
            if not valid_playlists: valid_playlists = master.playlists
            video_playlist = max(valid_playlists, key=lambda x: x.stream_info.bandwidth)
            
            video_m3u8_url = urljoin(video_playlist.base_uri or master_m3u8_url, video_playlist.uri)
            resolution = video_playlist.stream_info.resolution or (0, 0)
            fps = video_playlist.stream_info.frame_rate
            if fps is not None: fps = float(fps)
            v_codec, a_codec = self._parse_codecs(video_playlist.stream_info.codecs or "")

            tver_headers = {"Origin": "https://tver.jp", "Referer": "https://tver.jp/"}
            video_track = VideoTrack(
                id_="V-0", source=self.ALIASES[0], url=video_m3u8_url, codec=v_codec,
                bitrate=video_playlist.stream_info.bandwidth, width=resolution[0], height=resolution[1],
                fps=fps, encrypted=False, needs_repack=True, descriptor=Track.Descriptor.M3U, 
                extra={"headers": tver_headers}  # 加上这行
            )
            video_track.force_m3u8re = True
            tracks.add(video_track)

            audio_group_id = video_playlist.stream_info.audio
            if audio_group_id:
                audio_media = next((m for m in master.media if m.type == "AUDIO" and m.group_id == audio_group_id and getattr(m, 'default', 'NO') == 'YES'), None) \
                              or next((m for m in master.media if m.type == "AUDIO" and m.group_id == audio_group_id), None)
                if audio_media:
                    audio_m3u8_url = urljoin(audio_media.base_uri or master_m3u8_url, audio_media.uri)
                    audio_track = AudioTrack(
                        id_="A-0", source=self.ALIASES[0], url=audio_m3u8_url, codec=a_codec,
                        language=Language.get(getattr(audio_media, 'language', 'ja') or 'ja'),
                        bitrate=getattr(audio_media, 'bandwidth', 128000) or 128000, encrypted=False,
                        needs_repack=True, descriptor=Track.Descriptor.M3U, 
                        extra={"headers": tver_headers}  # 加上这行
                    )
                    audio_track.force_m3u8re = True
                    tracks.add(audio_track)

            # 5. 字幕处理 (优先 API 的 VTT，其次 M3U8 的 SUBTITLES)
            has_subtitle = False
            
            # 优先级 1: Playback API tracks[] 中的 captions (VTT 直链)
            for track_info in playback_data.get("tracks", []):
                if track_info.get("kind") == "captions" and track_info.get("src"):
                    tracks.add(TextTrack(
                        id_=track_info.get("id", "SUB-API"),
                        source=self.ALIASES[0],
                        url=track_info["src"],
                        codec="vtt",
                        language=Language.get(track_info.get("srclang", "ja")),
                        encrypted=False,
                        extra={"name": track_info.get("label", ""), "headers": tver_headers}  # 加上 headers
                    ))
                    has_subtitle = True
            
            # 优先级 2: Master M3U8 中的 SUBTITLES (m3u8 内嵌 VTT)
            # 只有当 API 中没有找到字幕时，才解析 M3U8
            if not has_subtitle:
                seen_subtitle_uris = set()
                for media in master.media:
                    if media.type != "SUBTITLES":
                        continue
                    subtitle_uri = getattr(media, 'uri', None)
                    if not subtitle_uri or subtitle_uri in seen_subtitle_uris:
                        continue
                    seen_subtitle_uris.add(subtitle_uri)
                    
                    subtitle_url = urljoin(master_m3u8_url, subtitle_uri)
                    subtitle_lang = getattr(media, 'language', 'ja') or 'ja'
                    subtitle_name = getattr(media, 'name', '')
                    
                    tracks.add(TextTrack(
                        id_=f"SUB-M3U8-{subtitle_lang}",
                        source=self.ALIASES[0],
                        url=subtitle_url,
                        codec="vtt",
                        language=Language.get(subtitle_lang),
                        encrypted=False,
                        extra={
                            "name": subtitle_name,
                            "default": getattr(media, 'default', 'NO') == 'YES',
                            "headers": tver_headers  # 加上 headers
                        }
                    ))             

        except requests.exceptions.HTTPError as e:
            self.log.exit(f" - HTTP {e.response.status_code}: {e.response.url}")
        except Exception as e:
            self.log.exit(f" - {type(e).__name__}: {e}")
        # --- 新增：从 TVer 元数据补充时长和体积 ---
        # TVer 的 CDN 有防盗链，直接探测子清单不稳定，因此使用 API 返回的时长
        duration_str = video_info.get("video", {}).get("duration", None)
        if duration_str:
            try:
                duration_sec = float(duration_str)
                for track in tracks.videos + tracks.audios:
                    if not track.duration:
                        track.duration = duration_sec
                        if track.bitrate:
                            track.size = int((float(track.bitrate) * duration_sec) / 8)
            except (ValueError, TypeError):
                pass
        # ----------------------------------------

        try:
            sub_res = self.session.get(video_m3u8_url, headers=streaks_headers)
            sub_res.raise_for_status()
            sub_m3u8 = m3u8loads(sub_res.text, uri=video_m3u8_url)
            total_duration = sum(seg.duration for seg in sub_m3u8.segments if seg.duration)
            if total_duration:
                for track in tracks.videos + tracks.audios:
                    track.duration = total_duration
                    if track.bitrate:
                        track.size = int((float(track.bitrate) * total_duration) / 8)
        except Exception as e:
            self.log.warning(f"Failed to probe sub-manifest for duration: {e}")
        # ----------------------------------------

        return tracks

    def get_chapters(self, title: Title) -> list[MenuTrack]:
        return []

    def license(self, key_url: str, track: Track, **kwargs) -> bytes:
        """获取 AES-128 密钥"""
        # 🔴 获取 Key 也需要带 Streaks Header
        # 注意：key_url 中包含了 project 信息，我们可以从中提取，或者直接用当前 episode 的 project_id
        # 这里简单处理，直接使用 Origin 和 Referer (yt-dlp 的做法)
        headers = {
            "Origin": "https://tver.jp",
            "Referer": "https://tver.jp/",
        }
        # 如果只用 Origin/Referer 被拒，则需要传入 project_id 并使用动态 API Key
        
        try:
            res = self.session.get(key_url, headers=headers)
            res.raise_for_status()
            if len(res.content) != 16:
                self.log.exit(f" - Invalid AES key length: {len(res.content)}")
            return res.content
        except Exception as e:
            self.log.exit(f" - Failed to fetch AES key: {e}")
            return b""

    def _call_platform_api(self, path: str, display_id: str, note: str, params: dict = None):
        query = {"platform_uid": self.platform_uid, "platform_token": self.platform_token, "app_ver": self.APP_VER}
        if params: query.update(params)
        try:
            req = self.session.get(f"https://platform-api.tver.jp/service/api/{path}", params=query)
            req.raise_for_status()
            return req.json()
        except requests.exceptions.RequestException as e:
            self.log.error(f" - API call failed for '{note}' ({display_id}): {e}")
            return None