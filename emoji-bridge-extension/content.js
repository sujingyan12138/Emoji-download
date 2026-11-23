/* global EmojiBridgeCore, chrome */
(function startEmojiBridge() {
  "use strict";

  if (document.getElementById("emoji-bridge-root")) return;

  const Core = EmojiBridgeCore;
  const POSITION_STORAGE_KEY = "emojiBridgePositionV1";
  const HIDDEN_STORAGE_KEY = "emojiBridgeHiddenV1";
  const state = {
    open: false,
    hidden: false,
    scanning: false,
    assets: [],
    dragMoved: false,
    suppressLauncherClick: false
  };
  const drag = {
    active: false,
    source: null,
    offsetX: 0,
    offsetY: 0,
    startX: 0,
    startY: 0
  };

  const root = document.createElement("section");
  root.id = "emoji-bridge-root";
  root.setAttribute("aria-label", "表情中转站");
  root.innerHTML = `
    <button class="eb-launcher" type="button" aria-label="打开表情中转站" title="表情中转站">
      <span class="eb-launcher__stamp">转</span>
    </button>
    <aside class="eb-panel" aria-hidden="true">
      <header class="eb-header">
        <div class="eb-brand">
          <span class="eb-brand__mark">转</span>
          <div class="eb-brand__text">
            <h2>表情中转站</h2>
            <p class="eb-subtitle">抓取网页原始表情 · 不截图不压动图</p>
          </div>
        </div>
        <div class="eb-tools">
          <button class="eb-tool eb-close" type="button" aria-label="收起面板" title="收起面板">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
          </button>
          <button class="eb-tool eb-hide" type="button" aria-label="隐藏悬浮窗" title="隐藏悬浮窗，可从右侧标签恢复">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3l18 18"/><path d="M10.6 5.1A10.9 10.9 0 0 1 12 5c5 0 9 4 9 7 0 1-.6 2.1-1.7 3.2"/><path d="M6.1 6.6C3.9 8.1 3 10.1 3 12c0 3 4 7 9 7 1.2 0 2.4-.2 3.4-.7"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>
          </button>
        </div>
      </header>

      <section class="eb-route" aria-label="整理路线">
        <div class="eb-route__box eb-route__box--from">
          <span class="eb-route__label">来源</span>
          <strong>抖音网页</strong>
        </div>
        <span class="eb-route__arrow" aria-hidden="true">→</span>
        <div class="eb-route__box eb-route__box--to">
          <span class="eb-route__label">整理到</span>
          <strong>QQ 表情</strong>
        </div>
      </section>

      <section class="eb-actions">
        <button class="eb-primary eb-scan" type="button">
          <span class="eb-button-mark">⌁</span>
          扫描当前会话
        </button>
        <button class="eb-secondary eb-select-all" type="button">全选</button>
      </section>

      <div class="eb-status" role="status" aria-live="polite">
        <span class="eb-status__dot"></span>
        <span class="eb-status__text">打开聊天并滚动加载表情，然后开始扫描。</span>
      </div>

      <section class="eb-results" aria-label="已识别表情">
        <div class="eb-empty">
          <span class="eb-empty__face">( ˘ω˘ )</span>
          <strong>分拣台还是空的</strong>
          <p>只读取当前网页已经加载的聊天表情。</p>
        </div>
        <div class="eb-grid"></div>
      </section>

      <footer class="eb-footer">
        <div class="eb-tip">
          <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v10"/><path d="M7.5 8.5L12 13l4.5-4.5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/></svg>
          <p>下载后发到 QQ 的「我的电脑」，长按图片收藏为表情。</p>
        </div>
        <div class="eb-footer__actions">
          <button class="eb-download" type="button" disabled>
            下载选中 <span class="eb-download-count">0</span>
          </button>
          <button class="eb-open-downloads" type="button">打开下载文件夹</button>
        </div>
        <p class="eb-footer__hint">保存到浏览器下载目录的 <code>EmojiBridge</code> 文件夹</p>
      </footer>
    </aside>
  `;
  document.documentElement.appendChild(root);

  const launcher = root.querySelector(".eb-launcher");
  const panel = root.querySelector(".eb-panel");
  const header = root.querySelector(".eb-header");
  const closeButton = root.querySelector(".eb-close");
  const hideButton = root.querySelector(".eb-hide");
  const scanButton = root.querySelector(".eb-scan");
  const selectAllButton = root.querySelector(".eb-select-all");
  const grid = root.querySelector(".eb-grid");
  const empty = root.querySelector(".eb-empty");
  const statusText = root.querySelector(".eb-status__text");
  const statusDot = root.querySelector(".eb-status__dot");
  const downloadButton = root.querySelector(".eb-download");
  const downloadCount = root.querySelector(".eb-download-count");
  const openDownloadsButton = root.querySelector(".eb-open-downloads");

  launcher.addEventListener("click", () => {
    if (state.suppressLauncherClick) {
      state.suppressLauncherClick = false;
      return;
    }
    if (state.hidden) {
      setHidden(false);
      setPanelOpen(true);
      return;
    }
    setPanelOpen(!state.open);
  });
  launcher.addEventListener("pointerdown", beginDrag);
  header.addEventListener("pointerdown", beginDrag);
  window.addEventListener("pointermove", moveDrag, true);
  window.addEventListener("pointerup", endDrag, true);
  window.addEventListener("pointercancel", endDrag, true);
  window.addEventListener("resize", clampCurrentPosition);
  closeButton.addEventListener("click", () => setPanelOpen(false));
  hideButton.addEventListener("click", () => setHidden(true));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.open) setPanelOpen(false);
  });
  scanButton.addEventListener("click", scanCurrentConversation);
  selectAllButton.addEventListener("click", toggleSelectAll);
  downloadButton.addEventListener("click", downloadSelected);
  openDownloadsButton.addEventListener("click", openDownloads);

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type === "TOGGLE_PANEL") {
      if (state.hidden) {
        setHidden(false);
        setPanelOpen(true);
      } else {
        setPanelOpen(!state.open);
      }
    }
  });
  restorePosition();
  restoreHiddenState();

  function setPanelOpen(open) {
    state.open = Boolean(open);
    panel.classList.toggle("is-open", state.open);
    launcher.classList.toggle("is-hidden", state.open);
    panel.setAttribute("aria-hidden", String(!state.open));
  }

  function setHidden(hidden) {
    state.hidden = Boolean(hidden);
    if (state.hidden) setPanelOpen(false);
    root.classList.toggle("is-away", state.hidden);
    chrome.storage.local.set({ [HIDDEN_STORAGE_KEY]: state.hidden });
  }

  function restoreHiddenState() {
    chrome.storage.local.get(HIDDEN_STORAGE_KEY, (result) => {
      if (result?.[HIDDEN_STORAGE_KEY]) {
        state.hidden = true;
        root.classList.add("is-away");
      }
    });
  }

  async function scanCurrentConversation() {
    if (state.scanning) return;
    state.scanning = true;
    scanButton.disabled = true;
    setStatus("scanning", "正在识别原始资源与动画格式…");

    try {
      const candidates = collectCandidates();
      if (!candidates.length) {
        state.assets = [];
        renderAssets();
        setStatus("warning", "没有找到聊天表情。请先打开会话并滚动到表情所在位置。");
        return;
      }

      const response = await sendMessage({
        type: "INSPECT_ASSETS",
        items: candidates
      });
      state.assets = response.items.map((item) => ({
        ...item,
        selected: item.status === "ready"
      }));
      renderAssets();

      const readyCount = state.assets.filter((item) => item.status === "ready").length;
      const errorCount = state.assets.length - readyCount;
      setStatus(
        errorCount ? "warning" : "ready",
        `识别 ${readyCount} 个表情${errorCount ? `，${errorCount} 个读取失败` : ""}。`
      );
    } catch (error) {
      setStatus("error", error.message || String(error));
    } finally {
      state.scanning = false;
      scanButton.disabled = false;
    }
  }

  function collectCandidates() {
    const seen = new Set();
    const candidates = [];

    document.querySelectorAll("img").forEach((image, domIndex) => {
      const src = image.currentSrc || image.src;
      const isMessageEmoji =
        String(image.className || "").includes("MessageItemEmoji") ||
        Boolean(image.closest('[class*="MessageItemEmoji"]'));
      const candidate = {
        src,
        naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight,
        width: image.naturalWidth,
        height: image.naturalHeight,
        isMessageEmoji,
        domIndex
      };
      if (!Core.isDouyinStickerCandidate(candidate)) return;

      const key = Core.canonicalAssetKey(src);
      if (seen.has(key)) return;
      seen.add(key);
      candidates.push(candidate);
    });

    return candidates;
  }

  function renderAssets() {
    grid.replaceChildren();
    empty.hidden = state.assets.length > 0;

    for (const asset of state.assets) {
      const card = document.createElement("label");
      card.className = "eb-card";
      card.classList.toggle("is-selected", asset.selected);
      card.classList.toggle("has-error", asset.status === "error");

      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = asset.selected;
      input.disabled = asset.status !== "ready";
      input.addEventListener("change", () => {
        asset.selected = input.checked;
        card.classList.toggle("is-selected", asset.selected);
        refreshSelection();
      });

      const preview = document.createElement("div");
      preview.className = "eb-card__preview";
      const image = document.createElement("img");
      image.src = asset.src;
      image.alt = "";
      image.referrerPolicy = "no-referrer";
      preview.appendChild(image);

      const badge = document.createElement("span");
      badge.className = `eb-format ${asset.animated ? "is-animated" : ""}`;
      badge.textContent =
        asset.status === "error"
          ? "读取失败"
          : `${asset.format}${asset.animated ? " · 动态" : ""}`;
      preview.appendChild(badge);

      const meta = document.createElement("div");
      meta.className = "eb-card__meta";
      const dimensions = document.createElement("strong");
      dimensions.textContent = `${asset.width}×${asset.height}`;
      const size = document.createElement("span");
      size.textContent =
        asset.status === "error"
          ? asset.error
          : `${Core.formatBytes(asset.byteLength)}${asset.frameCount > 1 ? ` · ${asset.frameCount} 帧` : ""}`;
      meta.append(dimensions, size);

      card.append(input, preview, meta);
      grid.appendChild(card);
    }
    refreshSelection();
  }

  function toggleSelectAll() {
    const readyAssets = state.assets.filter((item) => item.status === "ready");
    if (!readyAssets.length) return;
    const shouldSelect = readyAssets.some((item) => !item.selected);
    readyAssets.forEach((item) => {
      item.selected = shouldSelect;
    });
    renderAssets();
  }

  function refreshSelection() {
    const selected = state.assets.filter(
      (item) => item.status === "ready" && item.selected
    ).length;
    downloadCount.textContent = String(selected);
    downloadButton.disabled = selected === 0;
    selectAllButton.textContent =
      selected > 0 &&
      selected === state.assets.filter((item) => item.status === "ready").length
        ? "全不选"
        : "全选";
  }

  async function downloadSelected() {
    const selected = state.assets.filter(
      (item) => item.status === "ready" && item.selected
    );
    if (!selected.length) return;

    downloadButton.disabled = true;
    setStatus("scanning", `正在交给浏览器下载 ${selected.length} 个原始文件…`);
    try {
      const result = await sendMessage({
        type: "DOWNLOAD_ASSETS",
        items: selected
      });
      setStatus(
        result.failures.length ? "warning" : "ready",
        `已开始下载 ${result.downloaded} 个文件${result.failures.length ? `，${result.failures.length} 个失败` : ""}。`
      );
    } catch (error) {
      setStatus("error", error.message || String(error));
    } finally {
      refreshSelection();
    }
  }

  async function openDownloads() {
    try {
      await sendMessage({ type: "OPEN_DOWNLOADS" });
    } catch (error) {
      setStatus("error", error.message || String(error));
    }
  }

  function setStatus(kind, text) {
    statusText.textContent = text;
    statusDot.dataset.kind = kind;
  }

  function beginDrag(event) {
    if (event.button !== 0) return;
    if (event.currentTarget === header && event.target.closest("button")) return;

    const rect = root.getBoundingClientRect();
    drag.active = true;
    drag.source = event.currentTarget;
    drag.offsetX = event.clientX - rect.left;
    drag.offsetY = event.clientY - rect.top;
    drag.startX = event.clientX;
    drag.startY = event.clientY;
    state.dragMoved = false;
    root.classList.add("is-dragging");
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }

  function moveDrag(event) {
    if (!drag.active) return;
    if (
      Math.abs(event.clientX - drag.startX) > 3 ||
      Math.abs(event.clientY - drag.startY) > 3
    ) {
      state.dragMoved = true;
    }
    applyPosition(event.clientX - drag.offsetX, event.clientY - drag.offsetY);
    event.preventDefault();
  }

  function endDrag() {
    if (!drag.active) return;
    drag.active = false;
    root.classList.remove("is-dragging");
    const draggedLauncher = drag.source === launcher;
    drag.source = null;
    if (!state.dragMoved) return;
    state.suppressLauncherClick = draggedLauncher;
    const rect = root.getBoundingClientRect();
    chrome.storage.local.set({
      [POSITION_STORAGE_KEY]: {
        left: Math.round(rect.left),
        top: Math.round(rect.top)
      }
    });
  }

  function applyPosition(left, top) {
    const rect = root.getBoundingClientRect();
    const margin = 8;
    const dragHandle = state.open ? header : launcher;
    const handleRect = dragHandle.getBoundingClientRect();
    const position = Core.clampFloatingPosition({
      left,
      top,
      visibleWidth: state.open
        ? rect.width || 430
        : handleRect.width || 60,
      visibleHeight: handleRect.height || 60,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      margin
    });
    root.style.right = "auto";
    root.style.left = `${Math.round(position.left)}px`;
    root.style.top = `${Math.round(position.top)}px`;
  }

  function clampCurrentPosition() {
    if (!root.style.left) return;
    const rect = root.getBoundingClientRect();
    applyPosition(rect.left, rect.top);
  }

  function restorePosition() {
    chrome.storage.local.get(POSITION_STORAGE_KEY, (result) => {
      const position = result?.[POSITION_STORAGE_KEY];
      if (
        !position ||
        !Number.isFinite(position.left) ||
        !Number.isFinite(position.top)
      ) {
        return;
      }
      requestAnimationFrame(() => applyPosition(position.left, position.top));
    });
  }

  function sendMessage(payload) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(payload, (response) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        if (!response?.ok) {
          reject(new Error(response?.error || "扩展后台没有返回结果"));
          return;
        }
        resolve(response);
      });
    });
  }
})();
