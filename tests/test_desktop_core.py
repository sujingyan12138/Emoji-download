from __future__ import annotations

from pathlib import Path
import zipfile

from PIL import Image, ImageDraw

from emoji_bridge.core import (
    detect_media,
    discover_qq_locations,
    discover_wechat_locations,
    extract_extension_bundle,
    prepare_for_wechat,
    scan_local_folder,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _make_animated_gif(
    path: Path,
    *,
    size: tuple[int, int] = (80, 90),
    frame_count: int = 3,
    duration_ms: int = 100,
    transparent: bool = False,
) -> None:
    frames = []
    for index in range(frame_count):
        if transparent:
            frame = Image.new("RGBA", size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(frame)
            draw.rectangle(
                (index, index, min(size[0] - 1, index + 20), min(size[1] - 1, index + 20)),
                fill=(230, 80 + index % 120, 90, 255),
            )
        else:
            frame = Image.new(
                "RGB",
                size,
                ((index * 47) % 255, (index * 83) % 255, (index * 29) % 255),
            )
        frames.append(frame)
    frames[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=[duration_ms] * frame_count,
        loop=0,
        disposal=2,
        transparency=0 if transparent else None,
    )


def _make_transparent_png(path: Path, size: tuple[int, int] = (240, 240)) -> None:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((30, 30, 210, 210), fill=(240, 110, 120, 255))
    image.save(path, format="PNG")


def test_detects_real_gif_behind_wrong_suffix(tmp_path: Path) -> None:
    sample = tmp_path / "actually-a-gif.jpg"
    _make_animated_gif(sample, duration_ms=150)
    asset = detect_media(sample, "QQ")
    assert asset.format == "GIF"
    assert asset.width == 80
    assert asset.height == 90
    assert asset.frames == 3
    assert asset.animated
    assert asset.duration_ms == 450


def test_prepares_large_qq_gif_for_wechat(tmp_path: Path) -> None:
    source = tmp_path / "large.gif"
    _make_animated_gif(
        source,
        size=(300, 400),
        frame_count=21,
        duration_ms=110,
    )
    asset = detect_media(source, "QQ")
    target = prepare_for_wechat(asset, tmp_path / "output")
    converted = detect_media(target, "微信兼容")
    assert converted.animated
    assert converted.frames >= 2
    assert max(converted.width or 0, converted.height or 0) <= 240
    assert converted.size <= 1024 * 1024
    assert abs((converted.duration_ms or 0) - 2310) <= 100


def test_prepares_static_png_for_wechat(tmp_path: Path) -> None:
    source = tmp_path / "static.png"
    _make_transparent_png(source)
    asset = detect_media(source, "抖音网页")
    target = prepare_for_wechat(asset, tmp_path / "output")
    converted = detect_media(target, "微信兼容")
    assert converted.format == "PNG"
    assert (converted.width, converted.height) == (240, 240)


def test_wechat_gif_preserves_transparent_background(tmp_path: Path) -> None:
    source = tmp_path / "transparent.gif"
    _make_animated_gif(source, size=(120, 120), transparent=True)
    asset = detect_media(source, "抖音网页")
    target = prepare_for_wechat(asset, tmp_path / "output")
    with Image.open(target) as image:
        alpha_extrema = image.convert("RGBA").getchannel("A").getextrema()
    assert alpha_extrema[0] == 0


def test_qq_scan_reads_personal_collection_and_ignores_chat_cache(tmp_path: Path) -> None:
    from emoji_bridge.core import Location, scan_qq

    emoji = tmp_path / "account" / "nt_qq" / "nt_data" / "Emoji"
    target = emoji / "personal_emoji" / "Ori" / "favorite.gif"
    target.parent.mkdir(parents=True)
    _make_animated_gif(target)
    chat_cache = emoji / "emoji-recv" / "2026-07" / "Ori" / "chat-only.gif"
    chat_cache.parent.mkdir(parents=True)
    _make_animated_gif(chat_cache)
    location = Location("QQ", tmp_path / "account", emoji, "QQ test", "test", 0)
    assets = scan_qq(location, 10)
    assert len(assets) == 1
    assert assets[0].path == target
    assert assets[0].format == "GIF"


def test_wechat_inbox_reads_officially_saved_images_only(tmp_path: Path) -> None:
    inbox = tmp_path / "wechat-inbox"
    inbox.mkdir()
    saved = inbox / "saved-without-extension"
    _make_transparent_png(saved)
    (inbox / "not-an-image.db").write_bytes(b"encrypted")

    assets = scan_local_folder(inbox, "微信", 10)

    assert len(assets) == 1
    assert assets[0].platform == "微信"
    assert assets[0].path == saved
    assert assets[0].format == "PNG"


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
    locations = discover_qq_locations(home=tmp_path / "home", drives=[], extra_roots=[tmp_path])
    assert len(locations) == 1
    assert locations[0].media_root == emoji
    assert "123" in locations[0].label
    assert "789" in locations[0].label


def test_discovers_wechat_process_root_and_account(tmp_path: Path) -> None:
    account = tmp_path / "xwechat_files" / "wxid_example_1234"
    (account / "business" / "emoticon").mkdir(parents=True)
    locations = discover_wechat_locations(
        home=tmp_path / "home",
        drives=[],
        process_roots=[tmp_path / "xwechat_files"],
    )
    assert len(locations) == 1
    assert locations[0].account_root == account
    assert locations[0].source == "运行进程"


def test_rejects_similarly_named_but_invalid_directories(tmp_path: Path) -> None:
    (tmp_path / "QQ Files" / "Emoji").mkdir(parents=True)
    (tmp_path / "xwechat_files" / "someone").mkdir(parents=True)
    assert discover_qq_locations(home=tmp_path, drives=[], extra_roots=[tmp_path]) == []
    assert (
        discover_wechat_locations(
            home=tmp_path,
            drives=[],
            process_roots=[],
            extra_roots=[tmp_path / "xwechat_files"],
        )
        == []
    )
