import os
import sys
import logging
from types import SimpleNamespace
from pathlib import Path

import yaml
from appdirs import AppDirs
from requests.utils import CaseInsensitiveDict

from wpgskd.utils.collections import merge_dict

class Directories:
    def __init__(self):
        self.app_dirs = AppDirs("wpgskd", False)
        self.package_root = Path(__file__).resolve().parent.parent
        self.project_root = self.package_root.parent
        
        self.configuration = self.project_root / "config"
        self.user_configs = self.project_root
        
        self.service_configs = self.package_root / "servicookies"
        
        self.data = self.package_root
        
        self.downloads = self.project_root / "downloads"
        self.temp = self.project_root / "temp"
        self.cache = self.project_root / "cache"
        self.logs = self.project_root / "logs"
        self.exports = self.project_root / "exports"
        
        self.cookies = self.service_configs 

        self.devices = self.project_root / "devices"
        if not self.devices.exists():
            self.devices = self.package_root / "devices"

class Filenames:
    def __init__(self):
        self.log = os.path.join(directories.logs, "wpgskd_{time}.log")
        self.root_config = os.path.join(directories.package_root, "wpgskd.yml")
        self.user_root_config = os.path.join(directories.user_configs, "wpgskd.yml")
        
        self.service_config = os.path.join(directories.configuration, "services", "{service}.yml")
        self.user_service_config = os.path.join(directories.service_configs, "{service}.yml")
        
        self.subtitles = os.path.join(directories.temp, "TextTrack_{id}_{language_code}.srt")
        self.chapters = os.path.join(directories.temp, "{filename}_chapters.txt")

directories = Directories()
filenames = Filenames()

os.makedirs(directories.logs, exist_ok=True)
os.makedirs(directories.temp, exist_ok=True)
os.makedirs(directories.downloads, exist_ok=True)
os.makedirs(directories.cache, exist_ok=True)
os.makedirs(directories.exports, exist_ok=True)

config_data = {}
if os.path.exists(filenames.root_config):
    try:
        with open(filenames.root_config, encoding='utf-8') as fd:
            loaded = yaml.safe_load(fd)
            if loaded: config_data = loaded
    except Exception as e:
        print(f"Error loading config {filenames.root_config}: {e}")

user_config_data = {}
if os.path.exists(filenames.user_root_config):
    try:
        with open(filenames.user_root_config, encoding='utf-8') as fd:
            loaded = yaml.safe_load(fd)
            if loaded: user_config_data = loaded
    except Exception as e:
        print(f"Error loading user config {filenames.user_root_config}: {e}")

merge_dict(config_data, user_config_data)

if not config_data:
    print(f"Warning: No configuration loaded. Please ensure {filenames.root_config} exists.")

config = SimpleNamespace(**config_data)

credentials = getattr(config, 'credentials', {})

def setup_paths():
    if hasattr(config, 'directories'):
        downloads_path = config.directories.get('downloads')
        temp_path = config.directories.get('temp')

        if downloads_path:
            p = Path(downloads_path)
            if not p.is_absolute(): p = directories.project_root / p
            directories.downloads = p
            os.makedirs(directories.downloads, exist_ok=True)

        if temp_path:
            p = Path(temp_path)
            if not p.is_absolute(): p = directories.project_root / p
            directories.temp = p
            os.makedirs(directories.temp, exist_ok=True)
            
            filenames.subtitles = os.path.join(directories.temp, "TextTrack_{id}_{language_code}.srt")
            filenames.chapters = os.path.join(directories.temp, "{filename}_chapters.txt")

setup_paths()

try:
    from wpgskd.servicookies import SERVICE_MAP
except ImportError:
    SERVICE_MAP = {}

if not hasattr(config, 'arguments'):
    config.arguments = {}

if "range_" not in config.arguments:
    config.arguments["range_"] = config.arguments.get("range")

for service, aliases in SERVICE_MAP.items():
    for alias in aliases:
        config.arguments[alias] = config.arguments.get(service)

config.arguments = CaseInsensitiveDict(config.arguments)