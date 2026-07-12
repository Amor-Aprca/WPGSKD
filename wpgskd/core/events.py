import logging
from typing import Callable, Dict, List, Any

log = logging.getLogger("Events")

class EventManager:
    
    _listeners: Dict[str, List[Callable]] = {}

    @classmethod
    def subscribe(cls, event_name: str, callback: Callable):
        if event_name not in cls._listeners:
            cls._listeners[event_name] = []
        cls._listeners[event_name].append(callback)
        log.debug(f"Subscribed to event '{event_name}': {callback.__name__}")

    @classmethod
    def publish(cls, event_name: str, *args, **kwargs) -> Any:
        if event_name not in cls._listeners:
            return None
            
        for callback in cls._listeners[event_name]:
            try:
                result = callback(*args, **kwargs)
                if result is not None:
                    return result
            except Exception as e:
                log.error(f"Error in event listener for '{event_name}': {e}", exc_info=True)
                
        return None

class Events:
    BEFORE_DOWNLOAD = "before_download"
    AFTER_DOWNLOAD = "before_decrypt"
    AFTER_DECRYPT = "after_decrypt"
    BEFORE_MUX = "before_mux"
    AFTER_MUX = "after_mux"