<div align="center">

# 🎬 WPGSKD

### 多媒体研究 · 互操作性测试 · 个人归档工具包

**DASH / HLS / Smooth Streaming 全格式解析 · 智能轨道选择 · 容器封装**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-4CAF50?style=for-the-badge)](./LICENSE)
[![Version](https://img.shields.io/badge/版本-0.2.0-FF9800?style=for-the-badge)]()
[![Platform](https://img.shields.io/badge/平台-Windows%20%7C%20Linux%20%7C%20macOS-2196F3?style=for-the-badge)]()

</div>

---

## ⚖️ 法律声明

> **本项目仅用于教育研究、互操作性测试与个人归档目的。**
>
> - 使用者 **必须** 持有所访问服务的 **有效付费订阅**
> - 本项目 **不托管、不分发、不链接** 任何受版权保护的内容
> - 本项目 **不绕过** 任何技术保护措施，运行依赖合法获取的凭证与环境
> - 使用者需自行遵守所在地区的法律法规及服务提供商的使用条款
> - 作者不对本软件的滥用承担任何责任

---

## 📖 项目简介

WPGSKD 是一个高度模块化的 **流媒体处理框架**，围绕统一管线设计，涵盖从清单解析到最终封装的完整工作流：

```
清单获取 → 轨道解析 → 智能选择 → 下载 → 处理 → MKV 封装
```

核心能力：

| 能力 | 说明 |
|------|------|
| 🔍 **多格式清单解析** | DASH (MPD)、HLS (M3U8)、Smooth Streaming (ISM) 全覆盖 |
| 🎛️ **智能轨道选择** | 按分辨率 / 编码 / 动态范围 / 语言 / 声道多维筛选 |
| 📝 **字幕转换引擎** | WebVTT / TTML / WVTT / ISMT / SAMI → SRT，含 SDH 剥离 |
| 📦 **容器封装** | 自动解密、重打包、MKV 混流、章节嵌入 |
| 🔑 **密钥管理** | 本地 SQLite + 远程 HTTP 双层缓存，自动同步 |

---

## ✨ 功能特性

### 🎬 视频轨道
- 支持 H.264 / H.265 / AV1 / VP9 编码识别
- 动态范围检测：SDR / HDR10 / Dolby Vision / DV+HDR / HLG
- 多码率/分辨率选择，支持 2.39:1 等非标比例智能匹配

### 🔊 音频轨道
- 编码识别：DD+ Atmos / DD+ / DD / AAC / FLAC / DTS / TrueHD
- Dolby Atmos (JOC) 自动检测
- 解说音轨 (Descriptive) 独立标记，不与主音轨混淆
- 多语言智能选择，按编码质量 → 声道 → 码率排序

### 📝 字幕系统
| 输入格式 | 说明 |
|----------|------|
| WebVTT | 含 STYLE 块、X-TIMESTAMP-MAP 处理 |
| TTML / TTML2 / DFXP | 支持 tickRate / frameRate 时间戳 |
| WVTT (MP4 box) | 从 vttc/payl/sttg 提取 |
| ISMT | Smooth Streaming 内嵌字幕 |
| SAMI | 旧版 HTML 字幕 |
| Bilibili JSON | B 站弹幕格式 |

后处理：时间轴修复、空行清理、RTL 修正、SDH 剥离、强制字幕识别

### 🔄 密钥保险库
```
查询链：Local (SQLite) →    HTTP API →    HTTP
           ↑ 命中即返回      ↑ 回写缓存      ↑ 远程读写
```
- 自动缓存已解析的密钥，减少重复请求
- 支持多保险库并发查询、批量导入、数据库合并

---
## 🔧 外部工具

| 工具 | 用途 | 必需 | 下载 |
|------|------|:----:|------|
| aria2c | 多线程分段下载 | ✅ | [aria2.github.io](https://aria2.github.io) |
| N_m3u8DL-RE | HLS/DASH/ISM 下载器 | ✅ | [GitHub](https://github.com/nilaoda/N_m3u8DL-RE) |
| MKVToolNix | MKV 封装 | ✅ | [mkvtoolnix.download](https://mkvtoolnix.download) |
| FFmpeg | 重打包/探测 | ✅ | [ffmpeg.org](https://ffmpeg.org) |
| Bento4 (mp4decrypt) | 处理引擎 | ✅ | [bento4.com](https://www.bento4.com) |
| Shaka Packager | 处理引擎 | 可选 | [GitHub](https://github.com/shaka-project/shaka-packager) |

## 📜 许可证

[Apache License 2.0](./LICENSE)

---

## 🙏 致谢

本项目参考了以下开源项目与标准文档：
- ISO/IEC 14496-12 (ISOBMFF)
- ISO/IEC 23009-1 (MPEG-DASH)
- RFC 8216 (HTTP Live Streaming)
- 开源多媒体研究与处理工具

---

## ⚠️ 最终声明

<div align="center">

**本项目不提供、不托管、不链接任何受版权保护的内容。**

本项目是一个媒体处理研究框架。所有使用均需通过有效订阅合法获取内容。
滥用本软件可能违反您所在地区的法律。

</div>
