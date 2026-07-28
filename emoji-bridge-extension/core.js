(function initEmojiBridgeCore(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.EmojiBridgeCore = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function createEmojiBridgeCore() {
  "use strict";

  const MAX_ASSET_BYTES = 20 * 1024 * 1024;

  function canonicalAssetKey(url) {
    try {
      const parsed = new URL(url);
      if (parsed.hostname.toLowerCase().endsWith("douyinpic.com")) {
        return parsed.pathname;
      }
      return `${parsed.hostname}${parsed.pathname}`;
    } catch {
      return String(url || "").split("?")[0];
    }
  }

  function isDouyinStickerCandidate(candidate) {
    if (!candidate || !candidate.src) return false;

    let parsed;
    try {
      parsed = new URL(candidate.src);
    } catch {
      return false;
    }

    const host = parsed.hostname.toLowerCase();
    const path = parsed.pathname.toLowerCase();
    const search = parsed.searchParams;
    const width = Number(candidate.naturalWidth || candidate.width || 0);
    const height = Number(candidate.naturalHeight || candidate.height || 0);

    if (!host.endsWith("douyinpic.com")) return false;
    if (width < 40 || height < 40 || width > 2000 || height > 2000) return false;
    if (width / height < 0.2 || width / height > 5) return false;
    if (path.includes("avatar") || path.includes("cover") || path.includes("image-cut")) {
      return false;
    }
    if (search.get("s") === "im_1") return false;

    const isImAsset =
      search.get("biz_tag") === "aweme_im" &&
      search.get("s") === "im_2";
    const isMessageEmoji = Boolean(candidate.isMessageEmoji);
    const isKnownStickerPath =
      path.includes("/ies.fe.effect/") ||
      path.includes("/tos-cn-i-3jr8j4ixpe/");

    return isImAsset && (isKnownStickerPath || isMessageEmoji);
  }

  function readAscii(bytes, start, length) {
    let value = "";
    for (let index = start; index < Math.min(bytes.length, start + length); index += 1) {
      value += String.fromCharCode(bytes[index]);
    }
    return value;
  }

  function skipGifSubBlocks(bytes, offset) {
    let cursor = offset;
    while (cursor < bytes.length) {
      const size = bytes[cursor];
      cursor += 1;
      if (size === 0) return cursor;
      cursor += size;
    }
    return cursor;
  }

  function countGifFrames(bytes) {
    if (readAscii(bytes, 0, 3) !== "GIF" || bytes.length < 13) return 0;

    let cursor = 13;
    const packed = bytes[10];
    if (packed & 0x80) {
      cursor += 3 * (1 << ((packed & 0x07) + 1));
    }

    let frames = 0;
    while (cursor < bytes.length) {
      const marker = bytes[cursor];
      cursor += 1;

      if (marker === 0x3b) break;
      if (marker === 0x21) {
        cursor += 1;
        cursor = skipGifSubBlocks(bytes, cursor);
        continue;
      }
      if (marker === 0x2c) {
        frames += 1;
        if (cursor + 9 > bytes.length) break;
        const imagePacked = bytes[cursor + 8];
        cursor += 9;
        if (imagePacked & 0x80) {
          cursor += 3 * (1 << ((imagePacked & 0x07) + 1));
        }
        cursor += 1;
        cursor = skipGifSubBlocks(bytes, cursor);
        continue;
      }
      break;
    }
    return frames;
  }

  function findAscii(bytes, needle) {
    const target = Array.from(needle, (character) => character.charCodeAt(0));
    outer:
    for (let index = 0; index <= bytes.length - target.length; index += 1) {
      for (let offset = 0; offset < target.length; offset += 1) {
        if (bytes[index + offset] !== target[offset]) continue outer;
      }
      return index;
    }
    return -1;
  }

  function detectMediaInfo(input, contentType) {
    const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
    if (bytes.length > MAX_ASSET_BYTES) {
      throw new Error("表情资源超过 20 MB，已停止处理");
    }

    const signature6 = readAscii(bytes, 0, 6);
    const signature4 = readAscii(bytes, 0, 4);
    let format = "bin";
    let extension = "bin";
    let animated = false;
    let frameCount = 1;

    if (signature6 === "GIF87a" || signature6 === "GIF89a") {
      format = "GIF";
      extension = "gif";
      frameCount = countGifFrames(bytes);
      animated = frameCount > 1;
    } else if (
      bytes[0] === 0x89 &&
      bytes[1] === 0x50 &&
      bytes[2] === 0x4e &&
      bytes[3] === 0x47
    ) {
      format = "PNG";
      extension = "png";
      const animationChunk = findAscii(bytes, "acTL");
      animated = animationChunk >= 0;
      if (animated && animationChunk + 12 <= bytes.length) {
        frameCount =
          bytes[animationChunk + 4] * 0x1000000 +
          bytes[animationChunk + 5] * 0x10000 +
          bytes[animationChunk + 6] * 0x100 +
          bytes[animationChunk + 7];
      }
    } else if (signature4 === "RIFF" && readAscii(bytes, 8, 4) === "WEBP") {
      format = "WebP";
      extension = "webp";
      animated = findAscii(bytes, "ANIM") >= 0 || findAscii(bytes, "ANMF") >= 0;
      frameCount = animated ? Math.max(2, countOccurrences(bytes, "ANMF")) : 1;
    } else if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
      format = "JPEG";
      extension = "jpg";
    } else if (String(contentType || "").includes("image/")) {
      const subtype = String(contentType).split("/")[1].split(";")[0].toLowerCase();
      format = subtype.toUpperCase();
      extension = subtype === "jpeg" ? "jpg" : subtype;
    }

    return {
      format,
      extension,
      animated,
      frameCount,
      byteLength: bytes.length
    };
  }

  function countOccurrences(bytes, needle) {
    let count = 0;
    let cursor = 0;
    while (cursor < bytes.length) {
      const remaining = bytes.subarray(cursor);
      const found = findAscii(remaining, needle);
      if (found < 0) break;
      count += 1;
      cursor += found + needle.length;
    }
    return count;
  }

  function sanitizeFilename(value) {
    return String(value || "sticker")
      .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
      .replace(/\s+/g, "_")
      .replace(/_+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 80) || "sticker";
  }

  function buildFilename(asset, index, date) {
    const stampDate = date instanceof Date ? date : new Date(date || Date.now());
    const pad = (value) => String(value).padStart(2, "0");
    const stamp = [
      stampDate.getFullYear(),
      pad(stampDate.getMonth() + 1),
      pad(stampDate.getDate())
    ].join("") + "-" + [
      pad(stampDate.getHours()),
      pad(stampDate.getMinutes()),
      pad(stampDate.getSeconds())
    ].join("");
    const suffix = String(index + 1).padStart(3, "0");
    const dimensions =
      asset.width && asset.height ? `_${asset.width}x${asset.height}` : "";
    const extension = sanitizeFilename(asset.extension || "bin").toLowerCase();
    return `douyin_${stamp}_${suffix}${dimensions}.${extension}`;
  }

  function formatBytes(bytes) {
    const size = Number(bytes || 0);
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  }

  return {
    MAX_ASSET_BYTES,
    canonicalAssetKey,
    isDouyinStickerCandidate,
    countGifFrames,
    detectMediaInfo,
    sanitizeFilename,
    buildFilename,
    formatBytes
  };
});
