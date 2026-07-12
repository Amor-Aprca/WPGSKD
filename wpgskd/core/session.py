import logging
from typing import Optional, Dict, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("Session")

class SessionBuilder:

    @staticmethod
    def build(
        headers: Optional[Dict[str, str]] = None,
        retries: int = 5,
        backoff_factor: int = 1,
        status_forcelist: Optional[list] = None,
        raise_on_error: bool = True
    ) -> requests.Session:
        if status_forcelist is None:
            status_forcelist = [429, 500, 502, 503, 504]

        session = requests.Session()
        
        retry_strategy = Retry(
            total=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
            allowed_methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        if headers:
            session.headers.update(headers)

        if raise_on_error:
            session.hooks = {
                "response": lambda r, *args, **kwargs: r.raise_for_status()
            }

        return session

    @staticmethod
    def build_hybrid(
        headers: Optional[Dict[str, str]] = None,
        impersonate: str = "chrome120",
        verify: bool = False
    ) -> Any:
        try:
            from curl_cffi import requests as curl_requests
            import requests as std_requests
        except ImportError:
            log.warning("curl_cffi is not installed. Falling back to standard requests.")
            return SessionBuilder.build(headers=headers)

        class HybridSession:
            def __init__(self, hdrs, imp, vfy):
                self.curl = curl_requests.Session(impersonate=imp, verify=vfy)
                self.std = std_requests.Session()
                
                if hdrs:
                    self.curl.headers.update(hdrs)
                    self.std.headers.update(hdrs)
                    
                self.headers = self.curl.headers
                self.cookies = self.curl.cookies
                self.proxies = {} 

            def _sync_std_session(self):
                for k, v in self.curl.headers.items():
                    self.std.headers[k] = v

            def get(self, url, **kwargs):
                if kwargs.get('stream'):
                    self._sync_std_session()
                    return self.std.get(url, **kwargs)
                return self.curl.get(url, **kwargs)

            def post(self, url, **kwargs):
                if kwargs.get('stream'):
                    self._sync_std_session()
                    return self.std.post(url, **kwargs)
                return self.curl.post(url, **kwargs)

            def put(self, url, **kwargs):
                return self.curl.put(url, **kwargs)
                
            def delete(self, url, **kwargs):
                return self.curl.delete(url, **kwargs)

            def __getattr__(self, name):
                return getattr(self.curl, name)

        return HybridSession(headers, impersonate, verify)