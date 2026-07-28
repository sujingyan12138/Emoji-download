/* global EmojiBridgeCore, chrome, importScripts */
"use strict";

importScripts("core.js");

const Core = EmojiBridgeCore;

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id || !String(tab.url || "").startsWith("https://www.douyin.com/")) {
    return;
  }
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "TOGGLE_PANEL" });
  } catch {
    // The page may have been open before the extension was loaded.
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message.type !== "string") return false;

  if (message.type === "INSPECT_ASSETS") {
    inspectAssets(message.items || [])
      .then((items) => sendResponse({ ok: true, items }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message.type === "DOWNLOAD_ASSETS") {
    downloadAssets(message.items || [])
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message.type === "OPEN_DOWNLOADS") {
    chrome.downloads.showDefaultFolder();
    sendResponse({ ok: true });
    return false;
  }

  return false;
});

async function inspectAssets(items) {
  const unique = [];
  const seen = new Set();
  for (const item of items.slice(0, 200)) {
    const key = Core.canonicalAssetKey(item.src);
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(item);
    }
  }
  return mapWithConcurrency(unique, 4, inspectOne);
}

async function inspectOne(item) {
  try {
    const response = await fetch(item.src, {
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer"
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const contentLength = Number(response.headers.get("content-length") || 0);
    if (contentLength > Core.MAX_ASSET_BYTES) {
      throw new Error("资源超过 20 MB");
    }
    const buffer = await response.arrayBuffer();
    const info = Core.detectMediaInfo(buffer, response.headers.get("content-type"));
    return { ...item, ...info, status: "ready" };
  } catch (error) {
    return {
      ...item,
      status: "error",
      error: error instanceof Error ? error.message : String(error)
    };
  }
}

async function downloadAssets(items) {
  let downloaded = 0;
  const failures = [];
  const startedAt = new Date();

  for (let index = 0; index < items.length; index += 1) {
    const item = items[index];
    try {
      const filename = `EmojiBridge/${Core.buildFilename(item, index, startedAt)}`;
      await chrome.downloads.download({
        url: item.src,
        filename,
        conflictAction: "uniquify",
        saveAs: false
      });
      downloaded += 1;
    } catch (error) {
      failures.push({
        src: item.src,
        error: error instanceof Error ? error.message : String(error)
      });
    }
  }

  await chrome.storage.local.set({
    lastExportAt: new Date().toISOString(),
    lastExportCount: downloaded
  });

  return { downloaded, failures };
}

async function mapWithConcurrency(items, concurrency, worker) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function runWorker() {
    while (true) {
      const index = nextIndex;
      nextIndex += 1;
      if (index >= items.length) return;
      results[index] = await worker(items[index]);
    }
  }

  await Promise.all(
    Array.from({ length: Math.min(concurrency, items.length) }, runWorker)
  );
  return results;
}
