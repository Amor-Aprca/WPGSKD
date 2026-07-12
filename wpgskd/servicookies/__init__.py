import os
import logging
import importlib.util
import sys
import traceback
from wpgskd.servicookies.BaseService import BaseService

SERVICE_MAP = {}
log = logging.getLogger("ServiceLoader")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_services():
    """
    Dynamically load all service modules.
    """
    count = 0

    for item in os.listdir(BASE_DIR):
        item_path = os.path.join(BASE_DIR, item)
        
        if os.path.isdir(item_path) and not item.startswith("_") and item != "dm":
            
            candidates = []
            exact_match = os.path.join(item_path, f"{item.lower()}.py")
            if os.path.exists(exact_match):
                candidates.append(exact_match)
            else:
                for f in os.listdir(item_path):
                    if f.endswith(".py") and not f.startswith("__") and not f.endswith("_pb2.py"):
                        candidates.append(os.path.join(item_path, f))
            
            for py_file in candidates:
                try:
                    module_name = f"wpgskd.servicookies.{item}.{os.path.splitext(os.path.basename(py_file))[0]}"
                    
                    spec = importlib.util.spec_from_file_location(module_name, py_file)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        sys.modules[module_name] = module
                        spec.loader.exec_module(module)
                        
                        for name, obj in module.__dict__.items():
                            if isinstance(obj, type) and issubclass(obj, BaseService) and obj != BaseService:
                                SERVICE_MAP[name] = obj.ALIASES
                                globals()[name] = obj
                                count += 1
                                # log.info(f"Loaded service: {name}")
                except Exception as e:
                    print(f"\n[ERROR] Failed to load service from {py_file}")
                    print(f"Reason: {e}")
                    traceback.print_exc()
                    print("-" * 30 + "\n")

    log.info(f"Loaded {count} services.")

load_services()

import os
import html
from http.cookiejar import MozillaCookieJar
from wpgskd.config import filenames, directories
from wpgskd.utils.io import load_yaml
from wpgskd.utils.collections import merge_dict
from wpgskd.core.credential import Credential

def get_service_config(service: str) -> dict:
    """Get both service config and service secrets as one merged dictionary."""
    service_config = load_yaml(filenames.service_config.format(service=service.lower()))

    user_config_path = os.path.join(directories.service_configs, f"{service.lower()}.yml")
    if os.path.exists(user_config_path):
        user_config = load_yaml(user_config_path)
        if user_config:
            merge_dict(service_config, user_config)
            
    return service_config

def get_cookie_jar(service: str, profile: str):
    """Get the profile's cookies if available."""
    cookie_file = os.path.join(directories.cookies, service.lower(), f"{profile}.txt")
    if not os.path.isfile(cookie_file):
        cookie_file = os.path.join(directories.cookies, service.lower(), "default.txt")
        
    if os.path.isfile(cookie_file):
        cookie_jar = MozillaCookieJar(cookie_file)
        with open(cookie_file, "r+", encoding="utf-8") as fd:
            unescaped = html.unescape(fd.read())
            fd.seek(0)
            fd.truncate()
            fd.write(unescaped)
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
        return cookie_jar
    return None

def get_credentials(service: str, profile: str = "default"):
    """Get the profile's credentials if available."""
    from wpgskd.config import config
    cred = config.credentials.get(service, {})

    if isinstance(cred, dict):
        cred = cred.get(profile)
    elif profile != "default":
        return None

    if cred:
        if isinstance(cred, list):
            return Credential(*cred)
        else:
            return Credential.loads(cred)
    return None

def get_service_key(value):
    value = value.lower()
    for key, aliases in SERVICE_MAP.items():
        if value in map(str.lower, aliases) or value == key.lower():
            return key
    return None