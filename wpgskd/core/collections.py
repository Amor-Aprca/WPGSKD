import itertools
from typing import Iterable, Sequence

class CaseInsensitiveDict(dict):
    """A dictionary with case-insensitive keys."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for k in self.keys():
            if not isinstance(k, (str, bytes)):
                raise ValueError(f"dictionary keys must be str or bytes, not {type(k)}")

    def _resolve_key(self, key):
        if not isinstance(key, (str, bytes)):
            raise ValueError(f"dictionary keys must be str or bytes, not {type(key)}")
        return next((x for x in self.keys() if x.casefold() == key.casefold()), key)

    def __contains__(self, key): return super().__contains__(self._resolve_key(key))
    def __getitem__(self, key): return super().__getitem__(self._resolve_key(key))
    def __setitem__(self, key, value): return super().__setitem__(self._resolve_key(key), value)
    def get(self, key, default=None): return super().get(self._resolve_key(key), default)
    def pop(self, key): return super().pop(self._resolve_key(key))
    def setdefault(self, key, value=None): return super().setdefault(self._resolve_key(key), value)

def as_lists(*args):
    for item in args:
        yield item if isinstance(item, list) else [item]

def as_list(*args):
    if args == (None,): return []
    return list(itertools.chain.from_iterable(as_lists(*args)))

def first(iterable): return next(iter(iterable))
def first_or_else(iterable, default):
    item = next(iter(iterable or []), None)
    return default if item is None else item
def first_or_none(iterable): return first_or_else(iterable, None)

def flatten(items, ignore_types=str):
    if isinstance(items, (Iterable, Sequence)) and not isinstance(items, ignore_types):
        for i in items:
            yield from flatten(i, ignore_types)
    else:
        yield items

def merge_dict(*dicts):
    """Recursively merge dicts into dest in-place."""
    dest = dicts[0]
    for d in dicts[1:]:
        for key, value in d.items():
            if isinstance(value, dict):
                node = dest.setdefault(key, {})
                merge_dict(node, value)
            else:
                dest[key] = value