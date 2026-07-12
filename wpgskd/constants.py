from enum import Enum

class EncryptionScheme(Enum):
    NONE = "none"
    WIDEVINE = "widevine"
    PLAYREADY = "playready"
    CLEARKEY = "clearkey"
    AES_128 = "aes-128"
    AES_128_ECB = "aes-128-ecb"
    SAMPLE_AES = "SAMPLE-AES"

LANGUAGE_MUX_MAP = {
    "none": "und",
    "nb": "nor",
}

TERRITORY_MAP = {
    "001": "",
    "150": "European",
    "419": "Latin American",
    "AU": "Australian",
    "BE": "Flemish",
    "BR": "Brazilian",
    "CA": "Canadian",
    "CZ": "",
    "CN": "Chinese Mainland",
    "DK": "",
    "EG": "Egyptian",
    "ES": "European",
    "FR": "European",
    "GB": "British",
    "GR": "",
    "HK": "Hong Kong",
    "IL": "",
    "IN": "",
    "JP": "Japan",
    "KR": "",
    "MY": "",
    "NO": "",
    "PH": "",
    "PS": "Palestinian",
    "PT": "European",
    "SE": "",
    "SY": "Syrian",
    "TW": "Taiwan",
    "US": "American",
}

LANGUAGE_MAX_DISTANCE = 5

CODEC_MAP = {
    "avc1": "H.264", "avc3": "H.264", "hev1": "H.265", "hvc1": "H.265", "dvh1": "H.265", "dvhe": "H.265", "av01": "AV1",
    "aac": "AAC", "mp4a": "AAC", "stereo": "AAC", "HE": "HE-AAC", "ac3": "AC3", "ac-3": "AC3", "dd": "DD",
    "eac": "E-AC3", "eac3": "E-AC3", "eac-3": "E-AC3", "ec-3": "DD+", "ddp": "DD+", "dd+": "DD+", "atmos": "DD+ Atmos", "ec3": "DD+",
    "srt": "SRT", "vtt": "VTT", "wvtt": "WVTT", "dfxp": "TTML", "stpp": "TTML", "ttml": "TTML", "tt": "TTML", "ass": "ASS", "ssa": "SSA",
}