from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator, Sequence

from PIL import Image, UnidentifiedImageError


MEDIA_SUFFIXES = {
    "GIF": ".gif",
    "PNG": ".png",
    "APNG": ".png",
    "WEBP": ".webp",
    "JPEG": ".jpg",
    "BMP": ".bmp",
}
MAX_SCAN_FILES = 1200
MAX_EXTENSION_ARCHIVE_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class Location:
    platform: str
    account_root: Path
    media_root: Path
    label: str
    source: str
    last_activity: float


@dataclass(frozen=True)
class Asset:
    platform: str
    path: Path
    format: str
    width: int | None
    height: int | None
    frames: int
    duration_ms: int | None
    size: int
    modified: float
    readable: bool
    note: str = ""

    @property
    def animated(self) -> bool:
        return self.frames > 1


def _read_head(path: Path, length: int = 32) -> bytes:
    with path.open("rb") as stream:
        return stream.read(length)


def _activity_time(stat: os.stat_result) -> float:
    # On Windows QQ often preserves the source file's old mtime while the
    # creation time records when the cache entry arrived on this computer.
    return max(stat.st_mtime, stat.st_ctime)


def sniff_format(path: Path) -> str | None:
    try:
        head = _read_head(path)
    except (OSError, PermissionError):
        return None
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if head.startswith(b"BM"):
        return "BMP"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    return None


def detect_media(path: Path, platform: str = "") -> Asset:
    stat = path.stat()
    detected = sniff_format(path)
    if not detected:
        return Asset(
            platform=platform,
            path=path,
            format="加密/未知",
            width=None,
            height=None,
            frames=0,
            duration_ms=None,
            size=stat.st_size,
            modified=_activity_time(stat),
            readable=False,
            note="文件不是可直接读取的图片；微信 4.x 缓存通常已加密。",
        )

    width = height = None
    frames = 1
    duration_ms = None
    rendered_format = detected
    try:
        with Image.open(path) as image:
            width, height = image.size
            frames = int(getattr(image, "n_frames", 1))
            durations: list[int] = []
            if frames > 1:
                for index in range(frames):
                    image.seek(index)
                    durations.append(int(image.info.get("duration", 0)))
                duration_ms = sum(durations)
            if detected == "PNG" and frames > 1:
                rendered_format = "APNG"
    except (OSError, ValueError, UnidentifiedImageError):
        pass

    return Asset(
        platform=platform,
        path=path,
        format=rendered_format,
        width=width,
        height=height,
        frames=frames,
        duration_ms=duration_ms,
        size=stat.st_size,
        modified=_activity_time(stat),
        readable=True,
    )


def _logical_drives() -> list[Path]:
    if os.name != "nt":
        return [Path("/")]
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    drives = []
    for index in range(26):
        if mask & (1 << index):
            drives.append(Path(f"{chr(65 + index)}:\\"))
    return drives


def _safe_children(path: Path) -> list[Path]:
    try:
        return [item for item in path.iterdir() if item.is_dir()]
    except (OSError, PermissionError):
        return []


def _walk_dirs_limited(root: Path, max_depth: int, max_dirs: int = 3000) -> Iterator[Path]:
    if not root.is_dir():
        return
    queue: list[tuple[Path, int]] = [(root, 0)]
    visited = 0
    while queue and visited < max_dirs:
        current, depth = queue.pop(0)
        visited += 1
        yield current
        if depth >= max_depth:
            continue
        for child in _safe_children(current):
            queue.append((child, depth + 1))


def _latest_mtime(path: Path, max_files: int = 300) -> float:
    latest = 0.0
    seen = 0
    try:
        for item in path.rglob("*"):
            if seen >= max_files:
                break
            if item.is_file():
                seen += 1
                try:
                    latest = max(latest, _activity_time(item.stat()))
                except OSError:
                    continue
    except (OSError, PermissionError):
        return latest
    return latest


def _mask_account(name: str) -> str:
    value = str(name)
    if len(value) <= 6:
        return value
    return f"{value[:3]}…{value[-3:]}"


def _dedupe_locations(locations: Iterable[Location]) -> list[Location]:
    result: dict[str, Location] = {}
    for item in locations:
        key = os.path.normcase(str(item.media_root.resolve()))
        existing = result.get(key)
        if existing is None or item.last_activity > existing.last_activity:
            result[key] = item
    return sorted(result.values(), key=lambda item: item.last_activity, reverse=True)


def discover_qq_locations(
    *,
    home: Path | None = None,
    drives: Sequence[Path] | None = None,
    extra_roots: Sequence[Path] = (),
) -> list[Location]:
    user_home = home or Path.home()
    drive_roots = list(drives) if drives is not None else _logical_drives()
    candidates: list[tuple[Path, str]] = []
    standard_bases = [
        user_home / "Documents" / "Tencent Files",
        user_home / "Documents" / "QQ Files",
        user_home / "AppData" / "Roaming" / "Tencent" / "QQ",
    ]
    for drive in drive_roots:
        standard_bases.extend([drive / "Tencent Files", drive / "QQ Files"])
    standard_bases.extend(extra_roots)

    for base in standard_bases:
        for folder in _walk_dirs_limited(base, max_depth=7):
            if folder.name.casefold() != "emoji":
                continue
            if folder.parent.name.casefold() != "nt_data":
                continue
            if folder.parent.parent.name.casefold() != "nt_qq":
                continue
            account_root = folder.parent.parent.parent
            candidates.append((folder, "自动发现"))

    locations = []
    for media_root, source in candidates:
        account_root = media_root.parent.parent.parent
        locations.append(
            Location(
                platform="QQ",
                account_root=account_root,
                media_root=media_root,
                label=f"QQ · {_mask_account(account_root.name)}",
                source=source,
                last_activity=_latest_mtime(media_root),
            )
        )
    return _dedupe_locations(locations)


def _extract_wechat_process_roots() -> list[Path]:
    if os.name != "nt":
        return []
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_Process | "
        "Where-Object {$_.Name -in @('Weixin.exe','WeChatAppEx.exe')} | "
        "Select-Object -ExpandProperty CommandLine | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        raw = completed.stdout.strip()
        if not raw:
            return []
        lines = json.loads(raw)
        if isinstance(lines, str):
            lines = [lines]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []

    roots = []
    pattern = re.compile(r'--wechat-files-path=(?:"([^"]+)"|([^\s]+))', re.IGNORECASE)
    for line in lines:
        match = pattern.search(str(line or ""))
        if match:
            roots.append(Path(match.group(1) or match.group(2)))
    return roots


def _wechat_config_roots(home: Path) -> list[Path]:
    roots: list[Path] = []
    config_paths = [
        home / "AppData/Roaming/Tencent/WeChat/All Users/config/3ebffe94.ini",
        home / "AppData/Roaming/Tencent/xwechat/all_users/config/3ebffe94.ini",
    ]
    for config in config_paths:
        try:
            value = config.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        if not value:
            continue
        if re.fullmatch(r"[A-Za-z]:", value):
            value += "\\"
        path = Path(value)
        roots.extend([path, path / "xwechat_files"])
    return roots


def _wechat_account_locations(root: Path, source: str) -> list[Location]:
    locations = []
    if not root.is_dir():
        return locations
    for account in _safe_children(root):
        has_business = (account / "business" / "emoticon").is_dir()
        has_cache = (account / "cache").is_dir()
        if not (has_business or has_cache):
            continue
        media_root = account
        locations.append(
            Location(
                platform="微信",
                account_root=account,
                media_root=media_root,
                label=f"微信 · {_mask_account(account.name)}",
                source=source,
                last_activity=max(
                    _latest_mtime(account / "business" / "emoticon"),
                    _latest_mtime(account / "cache"),
                ),
            )
        )
    return locations


def discover_wechat_locations(
    *,
    home: Path | None = None,
    drives: Sequence[Path] | None = None,
    process_roots: Sequence[Path] | None = None,
    extra_roots: Sequence[Path] = (),
) -> list[Location]:
    user_home = home or Path.home()
    drive_roots = list(drives) if drives is not None else _logical_drives()
    candidates: list[tuple[Path, str]] = []

    running_roots = (
        list(process_roots) if process_roots is not None else _extract_wechat_process_roots()
    )
    candidates.extend((path, "运行进程") for path in running_roots)
    candidates.extend((path, "客户端配置") for path in _wechat_config_roots(user_home))
    candidates.extend(
        [
            (user_home / "Documents" / "WeChat Files", "标准目录"),
            (user_home / "Documents" / "xwechat_files", "标准目录"),
        ]
    )
    for drive in drive_roots:
        candidates.extend(
            [
                (drive / "xwechat_files", "盘符扫描"),
                (drive / "WeChat Files", "盘符扫描"),
            ]
        )
    candidates.extend((path, "手动目录") for path in extra_roots)

    locations: list[Location] = []
    for root, source in candidates:
        if (root / "business" / "emoticon").is_dir():
            locations.extend(_wechat_account_locations(root.parent, source))
        else:
            locations.extend(_wechat_account_locations(root, source))
    return _dedupe_locations(locations)


def _recent_files(roots: Iterable[Path], limit: int) -> list[Path]:
    rows: list[tuple[float, Path]] = []
    seen = 0
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*"):
                if seen >= MAX_SCAN_FILES:
                    break
                if not path.is_file():
                    continue
                seen += 1
                try:
                    rows.append((_activity_time(path.stat()), path))
                except OSError:
                    continue
        except (OSError, PermissionError):
            continue
    rows.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in rows[:limit]]


def scan_qq(location: Location, limit: int = 120) -> list[Asset]:
    personal_originals = location.media_root / "personal_emoji" / "Ori"
    if not personal_originals.is_dir():
        return []
    return [
        detect_media(path, "QQ")
        for path in _recent_files([personal_originals], limit)
    ]


def scan_wechat(location: Location, limit: int = 120) -> list[Asset]:
    roots = [
        location.account_root / "business" / "emoticon" / "Persist",
        location.account_root / "cache",
    ]
    files = [
        path
        for path in _recent_files(roots, limit * 3)
        if "emoticon" in str(path).casefold()
    ][:limit]
    return [detect_media(path, "微信") for path in files]


def scan_douyin(download_root: Path, limit: int = 120) -> list[Asset]:
    files = _recent_files([download_root], limit * 2)
    assets = [detect_media(path, "抖音网页") for path in files]
    return [asset for asset in assets if asset.readable][:limit]


def scan_local_folder(
    folder: Path,
    platform: str,
    limit: int = 120,
) -> list[Asset]:
    files = _recent_files([folder], limit * 2)
    assets = [detect_media(path, platform) for path in files]
    return [asset for asset in assets if asset.readable][:limit]


def extract_extension_bundle(archive_path: Path, destination_root: Path) -> Path:
    """Safely extract only emoji-bridge-extension from a GitHub source archive."""
    destination_root.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".emoji-bridge-extension-", dir=destination_root)
    )
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) > 500:
                raise ValueError("扩展压缩包文件数量异常。")
            if sum(item.file_size for item in members) > MAX_EXTENSION_ARCHIVE_BYTES:
                raise ValueError("扩展压缩包解压后超过 50 MB。")

            extracted = 0
            for item in members:
                parts = PurePosixPath(item.filename).parts
                try:
                    marker = parts.index("emoji-bridge-extension")
                except ValueError:
                    continue
                relative_parts = parts[marker + 1 :]
                if not relative_parts or any(part in ("", ".", "..") for part in relative_parts):
                    continue
                target = staging.joinpath(*relative_parts)
                if not target.resolve().is_relative_to(staging.resolve()):
                    raise ValueError("扩展压缩包包含不安全路径。")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                extracted += 1

        manifest_path = staging / "manifest.json"
        if not extracted or not manifest_path.is_file():
            raise ValueError("压缩包中没有找到 emoji-bridge-extension。")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("manifest_version") != 3 or not manifest.get("name"):
            raise ValueError("扩展 manifest.json 未通过验证。")

        target = destination_root / "emoji-bridge-extension"
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = destination_root / f"emoji-bridge-extension-{stamp}"
            counter = 2
            while target.exists():
                target = destination_root / f"emoji-bridge-extension-{stamp}-{counter}"
                counter += 1
        staging.replace(target)
        return target
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_asset(asset: Asset, library_dir: Path) -> Path:
    if not asset.readable:
        raise ValueError("该缓存仍是加密/未知格式，不能导出。")
    library_dir.mkdir(parents=True, exist_ok=True)
    suffix = MEDIA_SUFFIXES.get(asset.format, asset.path.suffix.lower() or ".bin")
    stamp = datetime.fromtimestamp(asset.modified).strftime("%Y%m%d-%H%M%S")
    platform = {"QQ": "qq", "微信": "wechat", "抖音网页": "douyin"}.get(
        asset.platform, "emoji"
    )
    dimensions = (
        f"_{asset.width}x{asset.height}" if asset.width and asset.height else ""
    )
    frames = f"_{asset.frames}f" if asset.frames > 1 else ""
    digest = _sha256(asset.path)
    target = library_dir / f"{platform}_{stamp}{dimensions}{frames}_{digest[:8]}{suffix}"
    if target.exists():
        if _sha256(target) == digest:
            return target
        counter = 2
        while target.exists():
            target = target.with_stem(f"{target.stem}_{counter}")
            counter += 1
    shutil.copy2(asset.path, target)
    if _sha256(target) != digest:
        target.unlink(missing_ok=True)
        raise OSError("复制后的文件校验失败。")
    return target


def prepare_for_wechat(
    asset: Asset,
    output_dir: Path,
    *,
    max_dimension: int = 240,
    max_bytes: int = 1024 * 1024,
) -> Path:
    """Create a conservative WeChat custom-sticker file.

    Animated assets are converted to GIF and iteratively reduced while keeping
    the original timing. Static assets become PNG at no more than 240 px on
    their longest side. The source file is never modified.
    """
    if not asset.readable:
        raise ValueError("该缓存仍是加密/未知格式，不能生成微信兼容版。")
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = _sha256(asset.path)

    if asset.animated:
        target = output_dir / f"wechat_{digest[:12]}.gif"
        if target.exists():
            existing = detect_media(target, "微信兼容")
            if (
                existing.readable
                and existing.animated
                and existing.size <= max_bytes
                and max(existing.width or 0, existing.height or 0) <= max_dimension
            ):
                return target
        _write_wechat_gif(asset.path, target, max_dimension, max_bytes)
    else:
        target = output_dir / f"wechat_{digest[:12]}.png"
        if not target.exists():
            temporary = target.with_suffix(".tmp.png")
            with Image.open(asset.path) as image:
                frame = image.convert("RGBA")
                frame.thumbnail(
                    (max_dimension, max_dimension), Image.Resampling.LANCZOS
                )
                frame.save(temporary, format="PNG", optimize=True)
            temporary.replace(target)

    prepared = detect_media(target, "微信兼容")
    if not prepared.readable:
        raise OSError("生成的微信兼容文件无法重新解码。")
    if asset.animated and not prepared.animated:
        raise OSError("生成文件丢失了动画。")
    if max(prepared.width or 0, prepared.height or 0) > max_dimension:
        raise OSError("生成文件尺寸超过微信兼容目标。")
    if prepared.size > max_bytes:
        raise OSError(
            f"生成文件仍有 {prepared.size / 1024 / 1024:.2f} MB，超过 1 MB 兼容目标。"
        )
    return target


def _write_wechat_gif(
    source: Path, target: Path, max_dimension: int, max_bytes: int
) -> None:
    frames: list[Image.Image] = []
    durations: list[int] = []
    with Image.open(source) as image:
        frame_count = int(getattr(image, "n_frames", 1))
        for index in range(frame_count):
            image.seek(index)
            frame = image.convert("RGBA")
            frame.thumbnail(
                (max_dimension, max_dimension), Image.Resampling.LANCZOS
            )
            frames.append(frame.copy())
            durations.append(max(20, int(image.info.get("duration", 100))))

    if len(frames) < 2:
        raise ValueError("输入文件没有可保留的动画帧。")

    strategies = [
        (1, 128),
        (1, 96),
        (1, 64),
        (2, 96),
        (2, 64),
        (3, 64),
        (4, 48),
    ]
    temporary = target.with_suffix(".tmp.gif")
    best: bytes | None = None
    for step, colors in strategies:
        selected: list[Image.Image] = []
        selected_durations: list[int] = []
        for start in range(0, len(frames), step):
            group = frames[start : start + step]
            selected.append(_quantize_gif_frame(group[0], colors))
            selected_durations.append(sum(durations[start : start + step]))
        if len(selected) < 2:
            continue
        selected[0].save(
            temporary,
            format="GIF",
            save_all=True,
            append_images=selected[1:],
            duration=selected_durations,
            loop=0,
            optimize=False,
            disposal=2,
            transparency=255,
        )
        candidate = temporary.read_bytes()
        if best is None or len(candidate) < len(best):
            best = candidate
        if len(candidate) <= max_bytes:
            best = candidate
            break

    temporary.unlink(missing_ok=True)
    if best is None:
        raise OSError("无法生成微信兼容 GIF。")
    temporary.write_bytes(best)
    temporary.replace(target)


def _quantize_gif_frame(frame: Image.Image, colors: int) -> Image.Image:
    rgba = frame.convert("RGBA")
    alpha = rgba.getchannel("A")
    quantized = rgba.convert("RGB").quantize(
        colors=min(254, colors),
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.FLOYDSTEINBERG,
    )
    transparent_mask = alpha.point(lambda value: 255 if value < 128 else 0)
    quantized.paste(255, mask=transparent_mask)
    palette = quantized.getpalette() or []
    palette.extend([0] * (768 - len(palette)))
    palette[255 * 3 : 255 * 3 + 3] = [0, 0, 0]
    quantized.putpalette(palette[:768])
    quantized.info["transparency"] = 255
    return quantized
