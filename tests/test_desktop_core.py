from __future__ import annotations

import zipfile
from pathlib import Path

from PIL import Image

import emoji_bridge.app as app_module
from emoji_bridge.core import (
    Location,
    copy_extension_bundle,
    detect_media,
    discover_qq_locations,
    export_asset,
    extract_extension_bundle,
    scan_qq,
)


def test_launches_chrome_without_blocked_internal_page_argument(
    monkeypatch,
    tmp_path: Path,
) -> None:
    chrome = tmp_path / "chrome.exe"
    chrome.touch()
    calls: list[tuple[list[str], object, object]] = []
    monkeypatch.setattr(app_module, "find_chrome_executable", lambda: chrome)
    monkeypatch.setattr(
        app_module.subprocess,
        "Popen",
        lambda args, stdout, stderr: calls.append((args, stdout, stderr)),
    )

    opened = app_module.launch_chrome()

    assert opened
    assert calls == [
        (
            [str(chrome)],
            app_module.subprocess.DEVNULL,
            app_module.subprocess.DEVNULL,
        )
    ]


def test_reports_chrome_as_unopened_when_executable_is_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(app_module, "find_chrome_executable", lambda: None)

    assert not app_module.launch_chrome()


def test_extension_page_action_copies_address_before_launching_chrome(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[object] = []

    class FakeApp:
        def clipboard_clear(self) -> None:
            events.append("clipboard_clear")

        def clipboard_append(self, value: str) -> None:
            events.append(("clipboard_append", value))

        def update(self) -> None:
            events.append("update")

    monkeypatch.setattr(
        app_module,
        "find_chrome_executable",
        lambda: tmp_path / "chrome.exe",
    )
    monkeypatch.setattr(
        app_module.messagebox,
        "showinfo",
        lambda *args, **kwargs: events.append(("showinfo", args, kwargs)),
    )
    monkeypatch.setattr(
        app_module,
        "launch_chrome",
        lambda: events.append("launch_chrome") or True,
    )

    app_module.EmojiBridgeApp._open_extension_page(FakeApp())

    assert events[:3] == [
        "clipboard_clear",
        ("clipboard_append", "chrome://extensions/"),
        "update",
    ]
    assert events[3][0] == "showinfo"
    assert events[4] == "launch_chrome"


def _make_animated_gif(
    path: Path,
    *,
    size: tuple[int, int] = (80, 90),
    frame_count: int = 3,
    duration_ms: int = 100,
) -> None:
    frames = [
        Image.new(
            "RGB",
            size,
            ((index * 47) % 255, (index * 83) % 255, (index * 29) % 255),
        )
        for index in range(frame_count)
    ]
    frames[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=[duration_ms] * frame_count,
        loop=0,
        disposal=2,
    )


def test_detects_real_gif_behind_wrong_suffix(tmp_path: Path) -> None:
    sample = tmp_path / "actually-a-gif.jpg"
    _make_animated_gif(sample, duration_ms=150)

    asset = detect_media(sample, "QQ")

    assert asset.format == "GIF"
    assert (asset.width, asset.height) == (80, 90)
    assert asset.frames == 3
    assert asset.animated
    assert asset.duration_ms == 450


def test_qq_scan_reads_personal_collection_and_ignores_chat_cache(
    tmp_path: Path,
) -> None:
    emoji = tmp_path / "account" / "nt_qq" / "nt_data" / "Emoji"
    favorite = emoji / "personal_emoji" / "Ori" / "favorite.gif"
    favorite.parent.mkdir(parents=True)
    _make_animated_gif(favorite)
    chat_cache = emoji / "emoji-recv" / "2026-07" / "Ori" / "chat-only.gif"
    chat_cache.parent.mkdir(parents=True)
    _make_animated_gif(chat_cache)
    location = Location("QQ", tmp_path / "account", emoji, "QQ test", "test", 0)

    assets = scan_qq(location, 10)

    assert len(assets) == 1
    assert assets[0].path == favorite
    assert assets[0].format == "GIF"


def test_exports_qq_original_with_hash_verification(tmp_path: Path) -> None:
    source = tmp_path / "favorite.bin"
    _make_animated_gif(source)
    asset = detect_media(source, "QQ")

    first = export_asset(asset, tmp_path / "library")
    second = export_asset(asset, tmp_path / "library")

    assert first == second
    assert first.suffix == ".gif"
    assert first.read_bytes() == source.read_bytes()


def test_extracts_only_valid_extension_folder_from_github_archive(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "Emoji-download-main/emoji-bridge-extension/manifest.json",
            '{"manifest_version": 3, "name": "Emoji Bridge"}',
        )
        bundle.writestr(
            "Emoji-download-main/emoji-bridge-extension/content.js",
            '"use strict";',
        )
        bundle.writestr("Emoji-download-main/README.md", "not part of extension")
        bundle.writestr(
            "Emoji-download-main/emoji-bridge-extension/../outside.txt",
            "must not escape",
        )

    target = extract_extension_bundle(archive, tmp_path / "downloads")

    assert target.name == "emoji-bridge-extension"
    assert (target / "manifest.json").is_file()
    assert (target / "content.js").is_file()
    assert not (target / "README.md").exists()
    assert not (target.parent / "outside.txt").exists()


def test_copies_current_bundled_extension_with_real_progress(tmp_path: Path) -> None:
    source = tmp_path / "source-extension"
    source.mkdir()
    (source / "manifest.json").write_text(
        '{"manifest_version": 3, "name": "Emoji Bridge", "version": "0.3.0"}',
        encoding="utf-8",
    )
    (source / "content.js").write_bytes(b"x" * 2048)
    updates: list[tuple[int, int]] = []

    target = copy_extension_bundle(
        source,
        tmp_path / "downloads",
        progress=lambda copied, total: updates.append((copied, total)),
    )

    assert (target / "manifest.json").is_file()
    assert (target / "content.js").read_bytes() == b"x" * 2048
    assert updates
    assert updates[-1][0] == updates[-1][1]
    assert updates[-1][1] > 2048


def test_discovers_qq_by_validated_internal_structure(tmp_path: Path) -> None:
    emoji = (
        tmp_path
        / "QQ Files"
        / "Tencent Files"
        / "Tencent Files"
        / "123456789"
        / "nt_qq"
        / "nt_data"
        / "Emoji"
    )
    emoji.mkdir(parents=True)

    locations = discover_qq_locations(
        home=tmp_path / "home",
        drives=[],
        extra_roots=[tmp_path],
    )

    assert len(locations) == 1
    assert locations[0].media_root == emoji
    assert locations[0].source == "手动位置"
    assert "123" in locations[0].label
    assert "789" in locations[0].label


def test_scans_every_supplied_drive_for_custom_qq_path(tmp_path: Path) -> None:
    drive_c = tmp_path / "C"
    drive_d = tmp_path / "D"
    drive_c.mkdir()
    drive_d.mkdir()
    emoji = (
        drive_d
        / "custom-data"
        / "chat"
        / "987654321"
        / "nt_qq"
        / "nt_data"
        / "Emoji"
    )
    emoji.mkdir(parents=True)

    locations = discover_qq_locations(
        home=tmp_path / "home",
        drives=[drive_c, drive_d],
    )

    assert [item.media_root for item in locations] == [emoji]
    assert "盘扫描" in locations[0].source


def test_rejects_similarly_named_but_invalid_qq_directory(tmp_path: Path) -> None:
    (tmp_path / "QQ Files" / "Emoji").mkdir(parents=True)

    assert (
        discover_qq_locations(
            home=tmp_path / "home",
            drives=[],
            extra_roots=[tmp_path],
        )
        == []
    )
