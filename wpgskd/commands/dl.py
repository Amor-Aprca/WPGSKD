import logging
import math
import os
import random
import time
from pathlib import Path

import click
import requests

from wpgskd import servicookies as services
from wpgskd.config import config, directories, filenames
from wpgskd.core.cdm.loader import CdmProvider
from wpgskd.core.console import ConsoleUI
from wpgskd.core.decryptor import Decryptor
from wpgskd.core.downloader import Downloader
from wpgskd.core.events import EventManager, Events
from wpgskd.core.muxer import Muxer
from wpgskd.core.resolver import KeyResolver
from wpgskd.core.tracks.title import Title, Titles
from wpgskd.core.tracks.audio import AudioTrack
from wpgskd.core.tracks.tracks import TextTrack
from wpgskd.core.vault import LocalVault
from wpgskd.core.vaults import Vaults
from wpgskd.utils.click import (AliasedGroup, ContextData, acodec_param,
                                channels_param, language_param, quality_param,
                                range_param, vcodec_param, wanted_param)

log = logging.getLogger("dl")

@click.group(name="dl", short_help="Download from a service.", cls=AliasedGroup, context_settings=dict(
    help_option_names=["-?", "-h", "--help"],
    max_content_width=116,
    default_map=config.arguments
))
@click.option("--debug", is_flag=True, hidden=True)
@click.option("-p", "--profile", type=str, default=None,
              help="Profile to use when multiple profiles are defined for a service.")
@click.option("-q", "--quality", callback=quality_param, default=None,
              help="Download Resolution, defaults to best available.")
@click.option("-v", "--vcodec", callback=vcodec_param, default="H264",
              help="Video Codec, defaults to H264.")
@click.option("-a", "--acodec", callback=acodec_param, default=None,
              help="Audio Codec")
@click.option("-vb", "--vbitrate", "vbitrate", type=int, default=None,
              help="Video Bitrate, defaults to Max.")
@click.option("-ab", "--abitrate", "abitrate", type=int, default=None,
              help="Audio Bitrate, defaults to Max.")
@click.option("-aa", "--atmos", is_flag=True, default=False,
              help="Prefer Atmos Audio")
@click.option("-ch", "--channels", callback=channels_param, default=None,
              help="Audio Channels")
@click.option("-r", "--range", "range_", callback=range_param, default="SDR",
              help="Video Color Range, defaults to SDR.")
@click.option("-w", "--wanted", callback=wanted_param, default=None,
              help="Wanted episodes, e.g. `S01-S05,S07`, `S01E01-S02E03`, defaults to all.")
@click.option("-al", "--alang", callback=language_param, default="orig",
              help="Language wanted for audio.")
@click.option("-sl", "--slang", callback=language_param, default="all",
              help="Language wanted for subtitles.")
@click.option("--delay", type=int, default=None,
              help="Delay between title processing")
@click.option("--proxy", type=str, default=None,
              help="Proxy URI to use. If a 2-letter country is provided, it will try get a proxy from the config.")
@click.option("-A", "--audio-only", is_flag=True, default=False, help="Only download audio tracks.")
@click.option("-S", "--subs-only", is_flag=True, default=False, help="Only download subtitle tracks.")
@click.option("-C", "--chapters-only", is_flag=True, default=False, help="Only download chapters.")
@click.option("-ns", "--no-subs", is_flag=True, default=False, help="Do not download subtitle tracks.")
@click.option("-na", "--no-audio", is_flag=True, default=False, help="Do not download audio tracks.")
@click.option("-nv", "--no-video", is_flag=True, default=False, help="Do not download video tracks.")
@click.option("-nc", "--no-chapters", is_flag=True, default=False, help="Do not download chapters tracks.")
@click.option("-ad", "--audio-description", is_flag=True, default=False, help="Download audio description tracks.")
@click.option("--list", "list_", is_flag=True, default=False, help="List available tracks without downloading.")
@click.option("--selected", is_flag=True, default=False, help="List selected tracks without downloading.")
@click.option("--cdm", type=str, default=None, help="Override the CDM that will be used for decryption.")
@click.option("--export", "export_arg", is_flag=False, flag_value="", default=None,
              help="Export track info and decryption keys to a JSON file. Can optionally specify file name.")
@click.option("--keys", is_flag=True, default=False, help="Skip downloading, retrieve keys and print them.")
@click.option("--cache", is_flag=True, default=False, help="Disable CDM use, only retrieve keys from Key Vaults.")
@click.option("--no-cache", is_flag=True, default=False, help="Disable Key Vaults use, only retrieve keys from CDM.")
@click.option("--no-proxy", is_flag=True, default=False, help="Force disable all proxy use.")
@click.option("--force-proxy", is_flag=True, default=False, help="Force using proxy even if current region matches.")
@click.option("-nm", "--no-mux", is_flag=True, default=False, help="Do not mux the downloaded and decrypted tracks.")
@click.option("--mux", is_flag=True, default=False, help="Force muxing when using --audio-only/--subs-only/--chapters-only.")
@click.option("--worst", is_flag=True, default=False, help="Choose the worst available video tracks rather than the best")
@click.option("--sync-vat", is_flag=True, default=False, help="Compress audio duration to match video duration before muxing.")
@click.option("-nys", "--no-sync-subs", is_flag=True, default=False, help="Do not merge/sync subtitle tracks during muxing.")
@click.pass_context
def dl(ctx, profile, cdm, *_, **__):
    """Download from a specified service."""
    if ctx.params.get("debug"):
        import coloredlogs
        LOG_FORMAT = "{asctime} [{levelname[0]}] {name} : {message}"
        LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
        LOG_STYLE = "{"
        coloredlogs.install(
            level=logging.DEBUG,
            fmt=LOG_FORMAT,
            datefmt=LOG_DATE_FORMAT,
            style=LOG_STYLE,
            handlers=[logging.StreamHandler()]
        )
        
    service_name = ctx.params.get("service_name") or services.get_service_key(ctx.invoked_subcommand)
    if not service_name:
        log.error(" - Unable to find service")
        return

    profile = profile or config.profiles.get(service_name) or config.profiles.get("default") or "default"
    
    service_config = services.get_service_config(service_name)

    vaults_list = []
    for vault_cfg in config.key_vaults:
        try:
            vaults_list.append(Vaults.load_vault(vault_cfg))
        except Exception as e:
            log.error(f" - Failed to load vault {vault_cfg.get('name')!r}: {e}")
    
    vaults_obj = Vaults(vaults_list, service=service_name)
    local_count = sum(1 for v in vaults_obj.vaults if isinstance(v, LocalVault))
    remote_count = sum(1 for v in vaults_obj.vaults if not isinstance(v, LocalVault))
    log.info(f" + {local_count} Local, {remote_count} Remote Vault(s) loaded")

    cdm_cfg_dict = {k.lower(): v for k, v in config.cdm.items()}
    cdm_name = cdm or cdm_cfg_dict.get(service_name.lower()) or cdm_cfg_dict.get("default")

    try:
        cdm_prov = CdmProvider(
            cdm_name=cdm_name,
            device_dir=directories.devices,
            cdm_api_config=config.cdm_api
        )
        cdm_prov.log_info()
    except Exception as e:
        log.error(f" - CDM Init Error: {e}")
        raise click.Abort() 
        return

    cookies = credentials_obj = None
    needs_auth = service_config.get("needs_auth", True)
    if profile:
        cookies = services.get_cookie_jar(service_name, profile)
        credentials_obj = services.get_credentials(service_name, profile)
        if not cookies and not credentials_obj and needs_auth:
            log.error(f" - Profile {profile!r} has no cookies or credentials")
            return

    ctx.obj = ContextData(
        config=service_config,
        vaults=vaults_obj,
        cdm=cdm_prov,
        profile=profile,
        cookies=cookies,
        credentials=credentials_obj
    )


@dl.result_callback()
def result(service, quality, vcodec, acodec, range_, wanted, alang, slang,
           audio_only, subs_only, chapters_only, audio_description, list_, keys,
           cache, no_cache, no_subs, no_audio, no_video, no_chapters, atmos,
           vbitrate: int, abitrate: int, channels, no_mux, worst, mux, delay,
           selected, sync_vat, no_sync_subs, export_arg, *_, **__):

    log = service.log
    service_name = service.__class__.__name__

    log.info("Retrieving Titles")
    try:
        titles = Titles(service.get_titles())
    except requests.HTTPError as e:
        log.error(f" - HTTP Error {e.response.status_code}: {e.response.reason}")
        return
        
    if not titles:
        log.error(" - No titles returned!")
        return
        
    titles.order()
    ConsoleUI.print_titles(titles)

    cdm_prov: CdmProvider = service.cdm
    resolver = KeyResolver(
        vaults=service.vaults,
        cdm_provider=cdm_prov,
        use_cache=not no_cache,
        use_cdm=not cache
    )
    downloader = Downloader(session=service.session)

    first = True
    for title in titles.with_wanted(wanted):
        if not first and delay:
            jitter = random.randint(math.floor(-delay / 5), math.floor(delay / 5))
            d = delay + jitter
            log.info(f"Delaying for {d}s before getting next title...")
            time.sleep(d)
        first = False

        _log_title(log, title)

        try:
            title.tracks.add(service.get_tracks(title), warn_only=True)
            chapters = service.get_chapters(title)
            if chapters:
                title.tracks.add(chapters)
        except requests.HTTPError as e:
            log.error(f" - HTTP Error getting tracks: {e.response.status_code}")
            continue

        title.tracks.sort_videos()
        title.tracks.sort_audios(by_language=alang)
        title.tracks.sort_subtitles(by_language=slang)
        title.tracks.sort_chapters()
        
        for track in title.tracks:
            track.is_original_lang = track.language == title.original_lang

        if not list(title.tracks):
            log.error(" - No tracks returned!")
            continue

        if not selected:
            log.info("> All Tracks:")
            ConsoleUI.print_tracks(title.tracks, title)

        try:
            if range_ == "DV+HDR":
                title.tracks.select_videos_multi(["HDR10", "DV"], by_quality=quality, by_vbitrate=vbitrate)
            else:
                title.tracks.select_videos(
                    by_quality=quality, by_vbitrate=vbitrate, by_range=range_,
                    one_only=True, by_worst=worst, by_codec=vcodec
                )
            title.tracks.select_audios(
                by_language=alang, by_bitrate=abitrate, with_atmos=atmos,
                with_descriptive=audio_description, by_channels=channels, by_codec=acodec
            )
            title.tracks.select_subtitles(by_language=slang, with_forced=True)
        except ValueError as e:
            log.error(f" - {e}")
            continue

        _apply_filters(title, no_video, no_audio, no_subs, no_chapters, audio_only, subs_only, chapters_only, mux)

        log.info("> Selected Tracks:")
        ConsoleUI.print_tracks(title.tracks, title)

        if list_:
            continue

        all_content_keys = {}
        skip_title = False
        
        for track in title.tracks:
            if track.encrypted and str(track.descriptor).split(".")[-1] == "M3U":
                if not track.pssh and not track.pr_pssh:
                    track.get_pssh(service.session)
                    
            enc_scheme = track.encryption_scheme.name if hasattr(track.encryption_scheme, 'name') else track.encryption_scheme
            if not track.encrypted or enc_scheme in ["AES_128", "CLEARKEY"]:
                continue

            log.info(f"Licensing: {str(track).replace('├─ ', '').replace('└─ ', '')}")
            
            if not track.pssh and not track.pr_pssh:
                track.get_pssh(service.session)
                
            if not track.kid:
                track.get_kid(service.session)

            cdm_type = cdm_prov.cdm_instance.cdm_type if cdm_prov else "widevine"

            if cdm_type == "playready":
                if getattr(track, 'pr_pssh', None):
                    pssh_str = track.pr_pssh
                    if isinstance(pssh_str, bytes):
                        pssh_str = pssh_str.decode('utf-8', 'ignore')
                    log.info(f" + PR_PSSH: {pssh_str}")
            else:  # widevine
                if getattr(track, 'pssh', None):
                    pssh_obj = track.pssh
                    try:
                        if hasattr(pssh_obj, 'dumps') and callable(pssh_obj.dumps):
                            dumped = pssh_obj.dumps()
                            if isinstance(dumped, bytes):
                                import base64
                                log.info(f" + WV_PSSH: {base64.b64encode(dumped).decode('utf-8')}")
                            else:
                                log.info(f" + WV_PSSH: {dumped}")
                        else:
                            log.info(f" + WV_PSSH: {pssh_obj}")
                    except Exception:
                        log.info(f" + WV_PSSH: {pssh_obj}")
            
            if getattr(track, 'kid', None):
                log.info(f" + KID: {track.kid}")

            try:
                pk, akeys = resolver.resolve(track, title, service, service_name, service.session)
                if cache and not pk:
                    skip_title = True
                    break
                
                if pk:
                    track.key = pk
                    all_content_keys.update(akeys)
                    log.info(f" + KEY: {pk[:32]}... (Resolved)")
                    
                    if export_arg is not None:
                        import click as click_mod
                        current_ctx = click_mod.get_current_context()
                        _export_keys(
                            directories.exports, service_name, title, track, akeys, 
                            export_arg, 
                            cli_title_id=current_ctx.parent.params.get("title", ""),
                            quality=quality,
                            vcodec=vcodec,
                            range_=range_
                        )
                else:
                    log.error(" - No content key returned")
                    return
            except Exception as e:
                log.error(f" - Key Resolution Failed: {e}")
                return

        if skip_title:
            for track in title.tracks:
                track.delete()
            continue
            
        if keys:
            continue

        EventManager.publish(Events.BEFORE_DOWNLOAD, title)

        for track in title.tracks:
            log.info(f"\nDownloading: {track}")
            
            proxy = None
            if track.needs_proxy:
                proxy = next(iter(service.session.proxies.values()), None)

            try:
                downloader.download(track, directories.temp, proxy=proxy, title_ref=title, all_keys=all_content_keys)
                log.info(" + Downloaded")
                EventManager.publish(Events.AFTER_DOWNLOAD, track)
            except Exception as e:
                log.error(f" - Download failed: {e}")
                continue

            should_decrypt = track.encrypted and enc_scheme not in ["AES_128", "AES_128_ECB", "CLEARKEY"]
            if should_decrypt:
                log.info("Decrypting...")
                dec_keys = {track.kid.lower().replace("-", ""): track.key.lower()}
                dec_keys.update({k.lower(): v.lower() for k, v in all_content_keys.items()})
                
                try:
                    dec_path = Decryptor.decrypt(track, dec_keys, config.decrypter, directories.temp)
                    if dec_path and track.swap(dec_path):
                        log.info(" + Decrypted")
                        EventManager.publish(Events.AFTER_DECRYPT, track)
                        
                        if track.needs_repack or config.decrypter == "mp4decrypt":
                            log.info("Repackaging stream with FFmpeg")
                            Decryptor.repackage(track.locate())
                            log.info(" + Repackaged")
                    else:
                        log.warning(" - Decryption swap failed")
                except Exception as e:
                    log.error(f" - Decryption failed: {e}")

        if range_ == "DV+HDR":
            try:
                if not any(v.dv and v.hdr10 for v in title.tracks.videos):
                    pass
            except Exception as e:
                log.warning(f" - Skipped DV+HDR: {e}")

        if not list(title.tracks) and not title.tracks.chapters:
            continue

        EventManager.publish(Events.BEFORE_MUX, title)
        
        if no_mux:
            _output_unmuxed(title, log)
        else:
            _output_muxed(title, log, audio_only, subs_only, service_name, sync_vat, no_sync_subs)
            EventManager.publish(Events.AFTER_MUX, title)

    log.info("Processed all titles!")

def _log_title(logger, title: Title):
    if title.type == Title.Types.TV:
        ep = f" - {title.episode_name}" if title.episode_name else ""
        logger.info(f"Getting tracks for {title.name} S{title.season or 0:02}E{title.episode or 0:02}{ep} [{title.id}]")
    else:
        yr = f" ({title.year})" if title.year else ""
        logger.info(f"Getting tracks for {title.name}{yr} [{title.id}]")

def _apply_filters(title, nv, na, ns, nc, ao, so, co, mux):
    if nv: title.tracks.videos.clear()
    if na: title.tracks.audios.clear()
    if ns: title.tracks.subtitles.clear()
    if nc: title.tracks.chapters.clear()
    if ao or so or co:
        title.tracks.videos.clear()
        if ao:
            if not so: title.tracks.subtitles.clear()
            if not co: title.tracks.chapters.clear()
        elif so:
            if not ao: title.tracks.audios.clear()
            if not co: title.tracks.chapters.clear()
        elif co:
            if not ao: title.tracks.audios.clear()
            if not so: title.tracks.subtitles.clear()

def _output_unmuxed(title: Title, logger):
    out_dir = Path(directories.downloads)
    if title.type == Title.Types.TV:
        out_dir = out_dir / title.parse_filename(folder=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    if title.tracks.chapters:
        loc = out_dir / f"{title.filename}_chapters.txt"
        title.tracks.export_chapters(str(loc))

    for track in title.tracks:
        if not track.locate(): continue
        fn = title.parse_filename()
        if isinstance(track, (AudioTrack, TextTrack)):
            fn += f".{track.language}"
        ext = track.codec if isinstance(track, TextTrack) else Path(track.locate()).suffix[1:]
        if isinstance(track, AudioTrack) and ext == "mp4": ext = "m4a"
        track.move(str(out_dir / f"{fn}.{track.id}.{ext}"))

def _output_muxed(title: Title, logger, audio_only, subs_only, service_name, sync_vat, no_sync_subs):
    try:
        muxed_location, returncode = Muxer.mux(title, title.tracks, no_sync_subs=no_sync_subs)
        
        if returncode >= 2:
            logger.error(" - Failed to mux tracks into MKV file")
            return

        logger.info(" + Muxed")
        
        out_dir = Path(directories.downloads)
        if title.type == Title.Types.TV:
            out_dir = out_dir / title.parse_filename(folder=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        ext = "mka" if audio_only else "mks" if subs_only else "mkv"
        target_path = out_dir / f"{title.parse_filename()}.{ext}"
        
        import shutil
        shutil.move(muxed_location, str(target_path))
        logger.info(f" + Saved to: {target_path}")

        if sync_vat:
            logger.info("Applying Audio-Video Sync (SyncVAT)...")
            Muxer.apply_sync(str(target_path))

        for track in title.tracks:
            try: track.delete()
            except: pass
        if title.tracks.chapters:
            try: os.unlink(filenames.chapters.format(filename=title.filename))
            except: pass
            
    except Exception as e:
        logger.error(f" - Muxing failed: {e}")

def _export_keys(export_dir, service_name, title, track, keys, export_name="", cli_title_id="", quality=None, vcodec=None, range_=None):
    import json
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    
    if export_name:
        if not export_name.endswith(".json"):
            export_name += ".json"
        export_path = export_dir / export_name
    else:
        if isinstance(quality, int):
            q_str = f"{quality}P"
        elif quality:
            q_str = str(quality).upper()
        else:
            q_str = "ALL"
            
        v_str = vcodec.upper() if vcodec else "ALL"
        r_str = range_.upper() if range_ else "ALL"
        
        export_file = f"{service_name}_{cli_title_id}_{q_str}_{v_str}_{r_str}.json"
        export_path = export_dir / export_file
    
    doc = {}
    if export_path.is_file():
        try: 
            doc = json.loads(export_path.read_text(encoding="utf-8"))
        except: pass
        
    titles_dict = doc.setdefault("titles", {})
    tinfo = titles_dict.setdefault(str(title.id), {})
    
    tinfo["title_id"] = title.id
    tinfo["title_name"] = title.name
    tinfo["type"] = "TV" if title.type == Title.Types.TV else "MOVIE"
    tinfo["year"] = title.year
    if title.type == Title.Types.TV:
        tinfo["season"] = title.season
        tinfo["number"] = title.episode
        
    tinfo["cbr_manifest_url"] = getattr(title, 'cbr_manifest_url', None)
    tinfo["cvbr_manifest_url"] = getattr(title, 'cvbr_manifest_url', None)
   
    manifest_url = getattr(title, 'manifest_url', None)
    if not manifest_url and title.tracks.videos:
        manifest_url = getattr(title.tracks.videos[0], 'manifest_url', None)
    tinfo["manifest_url"] = manifest_url
    
    tinfo["tracks"] = tinfo.get("tracks", {})
    track_data = tinfo["tracks"].setdefault(str(track), {})
    k_data = track_data.setdefault("keys", {})
    for kid, key in keys.items():
        k_data[kid] = key
        
    export_path.write_text(json.dumps(doc, indent=4, ensure_ascii=False), encoding="utf-8")
