import json
import logging
import os
import sys
import re
import yaml
from abc import ABC, abstractmethod
from http.cookiejar import MozillaCookieJar

import requests
from requests.adapters import HTTPAdapter, Retry
import random

from wpgskd import config as config_module 
from wpgskd.utils import try_get
from wpgskd.utils.collections import as_list, merge_dict
from wpgskd.utils.io import get_ip_info


class BaseService(ABC):
    ALIASES = []  
    GEOFENCE = []  

    def __init__(self, ctx):
        self.service_path = sys.modules[self.__module__].__file__
        self.service_dir = os.path.dirname(self.service_path)
        self.service_name = self.__class__.__name__

        self.log = logging.getLogger(self.ALIASES[0])
        
        self.service_config = self.load_local_config()
        self.local_cookies = self.load_local_cookies()

        self.config = ctx.obj.config if hasattr(ctx.obj, 'config') else {}
        
        if self.service_config:
            merge_dict(self.config, self.service_config)

        self.cookies = ctx.obj.cookies if hasattr(ctx.obj, 'cookies') else None
        self.credentials = ctx.obj.credentials if hasattr(ctx.obj, 'credentials') else None
        
        self.cdm = ctx.obj.cdm if hasattr(ctx.obj, 'cdm') else None
        self.vaults = ctx.obj.vaults if hasattr(ctx.obj, 'vaults') else None
        self.profile = ctx.obj.profile if hasattr(ctx.obj, 'profile') else None

        self.session = self.get_session()
        self.force_proxy = ctx.parent.params.get("force_proxy", False)

        if not ctx.parent.params.get("no_proxy"):
            self.setup_proxy(ctx)

    def get_session(self):
        session = requests.Session()
        session.mount("https://", HTTPAdapter(
            max_retries=Retry(
                total=5,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
        ))
        session.hooks = {
            "response": lambda r, *_, **__: r.raise_for_status(),
        }
        
        if hasattr(config_module, 'config') and hasattr(config_module.config, 'headers'):
            headers = config_module.config.headers
            if isinstance(headers, dict):
                session.headers.update(headers)
        
        if self.local_cookies:
            session.cookies.update(self.local_cookies)
        elif self.cookies:
            session.cookies.update(self.cookies)
            
        return session

    def load_local_config(self):
        candidates = [
            os.path.join(self.service_dir, f"{self.service_name}.yml"),
            os.path.join(self.service_dir, f"{self.service_name.lower()}.yml")
        ]
        for path in candidates:
            if os.path.exists(path):
                self.log.debug(f"Loading local config: {path}")
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        return yaml.safe_load(f) or {}
                except Exception as e:
                    self.log.warning(f"Failed to load config {path}: {e}")
        return {}

    def load_local_cookies(self):
        cookie_path = os.path.join(self.service_dir, "cookie.txt")
        if os.path.exists(cookie_path):
            self.log.debug(f"Loading local cookies: {cookie_path}")
            try:
                cj = MozillaCookieJar(cookie_path)
                cj.load(ignore_discard=True, ignore_expires=True)
                return cj
            except Exception as e:
                self.log.warning(f"Failed to load cookies {cookie_path}: {e}")
        return None

    def setup_proxy(self, ctx):
        proxy = ctx.parent.params.get("proxy") or next(iter(self.GEOFENCE), None)
        if proxy:
            if len("".join(i for i in proxy if not i.isdigit())) == 2:
                proxy = self.get_proxy(proxy)
            if proxy:
                if "://" not in proxy: proxy = f"https://{proxy}"
                self.session.proxies.update({"all": proxy})
                self.log.info(f"Using Proxy: {proxy}")
            else:
                self.log.info(" + Proxy was skipped as current region matches")

    @abstractmethod
    def get_titles(self):
        raise NotImplementedError

    @abstractmethod
    def get_tracks(self, title):
        raise NotImplementedError

    def get_chapters(self, title):
        return []

    def certificate(self, challenge, title, track, session_id):
        return self.license(challenge, title, track, session_id)

    @abstractmethod
    def license(self, challenge, title, track, session_id, drm_type=None):
        raise NotImplementedError

    def parse_title(self, ctx, title):
        title = title or ctx.parent.params.get("title")
        if not title:
            self.log.exit(" - No title ID specified")
        if not getattr(self, "TITLE_RE", None):
            self.title = title
            return {}
        for regex in as_list(self.TITLE_RE):
            m = re.search(regex, title)
            if m:
                self.title = m.group("id")
                return m.groupdict()
        self.log.warning(f" - Unable to parse title ID {title!r}, using as-is")
        self.title = title

    def get_cache(self, key):
        from wpgskd.config import directories
        cache_dir = getattr(directories, 'cache', None)
        if not cache_dir:
            cache_dir = os.path.join(os.getcwd(), "cache")
        target_dir = os.path.join(cache_dir, self.ALIASES[0])
        os.makedirs(target_dir, exist_ok=True)
        return os.path.join(target_dir, key)

    def get_proxy(self, region):
        if not region:
            raise self.log.exit("Region cannot be empty")
        region = region.lower()

        self.log.info(f"Obtaining a proxy to \"{region}\"")

        if not self.force_proxy and get_ip_info()["country_code"].lower() == "".join(char for char in region if not char.isdigit()):
            return None

        if getattr(config_module.config, 'proxies', {}).get(region) and not getattr(config_module.config, 'default_proxy_service', None):
            proxy = config_module.config.proxies[region]
            self.log.info(f" + {proxy}")
        else:
            default_service = getattr(config_module.config, 'default_proxy_service', None)
            proxy = None

            if default_service == "nordvpn" and getattr(config_module.config, 'nordvpn', {}).get("username") and getattr(config_module.config, 'nordvpn', {}).get("password"):
                proxy = self.get_nordvpn_proxy(region)
                self.log.info(f" + {proxy} (via NordVPN)")
            elif default_service == "surfshark" and getattr(config_module.config, 'surfshark', {}).get("username") and getattr(config_module.config, 'surfshark', {}).get("password"):
                proxy = self.get_surfshark_proxy(region, config_module.config.surfshark)
                self.log.info(f" + {proxy} (via SurfShark)")
            else:
                raise self.log.exit(" - Unable to obtain a proxy")

        if "://" not in proxy:
            proxy = f"https://{proxy}"

        return proxy

    def get_nordvpn_proxy(self, region):
        proxy = f"https://{config_module.config.nordvpn['username']}:{config_module.config.nordvpn['password']}@"
        if any(char.isdigit() for char in region):
            proxy += f"{region}.nordvpn.com"
        elif try_get(config_module.config.nordvpn, lambda x: x["servers"][region]):
            proxy += f"{region}{config_module.config.nordvpn['servers'][region]}.nordvpn.com"
        else:
            hostname = self.get_nordvpn_server(region)
            if not hostname:
                raise self.log.exit(f" - NordVPN doesn't contain any servers for the country \"{region}\"")
            proxy += hostname
        return proxy + ":89"

    def get_nordvpn_server(self, country):
        countries = self.session.get(
            url="https://api.nordvpn.com/v1/servers/countries"
        ).json()

        country_id = [x["id"] for x in countries if x["code"].lower() == country.lower()]
        if not country_id:
            return None
        country_id = country_id[0]

        recommendations = self.session.get(
            url="https://api.nordvpn.com/v1/servers/recommendations",
            params={
                "filters[country_id]": country_id,
                "limit": 30
            }
        ).json()
        hostnames = [host["hostname"] for host in recommendations]
        chosen_host = random.choice(hostnames)

        return chosen_host

    def get_surfshark_proxy(self, region, data):
        proxy = f"https://{data['username']}:{data['password']}@"
        if not (hostname := self.get_surfshark_server(region)):
            raise ValueError(
                f"SurfShark doesn't contain any servers for the country {region!r}"
            )
        proxy += hostname
        return proxy + ":443"

    def get_surfshark_server(self, country):
        response = self.session.get(
            url='https://api.surfshark.com/v5/server/clusters/all'
        )
        countries = response.json()

        if not (
            items := [
                x
                for x in countries
                if x["countryCode"].lower() == country.lower()
                and x["type"].lower() not in ("obfuscated", "static")
            ]
        ):
            return None

        hostname = min(items, key=lambda x: x["load"])["connectionName"]

        return hostname