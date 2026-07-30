from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Iterator, Sequence

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
MAX_DRIVE_SCAN_DEPTH = 7
MAX_DRIVE_SCAN_DIRS = 400


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
    # QQ often keeps the source mtime. On Windows ctime is the time the cache
    # reached this computer, so the newer value is the useful activity signal.
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
            format="未知",
            width=None,
            height=None,
            frames=0,
            duration_ms=None,
            size=stat.st_size,
            modified=_activity_time(stat),
            readable=False,
            note="文件不是受支持的静态或动态图片，已跳过导出。",
        )

    width = height = None
    frames = 1
    duration_ms = None
    rendered_format = detected
    try:
        with Image.open(path) as image:
            width, height = image.size
            frames = int(getattr(image, "n_frames", 1))
            if frames > 1:
                durations: list[int] = []
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


def list_local_drives() -> list[Path]:
    """Return ready fixed/removable local disks that may contain QQ data."""
    if os.name != "nt":
        return [Path("/")]

    mask = ctypes.windll.kernel32.GetLogicalDrives()
    drives: list[Path] = []
    for index in range(26):
        if not mask & (1 << index):
            continue
        root = Path(f"{chr(65 + index)}:\\")
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(root))
        if drive_type not in (2, 3):  # removable or fixed; skip network/CD/RAM
            continue
        try:
            if root.is_dir():
                drives.append(root)
        except OSError:
            continue
    return drives


_SCAN_SKIP_NAMES = {
    "$recycle.bin",
    "system volume information",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
}
_SCAN_PRIORITY_PARTS = (
    "qq",
    "tencent",
    "file",
    "data",
    "chat",
    "user",
    "document",
    "消息",
    "聊天",
    "文件",
    "数据",
)


def _safe_children(path: Path, *, prune: bool = False) -> list[Path]:
    children: list[Path] = []
    try:
        entries = path.iterdir()
        for item in entries:
            try:
                if prune and item.name.casefold() in _SCAN_SKIP_NAMES:
                    continue
                if not item.is_dir() or item.is_symlink():
                    continue
                is_junction = getattr(item, "is_junction", None)
                if callable(is_junction) and is_junction():
                    continue
                children.append(item)
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError):
        return []
    if prune:
        children.sort(
            key=lambda item: (
                0
                if any(part in item.name.casefold() for part in _SCAN_PRIORITY_PARTS)
                else 1,
                item.name.casefold(),
            )
        )
    return children


def _walk_dirs_limited(
    root: Path,
    max_depth: int,
    max_dirs: int = 3000,
    *,
    prune: bool = False,
) -> Iterator[Path]:
    try:
        if not root.is_dir():
            return
    except OSError:
        return

    pending: deque[tuple[Path, int]] = deque([(root, 0)])
    visited = 0
    while pending and visited < max_dirs:
        current, depth = pending.popleft()
        visited += 1
        yield current
        if depth >= max_depth:
            continue
        for child in _safe_children(current, prune=prune):
            pending.append((child, depth + 1))


def _latest_mtime(path: Path, max_files: int = 300) -> float:
    latest = 0.0
    seen = 0
    try:
        for item in path.rglob("*"):
            if seen >= max_files:
                break
            if not item.is_file():
                continue
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
        try:
            key = os.path.normcase(str(item.media_root.resolve()))
        except OSError:
            key = os.path.normcase(str(item.media_root))
        existing = result.get(key)
        if existing is None or item.last_activity > existing.last_activity:
            result[key] = item
    return sorted(result.values(), key=lambda item: item.last_activity, reverse=True)


def _drive_name(path: Path) -> str:
    return path.drive or path.name or str(path)


def discover_qq_locations(
    *,
    home: Path | None = None,
    drives: Sequence[Path] | None = None,
    extra_roots: Sequence[Path] = (),
) -> list[Location]:
    """Discover validated QQ NT accounts on every ready local disk.

    Common QQ locations are searched first. Each disk then gets a bounded
    structural scan for ``nt_qq/nt_data/Emoji`` so custom data folders are
    supported without turning application startup into an unbounded crawl.
    """

    user_home = home or Path.home()
    drive_roots = list(drives) if drives is not None else list_local_drives()
    candidates: list[tuple[Path, str]] = []
    standard_bases: list[tuple[Path, str]] = [
        (user_home / "Documents" / "Tencent Files", "用户目录"),
        (user_home / "Documents" / "QQ Files", "用户目录"),
        (user_home / "AppData" / "Roaming" / "Tencent" / "QQ", "用户目录"),
    ]
    for drive in drive_roots:
        drive_name = _drive_name(drive)
        standard_bases.extend(
            [
                (drive / "Tencent Files", f"{drive_name} 常见位置"),
                (drive / "QQ Files", f"{drive_name} 常见位置"),
            ]
        )
    standard_bases.extend((root, "手动位置") for root in extra_roots)

    def collect(
        base: Path,
        source: str,
        *,
        max_depth: int,
        max_dirs: int,
        prune: bool,
    ) -> None:
        for folder in _walk_dirs_limited(
            base,
            max_depth=max_depth,
            max_dirs=max_dirs,
            prune=prune,
        ):
            if folder.name.casefold() != "emoji":
                continue
            if folder.parent.name.casefold() != "nt_data":
                continue
            if folder.parent.parent.name.casefold() != "nt_qq":
                continue
            candidates.append((folder, source))

    for base, source in standard_bases:
        collect(base, source, max_depth=7, max_dirs=4000, prune=False)

    for drive in drive_roots:
        drive_name = _drive_name(drive)
        collect(
            drive,
            f"{drive_name} 盘扫描",
            max_depth=MAX_DRIVE_SCAN_DEPTH,
            max_dirs=MAX_DRIVE_SCAN_DIRS,
            prune=True,
        )

    locations: list[Location] = []
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
    """Read only QQ's personal “喜欢” originals, never the chat cache."""
    personal_originals = location.media_root / "personal_emoji" / "Ori"
    if not personal_originals.is_dir():
        return []
    return [
        detect_media(path, "QQ")
        for path in _recent_files([personal_originals], limit)
    ]


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
                if not relative_parts or any(
                    part in ("", ".", "..") for part in relative_parts
                ):
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


def copy_extension_bundle(
    source_root: Path,
    destination_root: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Copy and validate the bundled extension without touching the source."""
    manifest_path = source_root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("项目内没有找到 emoji-bridge-extension/manifest.json。")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != 3 or not manifest.get("name"):
        raise ValueError("项目内置扩展 manifest.json 未通过验证。")

    files = [
        path
        for path in source_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    if len(files) > 500:
        raise ValueError("项目内置扩展文件数量异常。")
    total = sum(path.stat().st_size for path in files)
    if total > MAX_EXTENSION_ARCHIVE_BYTES:
        raise ValueError("项目内置扩展超过 50 MB。")

    destination_root.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".emoji-bridge-extension-", dir=destination_root)
    )
    copied = 0
    try:
        for source in files:
            relative = source.relative_to(source_root)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as source_stream, target.open("wb") as target_stream:
                while True:
                    chunk = source_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    target_stream.write(chunk)
                    copied += len(chunk)
                    if progress:
                        progress(copied, total)

        copied_manifest = json.loads(
            (staging / "manifest.json").read_text(encoding="utf-8")
        )
        if (
            copied_manifest.get("manifest_version") != 3
            or copied_manifest.get("version") != manifest.get("version")
        ):
            raise ValueError("复制后的扩展 manifest.json 校验失败。")

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
        raise ValueError("该文件格式无法识别，不能导出。")
    library_dir.mkdir(parents=True, exist_ok=True)
    suffix = MEDIA_SUFFIXES.get(asset.format, asset.path.suffix.lower() or ".bin")
    stamp = datetime.fromtimestamp(asset.modified).strftime("%Y%m%d-%H%M%S")
    dimensions = (
        f"_{asset.width}x{asset.height}" if asset.width and asset.height else ""
    )
    frames = f"_{asset.frames}f" if asset.frames > 1 else ""
    digest = _sha256(asset.path)
    target = library_dir / f"qq_{stamp}{dimensions}{frames}_{digest[:8]}{suffix}"
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
