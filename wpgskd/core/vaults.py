import logging
from typing import Optional, Tuple, List, Type

from wpgskd.core.vault import BaseVault, LocalVault, HTTPAPIVault

log = logging.getLogger("Vaults")

class Vaults:    
    VAULT_TYPES = {
        "local": LocalVault,
        "httpapi": HTTPAPIVault,
    }

    def __init__(self, vaults_list: list, service: str):
        self.vaults: List[BaseVault] = []
        self.service = service.lower()
        
        for v in vaults_list:
            try:
                if isinstance(v, BaseVault):
                    vault = v
                else:
                    v_type = v.get("type", "").lower()
                    v_name = v.get("name", v_type)
                    vault_cls = self.VAULT_TYPES.get(v_type)
                    if not vault_cls:
                        log.warning(f"Unsupported vault type '{v_type}' for '{v_name}', skipping.")
                        continue
                    
                    cfg_copy = {k: val for k, val in v.items() if k not in ["type", "name"]}
                    vault = vault_cls(name=v_name, **cfg_copy)
                
                if isinstance(vault, LocalVault):
                    vault.create_table(self.service)
                    
                self.vaults.append(vault)
            except Exception as e:
                v_name = v.name if isinstance(v, BaseVault) else v.get('name')
                log.error(f"Failed to init vault {v_name}: {e}")
        
        self.vaults.sort(key=lambda v: 0 if isinstance(v, LocalVault) else 1)

    def get(self, kid: str, title_id: str = "") -> Tuple[Optional[str], Optional[BaseVault]]:
        for v in self.vaults:
            key = v.get_key(self.service, kid, title_id)
            if key:
                log.debug(f"Key {kid} found in vault {v.name}")
                return key, v
        return None, None

    def insert(self, kid: str, key: str, title_id: str = "") -> None:
        for v in self.vaults:
            try:
                res = v.insert_key(self.service, kid, key, title_id)
                if res.name == "SUCCESS":
                    log.debug(f"Inserted key to vault {v.name}")
            except Exception as e:
                log.warning(f"Failed to insert key to vault {v.name}: {e}")

    @staticmethod
    def load_vault(vault_cfg: dict) -> BaseVault:
        v_type = vault_cfg.get("type", "").lower()
        v_name = vault_cfg.get("name", v_type)
        no_push = vault_cfg.get("no_push", False)
        
        cfg_copy = {k: v for k, v in vault_cfg.items() if k not in ["type", "name", "no_push"]}
        
        vault_cls = Vaults.VAULT_TYPES.get(v_type)
        if not vault_cls:
            raise ValueError(f"Unknown vault type: {v_type}")
            
        return vault_cls(name=v_name, **cfg_copy)