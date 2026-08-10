<div align="left">

**English** | [简体中文](./README_CN.md)

</div>

---

# WPGSKD

**Multimedia Research, Interoperability & Archival Toolkit**

> Widevine · PlayReady · AES-128 · ClearKey — Manifest Parsing · Track Selection · Container Muxing

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green)](./LICENSE)
[![Version](https://img.shields.io/badge/Version-0.2.0-orange)]()

---

## ⚖️ Legal Disclaimer

This software is provided for **educational and interoperability research purposes only**.

- You **must** possess a valid, paid subscription to any service you interact with.
- The authors do **not** host, distribute, or facilitate access to any copyrighted content.
- This tool does **not** circumvent any technological protection measure on its own; it requires
  legally obtained credentials and a properly licensed environment.
- Users are solely responsible for complying with the Terms of Service of their providers
  and all applicable local laws.
- The authors assume no liability for misuse of this software.

By using this software you acknowledge and agree to the above.

---

## 📖 Overview

WPGSKD is a modular multimedia processing framework designed for **streaming media research,
interoperability testing, and personal archival**. It provides a unified pipeline for:

- **Manifest parsing** — DASH (MPD), HLS (M3U8), and Smooth Streaming (ISM)
- **Track analysis & selection** — video, audio, subtitles, and chapters
- **Container processing** — decryption, repackaging, and MKV muxing
- **Subtitle conversion** — WebVTT, TTML/DFXP, WVTT, ISMT, SAMI → SRT

The framework is built around a clean, extensible service-provider architecture, making it
straightforward to add support for new content sources.

---

## ✨ Features

### Manifest Parsing
| Format | Details |
|--------|---------|
| **DASH / MPD** | Multi-period support, ContentProtection extraction, HDR/DV metadata, FPS calculation from SegmentTimeline |
| **HLS / M3U8** | Variant playlists, EXT-X-SESSION-KEY, SAMPLE-AES detection |
| **Smooth Streaming (ISM)** | QualityLevel parsing, fragment URL construction, FPS probing from raw moof/trun boxes |

### Track Selection
- **Video**: resolution, codec (H.264/H.265/AV1/VP9), dynamic range (SDR/HDR10/DV/DV+HDR/HLG), bitrate
- **Audio**: language (BCP-47), codec (DD+/Atmos/DD/AAC/FLAC/DTS/TrueHD), channels, Atmos detection, descriptive track handling
- **Subtitles**: language, type (normal/SDH/Forced), multi-format conversion to SRT
- **Chapters**: automatic chapter extraction and muxing

### Sorting & Display
- Video: grouped by dynamic range → codec → resolution → bitrate
- Audio: grouped by language (A-Z) → codec quality → channels → bitrate
- Subtitles: grouped by language (A-Z, letter subtags before numeric) → type (normal → SDH → Forced)

### Subtitle Processing
- Format converters: WebVTT, TTML/TTML2/DFXP, WVTT (MP4 box), ISMT, SAMI, Bilibili JSON
- Post-processing: common issue fixing, SDH stripping, RTL correction, gap removal
- Output: clean UTF-8 SRT with optional SSA positioning tags

### Key Management
- **Local vault**: SQLite-based, multi-table (one per service), thread-safe via AtomicSQL
- **Remote vaults**: HTTP API and HTTP (read/write) support
- **Automatic caching**: resolved keys are stored for future use across all configured vaults
- **Import/export**: batch key import, vault merging, migration tools

---

## 🔧 External Tools

| Tool | Purpose | Required |
|------|---------|----------|
| [aria2c](https://aria2.github.io) | Segment downloader | ✅ |
| [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE) | HLS/DASH/ISM downloader | ✅ |
| [MKVToolNix](https://mkvtoolnix.download) | MKV muxing | ✅ |
| [FFmpeg](https://ffmpeg.org) | Repackaging / probing | ✅ |
| [Bento4](https://www.bento4.com) | mp4decrypt | ✅ |
| [Shaka Packager](https://github.com/shaka-project/shaka-packager) | Raw-key decryption | Optional |

---

## 📜 License

Licensed under the **Apache License 2.0**. See [`LICENSE`](./LICENSE).

---

## 🙏 Credits

Built with reference to open-source multimedia research projects and standards documentation
including ISO/IEC 14496-12 (ISOBMFF), MPEG-DASH (ISO/IEC 23009-1), and HLS (RFC 8216).

---

## ⚠️ Final Notice

**This project does not provide, host, or link to any copyrighted content.**
It is a framework for media processing research. All usage requires legitimate
access to the content through valid subscriptions. Misuse of this software
may violate laws in your jurisdiction.
