"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const Core = require("../emoji-bridge-extension/core.js");

const root = path.resolve(__dirname, "..");
const extensionStyles = fs.readFileSync(
  path.join(root, "emoji-bridge-extension", "styles.css"),
  "utf8"
);
const extensionContent = fs.readFileSync(
  path.join(root, "emoji-bridge-extension", "content.js"),
  "utf8"
);

test("accepts validated Douyin IM sticker URLs", () => {
  const staticUrl =
    "https://p3-sign.douyinpic.com/obj/ies.fe.effect/example?biz_tag=aweme_im&s=im_2";
  const dynamicUrl =
    "https://p26-sign.douyinpic.com/obj/tos-cn-i-3jr8j4ixpe/example?biz_tag=aweme_im&s=im_2";

  assert.equal(
    Core.isDouyinStickerCandidate({
      src: staticUrl,
      naturalWidth: 240,
      naturalHeight: 240
    }),
    true
  );
  assert.equal(
    Core.isDouyinStickerCandidate({
      src: dynamicUrl,
      naturalWidth: 300,
      naturalHeight: 300
    }),
    true
  );
});

test("deduplicates the same Douyin sticker served by different CDN hosts", () => {
  const path = "/obj/ies.fe.effect/same-sticker";
  assert.equal(
    Core.canonicalAssetKey(`https://p26-sign.douyinpic.com${path}?x=1`),
    Core.canonicalAssetKey(`https://p5-ex-sign.douyinpic.com${path}?x=2`)
  );
});

test("accepts user-uploaded images only when they are Douyin emoji messages", () => {
  const uploadedGif =
    "https://p26-sign.douyinpic.com/obj/tos-cn-o-0812/example?biz_tag=aweme_im&s=im_2";
  const userImage =
    "https://p5-sign.douyinpic.com/obj/douyin-user-image-file/example?biz_tag=aweme_im&s=im_2";

  for (const src of [uploadedGif, userImage]) {
    assert.equal(
      Core.isDouyinStickerCandidate({
        src,
        naturalWidth: 504,
        naturalHeight: 504,
        isMessageEmoji: true
      }),
      true
    );
    assert.equal(
      Core.isDouyinStickerCandidate({
        src,
        naturalWidth: 504,
        naturalHeight: 504,
        isMessageEmoji: false
      }),
      false
    );
  }
});

test("rejects avatars, covers and non-IM images", () => {
  assert.equal(
    Core.isDouyinStickerCandidate({
      src: "https://p3.douyinpic.com/img/aweme-avatar/a.webp?biz_tag=aweme_im&s=im_1",
      naturalWidth: 168,
      naturalHeight: 168
    }),
    false
  );
  assert.equal(
    Core.isDouyinStickerCandidate({
      src: "https://p3.douyinpic.com/image-cut-tos-priv/a.jpeg?biz_tag=pcweb_cover",
      naturalWidth: 440,
      naturalHeight: 330
    }),
    false
  );
});

test("detects an embedded transparent PNG fixture", () => {
  const bytes = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAC0lEQVR42mNgQAcAABIAAeRVjecAAAAASUVORK5CYII=",
    "base64"
  );
  assert.deepEqual(Core.detectMediaInfo(bytes, "image/png"), {
    format: "PNG",
    extension: "png",
    animated: false,
    frameCount: 1,
    byteLength: 68
  });
});

test("detects an embedded animated GIF fixture and frame count", () => {
  const bytes = Buffer.from(
    "R0lGODlhAgACAIEAAAAAAP8AAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQJCgAAACwAAAAAAgACAAAIBgADABgYEAAh+QQJDAAAACwAAAAAAQABAIEAAAAA/wAAAAAAAAAIBAADBAQAOw==",
    "base64"
  );
  const info = Core.detectMediaInfo(bytes, "image/gif");
  assert.equal(info.format, "GIF");
  assert.equal(info.extension, "gif");
  assert.equal(info.animated, true);
  assert.equal(info.frameCount, 2);
  assert.equal(info.byteLength, 109);
});

test("generates Windows-safe deterministic filenames", () => {
  assert.equal(
    Core.buildFilename(
      { width: 300, height: 300, extension: "gif" },
      0,
      new Date(2026, 6, 28, 17, 43, 32)
    ),
    "douyin_20260728-174332_001_300x300.gif"
  );
});

test("transparent extension shell does not intercept Douyin hover panels", () => {
  assert.match(
    extensionStyles,
    /#emoji-bridge-root\s*\{[\s\S]*?pointer-events:\s*none;/
  );
  assert.match(
    extensionStyles,
    /\.eb-launcher\s*\{[\s\S]*?pointer-events:\s*auto;/
  );
  assert.match(
    extensionStyles,
    /\.eb-panel\.is-open\s*\{[\s\S]*?pointer-events:\s*auto;/
  );
});

test("launcher and panel header support persisted pointer dragging", () => {
  assert.match(extensionContent, /launcher\.addEventListener\("pointerdown", beginDrag\)/);
  assert.match(extensionContent, /header\.addEventListener\("pointerdown", beginDrag\)/);
  assert.match(extensionContent, /emojiBridgePositionV1/);
  assert.match(extensionContent, /chrome\.storage\.local\.set/);
});
