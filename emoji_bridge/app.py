from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk, UnidentifiedImageError

from .core import (
    Asset,
    Location,
    copy_extension_bundle,
    discover_qq_locations,
    export_asset,
    extract_extension_bundle,
    list_local_drives,
    scan_qq,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = PROJECT_ROOT / "library"
EXTENSION_DOWNLOAD_DIR = Path.home() / "Downloads" / "EmojiBridge"
EXTENSION_ARCHIVE_URL = (
    "https://github.com/sujingyan12138/Emoji-download/archive/refs/heads/main.zip"
)
CONFIG_DIR = Path(os.getenv("APPDATA", Path.home())) / "EmojiBridge"
CONFIG_FILE = CONFIG_DIR / "config.json"
CHROME_EXTENSIONS_URL = "chrome://extensions/"


def find_chrome_executable() -> Path | None:
    candidates: list[Path] = []
    command_names = ("chrome.exe", "chrome") if os.name == "nt" else (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    )
    for command_name in command_names:
        resolved = shutil.which(command_name)
        if resolved:
            candidates.append(Path(resolved))

    if os.name == "nt":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.getenv(variable)
            if base:
                candidates.append(
                    Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
                )

        try:
            import winreg

            key_path = (
                r"Software\Microsoft\Windows\CurrentVersion"
                r"\App Paths\chrome.exe"
            )
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(root, key_path) as key:
                        registered = winreg.QueryValue(key, None)
                except OSError:
                    continue
                if registered:
                    candidates.append(Path(registered.strip().strip('"')))
        except ImportError:
            pass

    checked: set[str] = set()
    for candidate in candidates:
        candidate_key = os.path.normcase(str(candidate))
        if candidate_key in checked:
            continue
        checked.add(candidate_key)
        if candidate.is_file():
            return candidate
    return None


def launch_chrome() -> bool:
    chrome = find_chrome_executable()
    if chrome is None:
        return False
    try:
        subprocess.Popen(
            [str(chrome)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return True


class EmojiBridgeApp(tk.Tk):
    COLORS = {
        "background": "#F5F5F7",
        "surface": "#FFFFFF",
        "surface_alt": "#FAFAFC",
        "text": "#1D1D1F",
        "secondary_text": "#6E6E73",
        "tertiary_text": "#86868B",
        "separator": "#D2D2D7",
        "separator_soft": "#E5E5EA",
        "control": "#E8E8ED",
        "control_hover": "#DEDEE3",
        "primary": "#0071E3",
        "primary_hover": "#0077ED",
        "primary_pressed": "#0062C4",
        "primary_tint": "#EAF3FF",
        "primary_text": "#0057B8",
        "success": "#248A3D",
        "success_tint": "#EDFAF0",
        "error": "#D70015",
        "error_tint": "#FFF1F2",
    }

    def __init__(self) -> None:
        super().__init__()
        self.title("表情中转站 · QQ & Douyin")
        self.geometry("1180x760")
        self.minsize(980, 640)
        self.configure(bg=self.COLORS["background"])

        self.config_data = self._load_config()
        self.platform = "QQ"
        self.locations: list[Location] = []
        self.scanned_drives: list[Path] = []
        self.assets: list[Asset] = []
        self.thumbnail_images: list[ImageTk.PhotoImage] = []
        self.preview_image: ImageTk.PhotoImage | None = None
        self.preview_frames: list[ImageTk.PhotoImage] = []
        self.preview_job: str | None = None

        self.discovery_running = False
        self.discovery_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.extension_download_running = False
        self.extension_download_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.downloaded_extension_dir = self._find_existing_extension()

        self._build_styles()
        self._build_ui()
        if self.downloaded_extension_dir:
            self._show_extension_download_success(self.downloaded_extension_dir)
        if os.name == "nt":
            self.state("zoomed")
        self.after(80, self.refresh_sources)

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Bridge.Treeview",
            background=self.COLORS["surface"],
            fieldbackground=self.COLORS["surface"],
            foreground=self.COLORS["text"],
            rowheight=74,
            borderwidth=0,
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Bridge.Treeview.Heading",
            background=self.COLORS["surface_alt"],
            foreground=self.COLORS["secondary_text"],
            borderwidth=0,
            relief="flat",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map(
            "Bridge.Treeview",
            background=[("selected", self.COLORS["primary_tint"])],
            foreground=[("selected", self.COLORS["primary_text"])],
        )
        style.configure(
            "Bridge.TCombobox",
            fieldbackground=self.COLORS["surface"],
            background=self.COLORS["surface"],
            foreground=self.COLORS["text"],
            bordercolor=self.COLORS["separator"],
            lightcolor=self.COLORS["surface"],
            darkcolor=self.COLORS["surface"],
            arrowcolor=self.COLORS["secondary_text"],
            padding=8,
        )
        style.map(
            "Bridge.TCombobox",
            fieldbackground=[("readonly", self.COLORS["surface"])],
            foreground=[("readonly", self.COLORS["text"])],
            selectbackground=[("readonly", self.COLORS["surface"])],
            selectforeground=[("readonly", self.COLORS["text"])],
        )
        style.configure(
            "Bridge.Horizontal.TProgressbar",
            background=self.COLORS["primary"],
            troughcolor=self.COLORS["control"],
            borderwidth=0,
            lightcolor=self.COLORS["primary"],
            darkcolor=self.COLORS["primary"],
        )

    def _make_button(
        self,
        parent: tk.Misc,
        text: str,
        command: object,
        *,
        kind: str = "secondary",
        font_size: int = 9,
        padx: int = 14,
        pady: int = 8,
        state: str = "normal",
    ) -> tk.Button:
        if kind == "primary":
            background = self.COLORS["primary"]
            hover = self.COLORS["primary_hover"]
            foreground = "white"
        elif kind == "ghost":
            background = self.COLORS["surface"]
            hover = self.COLORS["control"]
            foreground = self.COLORS["text"]
        else:
            background = self.COLORS["control"]
            hover = self.COLORS["control_hover"]
            foreground = self.COLORS["text"]
        button = tk.Button(
            parent,
            text=text,
            command=command,
            state=state,
            bd=0,
            relief="flat",
            highlightthickness=0,
            bg=background,
            activebackground=hover,
            fg=foreground,
            activeforeground=foreground,
            disabledforeground=self.COLORS["tertiary_text"],
            padx=padx,
            pady=pady,
            cursor="hand2",
            font=("Microsoft YaHei UI", font_size, "bold"),
        )
        button._bridge_normal = background  # type: ignore[attr-defined]
        button._bridge_hover = hover  # type: ignore[attr-defined]

        def enter(_event: object) -> None:
            if str(button["state"]) != "disabled":
                button.configure(
                    bg=getattr(button, "_bridge_hover", hover),
                )

        def leave(_event: object) -> None:
            button.configure(
                bg=getattr(button, "_bridge_normal", background),
            )

        button.bind("<Enter>", enter)
        button.bind("<Leave>", leave)
        return button

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=self.COLORS["background"], height=112)
        header.pack(fill="x")
        header.pack_propagate(False)
        header_copy = tk.Frame(header, bg=self.COLORS["background"])
        header_copy.pack(side="left", fill="y", padx=(34, 0))
        tk.Label(
            header_copy,
            text="EMOJI BRIDGE",
            bg=self.COLORS["background"],
            fg=self.COLORS["primary"],
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(20, 2))
        tk.Label(
            header_copy,
            text="表情中转站",
            bg=self.COLORS["background"],
            fg=self.COLORS["text"],
            font=("Microsoft YaHei UI", 25, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header_copy,
            text="整理 QQ 喜欢表情，安装抖音原件提取扩展。",
            bg=self.COLORS["background"],
            fg=self.COLORS["secondary_text"],
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(2, 0))
        self._make_button(
            header,
            "打开本地表情库",
            lambda: self.open_folder(LIBRARY_DIR),
        ).pack(side="right", padx=34)

        route = tk.Frame(
            self,
            bg=self.COLORS["surface"],
            highlightthickness=1,
            highlightbackground=self.COLORS["separator_soft"],
        )
        route.pack(fill="x", padx=32, pady=(0, 12))
        tk.Label(
            route,
            text="工作区",
            bg=self.COLORS["surface"],
            fg=self.COLORS["secondary_text"],
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="left", padx=(16, 10), pady=13)
        self.source_buttons: dict[str, tk.Button] = {}
        for platform in ("QQ", "抖音扩展"):
            button = self._make_button(
                route,
                platform,
                lambda value=platform: self.set_platform(value),
                padx=18,
                pady=7,
            )
            button.pack(side="left", padx=2, pady=9)
            self.source_buttons[platform] = button
        tk.Label(
            route,
            text="QQ 页负责扫描与导出 · 抖音页只负责扩展安装",
            bg=self.COLORS["surface"],
            fg=self.COLORS["secondary_text"],
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=18)

        self.page_host = tk.Frame(self, bg=self.COLORS["background"])
        self.page_host.pack(fill="both", expand=True, padx=32, pady=(0, 14))
        self.qq_page = tk.Frame(self.page_host, bg=self.COLORS["background"])
        self.douyin_page = tk.Frame(self.page_host, bg=self.COLORS["background"])
        self._build_qq_page()
        self._build_douyin_page()
        self.qq_page.pack(fill="both", expand=True)
        self._paint_source_buttons()

    def _build_qq_page(self) -> None:
        controls = tk.Frame(
            self.qq_page,
            bg=self.COLORS["surface"],
            highlightthickness=1,
            highlightbackground=self.COLORS["separator_soft"],
        )
        controls.pack(fill="x", pady=(0, 10))
        control_copy = tk.Frame(controls, bg=self.COLORS["surface"])
        control_copy.pack(side="left", padx=(16, 10), pady=10)
        tk.Label(
            control_copy,
            text="QQ 喜欢表情",
            bg=self.COLORS["surface"],
            fg=self.COLORS["text"],
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            control_copy,
            text="只读取 personal_emoji\\Ori，不读取聊天缓存",
            bg=self.COLORS["surface"],
            fg=self.COLORS["secondary_text"],
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w")

        self.location_var = tk.StringVar()
        self.location_combo = ttk.Combobox(
            controls,
            textvariable=self.location_var,
            state="readonly",
            style="Bridge.TCombobox",
            width=36,
        )
        self.location_combo.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(4, 10),
            pady=12,
        )
        self.location_combo.bind("<<ComboboxSelected>>", lambda _event: self.scan())

        self._make_button(
            controls,
            "手动选择",
            self.choose_folder,
            kind="ghost",
        ).pack(side="right", padx=(4, 12), pady=12)
        self.discover_button = self._make_button(
            controls,
            "重新发现路径",
            self.refresh_sources,
        )
        self.discover_button.pack(side="right", padx=4, pady=12)
        self._make_button(
            controls,
            "重新扫描表情",
            self.scan,
            kind="primary",
        ).pack(side="right", padx=4, pady=12)

        toolbar = tk.Frame(self.qq_page, bg=self.COLORS["background"])
        toolbar.pack(fill="x", pady=(0, 8))
        self.status = tk.Label(
            toolbar,
            text="正在准备扫描本机磁盘…",
            anchor="w",
            bg=self.COLORS["background"],
            fg=self.COLORS["secondary_text"],
            font=("Microsoft YaHei UI", 8),
        )
        self.status.pack(side="left", fill="x", expand=True, padx=2)
        self.select_all_button = self._make_button(
            toolbar,
            "全选可导出项",
            self.select_all,
            kind="ghost",
            font_size=8,
            pady=6,
        )
        self.select_all_button.pack(side="right")

        body = tk.Frame(self.qq_page, bg=self.COLORS["background"])
        body.pack(fill="both", expand=True)
        left = tk.Frame(
            body,
            bg=self.COLORS["surface"],
            highlightthickness=1,
            highlightbackground=self.COLORS["separator_soft"],
        )
        right = tk.Frame(
            body,
            bg=self.COLORS["surface"],
            width=340,
            highlightthickness=1,
            highlightbackground=self.COLORS["separator_soft"],
        )
        right.pack(side="right", fill="y", padx=(12, 0))
        right.pack_propagate(False)
        left.pack(side="left", fill="both", expand=True)

        columns = ("format", "dimensions", "frames", "size", "modified")
        self.tree = ttk.Treeview(
            left,
            columns=columns,
            show="tree headings",
            style="Bridge.Treeview",
            selectmode="extended",
        )
        self.tree.heading("#0", text="预览")
        self.tree.column("#0", width=92, minwidth=92, stretch=False, anchor="center")
        labels = {
            "format": "真实格式",
            "dimensions": "尺寸",
            "frames": "动画",
            "size": "大小",
            "modified": "加入时间",
        }
        widths = {
            "format": 110,
            "dimensions": 100,
            "frames": 90,
            "size": 90,
            "modified": 155,
        }
        for name in columns:
            self.tree.heading(name, text=labels[name])
            self.tree.column(name, width=widths[name], anchor="center")
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.show_selected)

        tk.Label(
            right,
            text="原件预览",
            bg=self.COLORS["surface"],
            fg=self.COLORS["text"],
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor="w", padx=22, pady=(20, 1))
        tk.Label(
            right,
            text="核对格式、尺寸、帧数与动画",
            bg=self.COLORS["surface"],
            fg=self.COLORS["secondary_text"],
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=22, pady=(0, 11))
        self.preview = tk.Label(
            right,
            text="选择一个表情\n查看原件信息",
            bg=self.COLORS["surface_alt"],
            fg=self.COLORS["tertiary_text"],
            width=28,
            height=9,
            font=("Microsoft YaHei UI", 11),
        )
        self.preview.pack(fill="x", padx=22)
        self.detail = tk.Label(
            right,
            text="",
            justify="left",
            anchor="nw",
            wraplength=296,
            bg=self.COLORS["surface"],
            fg=self.COLORS["secondary_text"],
            font=("Microsoft YaHei UI", 9),
        )
        self.detail.pack(fill="x", padx=22, pady=15)

        self.export_button = self._make_button(
            right,
            "复制原件到表情库 · 0 项",
            self.export_selected,
            kind="primary",
            font_size=10,
            pady=12,
            state="disabled",
        )
        self.export_button.pack(fill="x", padx=22, pady=(0, 9), side="bottom")
        tk.Label(
            right,
            text="导出时会校验文件哈希；不会修改 QQ 数据库。",
            justify="left",
            wraplength=290,
            bg=self.COLORS["surface"],
            fg=self.COLORS["tertiary_text"],
            font=("Microsoft YaHei UI", 8),
        ).pack(fill="x", padx=22, pady=(0, 12), side="bottom")

    def _build_douyin_page(self) -> None:
        hero = tk.Frame(
            self.douyin_page,
            bg=self.COLORS["surface"],
            highlightthickness=1,
            highlightbackground=self.COLORS["separator_soft"],
        )
        hero.pack(fill="x", pady=(0, 10))
        hero_copy = tk.Frame(hero, bg=self.COLORS["surface"])
        hero_copy.pack(side="left", fill="both", expand=True, padx=22, pady=18)
        tk.Label(
            hero_copy,
            text="CHROME EXTENSION",
            bg=self.COLORS["surface"],
            fg=self.COLORS["primary"],
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hero_copy,
            text="从抖音私信提取表情原件",
            bg=self.COLORS["surface"],
            fg=self.COLORS["text"],
            font=("Microsoft YaHei UI", 18, "bold"),
        ).pack(anchor="w", pady=(2, 3))
        tk.Label(
            hero_copy,
            text="这个页面不扫描本地文件，只负责下载扩展和完成安装。",
            bg=self.COLORS["surface"],
            fg=self.COLORS["secondary_text"],
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w")

        hero_actions = tk.Frame(hero, bg=self.COLORS["surface"])
        hero_actions.pack(side="right", padx=20)
        self.extension_download_button = self._make_button(
            hero_actions,
            "获取 / 更新扩展",
            self._start_extension_download,
            kind="primary",
            padx=18,
            pady=10,
        )
        self.extension_download_button.pack(side="left", padx=4)
        self._make_button(
            hero_actions,
            "复制扩展页地址",
            self._open_extension_page,
            kind="ghost",
            pady=10,
        ).pack(side="left", padx=4)
        self._make_button(
            hero_actions,
            "打开抖音",
            lambda: webbrowser.open("https://www.douyin.com/"),
            kind="ghost",
            pady=10,
        ).pack(side="left", padx=4)

        status_card = tk.Frame(
            self.douyin_page,
            bg=self.COLORS["primary_tint"],
            highlightthickness=1,
            highlightbackground="#CFE3FF",
        )
        status_card.pack(fill="x", pady=(0, 12))
        self.extension_status_label = tk.Label(
            status_card,
            text="尚未准备 · 点击“获取 / 更新扩展”。",
            anchor="w",
            bg=self.COLORS["primary_tint"],
            fg=self.COLORS["text"],
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.extension_status_label.pack(fill="x", padx=16, pady=(10, 2))
        self.extension_path_label = tk.Label(
            status_card,
            text="优先使用项目内置扩展；内置目录缺失时从 GitHub 下载。",
            anchor="w",
            justify="left",
            wraplength=1000,
            bg=self.COLORS["primary_tint"],
            fg=self.COLORS["secondary_text"],
            font=("Segoe UI", 8),
        )
        self.extension_path_label.pack(fill="x", padx=16, pady=(0, 7))
        self.extension_progress = ttk.Progressbar(
            status_card,
            mode="determinate",
            maximum=100,
            value=0,
            style="Bridge.Horizontal.TProgressbar",
        )
        self.extension_progress.pack(fill="x", padx=16, pady=(0, 8))
        self.extension_progress.pack_forget()
        status_actions = tk.Frame(status_card, bg=self.COLORS["primary_tint"])
        status_actions.pack(fill="x", padx=12, pady=(0, 8))
        self.extension_open_button = self._make_button(
            status_actions,
            "打开扩展文件夹",
            self._open_downloaded_extension,
            kind="ghost",
            font_size=8,
            pady=6,
            state="disabled",
        )
        self.extension_open_button.pack(side="left", padx=3)
        self.extension_copy_button = self._make_button(
            status_actions,
            "复制文件夹路径",
            self._copy_extension_path,
            kind="ghost",
            font_size=8,
            pady=6,
            state="disabled",
        )
        self.extension_copy_button.pack(side="left", padx=3)

        tk.Label(
            self.douyin_page,
            text="三步完成安装",
            anchor="w",
            bg=self.COLORS["background"],
            fg=self.COLORS["text"],
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(fill="x", padx=2, pady=(0, 7))
        steps = (
            (
                "01",
                "粘贴扩展页地址",
                "点击上方“复制扩展页地址”，在 Chrome 地址栏按 Ctrl+V，"
                "再按 Enter。",
            ),
            (
                "02",
                "开启开发者模式",
                "打开“开发者模式”，点击“加载已解压的扩展程序”，选择 "
                "emoji-bridge-extension 文件夹。",
            ),
            (
                "03",
                "固定并开始使用",
                "然后固定扩展图标，刷新已打开的抖音页面，再进入私信。"
                "打开黄色“表情中转站”，扫描当前会话并下载选中原件。",
            ),
        )
        steps_frame = tk.Frame(self.douyin_page, bg=self.COLORS["background"])
        steps_frame.pack(fill="both", expand=True)
        for column in range(3):
            steps_frame.grid_columnconfigure(column, weight=1, uniform="steps")
        for column, (number, title, body) in enumerate(steps):
            card = tk.Frame(
                steps_frame,
                bg=self.COLORS["surface"],
                highlightthickness=1,
                highlightbackground=self.COLORS["separator_soft"],
            )
            card.grid(
                row=0,
                column=column,
                sticky="nsew",
                padx=(0 if column == 0 else 5, 0 if column == 2 else 5),
            )
            tk.Label(
                card,
                text=number,
                bg=self.COLORS["primary_tint"],
                fg=self.COLORS["primary_text"],
                font=("Segoe UI", 11, "bold"),
                padx=10,
                pady=6,
            ).pack(anchor="w", padx=16, pady=(16, 12))
            tk.Label(
                card,
                text=title,
                anchor="w",
                bg=self.COLORS["surface"],
                fg=self.COLORS["text"],
                font=("Microsoft YaHei UI", 11, "bold"),
            ).pack(fill="x", padx=16)
            tk.Label(
                card,
                text=body,
                anchor="nw",
                justify="left",
                wraplength=290,
                bg=self.COLORS["surface"],
                fg=self.COLORS["secondary_text"],
                font=("Microsoft YaHei UI", 9),
            ).pack(fill="both", expand=True, padx=16, pady=(7, 16))

        tk.Label(
            self.douyin_page,
            text=(
                "安装时请选择里面直接含有 manifest.json 的 emoji-bridge-extension "
                "文件夹，不要选择 ZIP 或它的上层目录。"
            ),
            anchor="w",
            justify="left",
            bg=self.COLORS["background"],
            fg=self.COLORS["secondary_text"],
            font=("Microsoft YaHei UI", 8),
        ).pack(fill="x", padx=2, pady=(10, 0))

    def _paint_source_buttons(self) -> None:
        for name, button in self.source_buttons.items():
            active = name == self.platform
            normal = self.COLORS["primary"] if active else self.COLORS["control"]
            hover = (
                self.COLORS["primary_hover"]
                if active
                else self.COLORS["control_hover"]
            )
            button._bridge_normal = normal  # type: ignore[attr-defined]
            button._bridge_hover = hover  # type: ignore[attr-defined]
            button.configure(
                bg=normal,
                activebackground=hover,
                fg="white" if active else self.COLORS["text"],
                activeforeground="white" if active else self.COLORS["text"],
            )

    def set_platform(self, platform: str) -> None:
        if platform == self.platform:
            return
        self.platform = platform
        self.qq_page.pack_forget()
        self.douyin_page.pack_forget()
        if platform == "QQ":
            self.qq_page.pack(fill="both", expand=True)
            if self.locations and not self.assets:
                self.scan()
        else:
            self._cancel_preview()
            self.douyin_page.pack(fill="both", expand=True)
        self._paint_source_buttons()

    def refresh_sources(self) -> None:
        if self.discovery_running:
            return
        self.discovery_running = True
        self.discover_button.configure(state="disabled")
        self.scanned_drives = list_local_drives()
        drive_text = "、".join(self._display_drive(path) for path in self.scanned_drives)
        self.status.configure(
            text=f"正在检查本机磁盘：{drive_text or '未发现可用本地磁盘'}…"
        )
        self._drain_queue(self.discovery_queue)
        extra_roots = [
            Path(path)
            for path in self.config_data.get("qq_roots", [])
            if isinstance(path, str)
        ]
        threading.Thread(
            target=self._discover_qq_worker,
            args=(self.scanned_drives, extra_roots),
            daemon=True,
        ).start()
        self.after(100, self._poll_discovery)

    def _discover_qq_worker(
        self,
        drives: list[Path],
        extra_roots: list[Path],
    ) -> None:
        try:
            locations = discover_qq_locations(
                drives=drives,
                extra_roots=extra_roots,
            )
            self.discovery_queue.put(("success", locations))
        except Exception as error:
            self.discovery_queue.put(("error", str(error)))

    def _poll_discovery(self) -> None:
        try:
            kind, payload = self.discovery_queue.get_nowait()
        except queue.Empty:
            if self.discovery_running:
                self.after(100, self._poll_discovery)
            return

        self.discovery_running = False
        self.discover_button.configure(state="normal")
        if kind == "error":
            self.status.configure(text=f"QQ 路径发现失败：{payload}")
            return
        self.locations = list(payload)  # type: ignore[arg-type]
        self._populate_locations()
        if self.platform == "QQ":
            self.scan()

    def _populate_locations(self) -> None:
        values = [
            f"{item.label}  ·  {item.source}  ·  {item.account_root}"
            for item in self.locations
        ]
        self.location_combo["values"] = values
        if values:
            self.location_combo.current(0)
        else:
            self.location_var.set("")

    def _selected_location(self) -> Location | None:
        index = self.location_combo.current()
        return self.locations[index] if 0 <= index < len(self.locations) else None

    def scan(self) -> None:
        if self.platform != "QQ":
            return
        self._cancel_preview()
        self.preview.configure(image="", text="正在读取 QQ 喜欢表情…")
        self.detail.configure(text="")
        self.preview_image = None
        self.preview_frames = []
        self.tree.delete(*self.tree.get_children())
        self.thumbnail_images = []
        self.assets = []
        self._refresh_export_button()

        location = self._selected_location()
        drive_text = "、".join(self._display_drive(path) for path in self.scanned_drives)
        if location is None:
            self.preview.configure(image="", text="没有找到 QQ 喜欢表情目录")
            self.status.configure(
                text=(
                    f"已检查 {drive_text or '本机标准位置'}，没有发现有效的 "
                    "nt_qq\\nt_data\\Emoji；可使用“手动选择”。"
                )
            )
            return

        try:
            self.assets = scan_qq(location)
            for index, asset in enumerate(self.assets):
                dimensions = (
                    f"{asset.width}×{asset.height}"
                    if asset.width and asset.height
                    else "—"
                )
                animation = (
                    f"{asset.frames} 帧"
                    if asset.frames > 1
                    else ("静态" if asset.readable else "不可识别")
                )
                thumbnail = self._make_thumbnail(asset)
                if thumbnail is not None:
                    self.thumbnail_images.append(thumbnail)
                self.tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    image=thumbnail or "",
                    text="" if thumbnail else "—",
                    values=(
                        asset.format,
                        dimensions,
                        animation,
                        self._format_size(asset.size),
                        datetime.fromtimestamp(asset.modified).strftime(
                            "%m-%d %H:%M:%S"
                        ),
                    ),
                )
            readable = sum(asset.readable for asset in self.assets)
            personal_root = location.media_root / "personal_emoji" / "Ori"
            self.status.configure(
                text=(
                    f"已检查 {drive_text or '手动目录'} · {location.label} · "
                    f"找到 {len(self.assets)} 项，可导出 {readable} 项 · {personal_root}"
                )
            )
            if self.assets:
                self.tree.selection_set("0")
                self.tree.focus("0")
                self.show_selected()
            else:
                self.preview.configure(image="", text="这个 QQ 账号的“喜欢”列表为空")
        except Exception as error:
            self.status.configure(text=f"QQ 表情扫描失败：{error}")

    def choose_folder(self) -> None:
        chosen = filedialog.askdirectory(title="选择 QQ 数据目录或它的上层目录")
        if not chosen:
            return
        root = Path(chosen)
        found = discover_qq_locations(
            home=root / ".emoji-bridge-validation-home",
            drives=[],
            extra_roots=[root],
        )
        if not found:
            messagebox.showwarning(
                "目录未通过验证",
                "所选目录内没有发现 nt_qq\\nt_data\\Emoji。请选择 QQ 数据目录或更上层目录。",
            )
            return
        saved = list(self.config_data.get("qq_roots", []))
        normalized = os.path.normcase(str(root.resolve()))
        if all(
            os.path.normcase(str(Path(item).resolve())) != normalized
            for item in saved
            if isinstance(item, str)
        ):
            saved.append(str(root))
            self.config_data["qq_roots"] = saved
            self._save_config()
        self.refresh_sources()

    def show_selected(self, _event: object | None = None) -> None:
        selection = self.tree.selection()
        if not selection:
            self._refresh_export_button()
            return
        asset = self.assets[int(selection[0])]
        self._show_preview(asset)
        duration = (
            f"{asset.duration_ms / 1000:.2f} 秒"
            if asset.duration_ms is not None
            else "—"
        )
        self.detail.configure(
            text=(
                f"真实格式：{asset.format}\n"
                f"尺寸：{asset.width or '—'} × {asset.height or '—'}\n"
                f"帧数：{asset.frames or '—'}\n"
                f"时长：{duration}\n"
                f"文件：{asset.path.name}\n\n"
                f"{asset.note}"
            )
        )
        self._refresh_export_button()

    def _show_preview(self, asset: Asset) -> None:
        self._cancel_preview()
        self.preview_frames = []
        if not asset.readable:
            self.preview.configure(image="", text="文件格式无法识别")
            return
        try:
            with Image.open(asset.path) as image:
                count = min(int(getattr(image, "n_frames", 1)), 80)
                durations: list[int] = []
                for index in range(count):
                    image.seek(index)
                    frame = image.convert("RGBA")
                    frame.thumbnail((300, 300), Image.Resampling.LANCZOS)
                    self.preview_frames.append(ImageTk.PhotoImage(frame.copy()))
                    durations.append(max(40, int(image.info.get("duration", 100))))
            self.preview.configure(text="", image=self.preview_frames[0])
            self.preview_image = self.preview_frames[0]
            if len(self.preview_frames) > 1:
                self._animate_preview(0, durations)
        except (OSError, ValueError, UnidentifiedImageError):
            self.preview.configure(image="", text="预览失败，但原件仍可导出")

    def _make_thumbnail(self, asset: Asset) -> ImageTk.PhotoImage | None:
        if not asset.readable:
            return None
        try:
            with Image.open(asset.path) as image:
                image.seek(0)
                frame = image.convert("RGBA")
                frame.thumbnail((64, 64), Image.Resampling.LANCZOS)
                tile = Image.new("RGBA", (68, 68), self.COLORS["surface"])
                tile.alpha_composite(
                    frame,
                    ((68 - frame.width) // 2, (68 - frame.height) // 2),
                )
                return ImageTk.PhotoImage(tile.convert("RGB"))
        except (OSError, ValueError, UnidentifiedImageError):
            return None

    def _animate_preview(self, index: int, durations: list[int]) -> None:
        frame = self.preview_frames[index % len(self.preview_frames)]
        self.preview.configure(image=frame)
        self.preview_image = frame
        delay = durations[index % len(durations)]
        self.preview_job = self.after(
            delay,
            self._animate_preview,
            (index + 1) % len(self.preview_frames),
            durations,
        )

    def _cancel_preview(self) -> None:
        if self.preview_job:
            self.after_cancel(self.preview_job)
            self.preview_job = None

    def export_selected(self) -> None:
        selected_assets = [
            self.assets[int(item)]
            for item in self.tree.selection()
            if int(item) < len(self.assets) and self.assets[int(item)].readable
        ]
        if not selected_assets:
            return
        try:
            targets = [export_asset(asset, LIBRARY_DIR) for asset in selected_assets]
            self.status.configure(
                text=f"已复制并校验 {len(targets)} 项到：{LIBRARY_DIR}"
            )
            messagebox.showinfo(
                "已进入本地表情库",
                (
                    f"已导出 {len(targets)} 项。\n\n"
                    "可发送到 QQ 的“我的电脑”或任意私聊，再收藏为表情。"
                ),
            )
        except Exception as error:
            messagebox.showerror("导出失败", str(error))

    def select_all(self) -> None:
        readable = [
            str(index)
            for index, asset in enumerate(self.assets)
            if asset.readable
        ]
        if not readable:
            return
        self.tree.selection_set(readable)
        self.tree.focus(readable[0])
        self.show_selected()

    def _refresh_export_button(self) -> None:
        readable_selected = sum(
            self.assets[int(item)].readable
            for item in self.tree.selection()
            if int(item) < len(self.assets)
        )
        enabled = readable_selected > 0
        self.export_button.configure(
            state="normal" if enabled else "disabled",
            text=f"复制原件到表情库 · {readable_selected} 项",
            bg=self.COLORS["primary"] if enabled else self.COLORS["control"],
            fg="white" if enabled else self.COLORS["tertiary_text"],
        )

    def _start_extension_download(self) -> None:
        if self.extension_download_running:
            return
        self.extension_download_running = True
        self._drain_queue(self.extension_download_queue)
        self.extension_status_label.configure(
            text="正在准备当前版本扩展…",
            fg=self.COLORS["text"],
        )
        self.extension_path_label.configure(
            text=str(PROJECT_ROOT / "emoji-bridge-extension")
        )
        self.extension_download_button.configure(state="disabled")
        self.extension_open_button.configure(state="disabled")
        self.extension_copy_button.configure(state="disabled")
        self.extension_progress.stop()
        self.extension_progress.configure(mode="indeterminate", value=0)
        self.extension_progress.pack(fill="x", padx=16, pady=(0, 8))
        self.extension_progress.start(12)
        threading.Thread(
            target=self._download_extension_worker,
            daemon=True,
        ).start()
        self.after(100, self._poll_extension_download)

    def _download_extension_worker(self) -> None:
        temporary_path: Path | None = None
        try:
            bundled = PROJECT_ROOT / "emoji-bridge-extension"
            if (bundled / "manifest.json").is_file():
                self.extension_download_queue.put(("local-start", bundled))

                def report(copied: int, total: int) -> None:
                    self.extension_download_queue.put(
                        (
                            "progress",
                            {
                                "downloaded": copied,
                                "total": total,
                                "operation": "正在复制项目内置扩展",
                            },
                        )
                    )

                target = copy_extension_bundle(
                    bundled,
                    EXTENSION_DOWNLOAD_DIR,
                    progress=report,
                )
                self.extension_download_queue.put(("success", target))
                return

            EXTENSION_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=".emoji-bridge-extension-",
                suffix=".zip",
                dir=EXTENSION_DOWNLOAD_DIR,
            )
            os.close(file_descriptor)
            temporary_path = Path(temporary_name)
            request = urllib.request.Request(
                EXTENSION_ARCHIVE_URL,
                headers={"User-Agent": "EmojiBridge/1.0"},
            )
            downloaded = 0
            max_download = 100 * 1024 * 1024
            with urllib.request.urlopen(request, timeout=45) as response:
                declared = int(response.headers.get("Content-Length") or 0)
                if declared > max_download:
                    raise ValueError("仓库压缩包超过 100 MB，已停止下载。")
                self.extension_download_queue.put(
                    ("download-start", {"total": declared})
                )
                with temporary_path.open("wb") as destination:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > max_download:
                            raise ValueError("仓库压缩包超过 100 MB，已停止下载。")
                        destination.write(chunk)
                        self.extension_download_queue.put(
                            (
                                "progress",
                                {
                                    "downloaded": downloaded,
                                    "total": declared,
                                    "operation": "正在下载扩展源码",
                                },
                            )
                        )
            self.extension_download_queue.put(("extracting", downloaded))
            target = extract_extension_bundle(
                temporary_path,
                EXTENSION_DOWNLOAD_DIR,
            )
            self.extension_download_queue.put(("success", target))
        except Exception as error:
            self.extension_download_queue.put(("error", str(error)))
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)

    def _poll_extension_download(self) -> None:
        while True:
            try:
                kind, payload = self.extension_download_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "download-start":
                total = int(payload["total"])  # type: ignore[index]
                if total > 0:
                    self.extension_progress.stop()
                    self.extension_progress.configure(mode="determinate", value=0)
                    self.extension_status_label.configure(text="正在下载扩展源码 · 0%")
                else:
                    self.extension_status_label.configure(
                        text="正在下载扩展源码 · 服务器未提供总大小"
                    )
            elif kind == "local-start":
                self.extension_progress.stop()
                self.extension_progress.configure(mode="determinate", value=0)
                self.extension_status_label.configure(text="正在复制项目内置扩展 · 0%")
                self.extension_path_label.configure(text=str(payload))
            elif kind == "progress":
                downloaded = int(payload["downloaded"])  # type: ignore[index]
                total = int(payload["total"])  # type: ignore[index]
                operation = str(payload.get("operation", "正在处理扩展"))  # type: ignore[union-attr]
                if total > 0:
                    percent = min(100, downloaded * 100 / total)
                    self.extension_progress.configure(value=percent)
                    self.extension_status_label.configure(
                        text=(
                            f"{operation} · {percent:.0f}% · "
                            f"{self._format_size(downloaded)} / {self._format_size(total)}"
                        )
                    )
                else:
                    self.extension_status_label.configure(
                        text=f"{operation} · 已处理 {self._format_size(downloaded)}"
                    )
            elif kind == "extracting":
                self.extension_progress.stop()
                self.extension_progress.configure(mode="indeterminate")
                self.extension_progress.start(12)
                self.extension_status_label.configure(
                    text=(
                        f"下载完成（{self._format_size(int(payload))}），"
                        "正在解压并验证 manifest…"
                    )
                )
            elif kind == "success":
                self.extension_download_running = False
                self.downloaded_extension_dir = Path(payload)
                self._show_extension_download_success(self.downloaded_extension_dir)
            elif kind == "error":
                self.extension_download_running = False
                self._show_extension_download_error(str(payload))
        if self.extension_download_running:
            self.after(100, self._poll_extension_download)

    def _show_extension_download_success(self, target: Path) -> None:
        self.extension_progress.stop()
        self.extension_progress.pack_forget()
        self.extension_status_label.configure(
            text="扩展准备与 manifest 校验已完成。",
            fg=self.COLORS["success"],
        )
        self.extension_path_label.configure(text=f"安装时选择：{target}")
        self.extension_download_button.configure(state="normal")
        self.extension_open_button.configure(state="normal")
        self.extension_copy_button.configure(state="normal")

    def _show_extension_download_error(self, error: str) -> None:
        self.extension_progress.stop()
        self.extension_progress.pack_forget()
        self.extension_status_label.configure(
            text="扩展下载失败，可以稍后重试。",
            fg=self.COLORS["error"],
        )
        self.extension_path_label.configure(text=error)
        self.extension_download_button.configure(state="normal")
        self.extension_open_button.configure(state="disabled")
        self.extension_copy_button.configure(state="disabled")

    def _open_downloaded_extension(self) -> None:
        if self.downloaded_extension_dir:
            self.open_folder(self.downloaded_extension_dir)

    def _open_extension_page(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(CHROME_EXTENSIONS_URL)
        self.update()
        if find_chrome_executable() is None:
            messagebox.showwarning(
                "扩展页地址已复制",
                "没有找到可启动的 Google Chrome。\n\n"
                "请手动打开 Chrome，在地址栏按 Ctrl+V，再按 Enter。",
                parent=self,
            )
            return
        messagebox.showinfo(
            "扩展页地址已复制",
            "Chrome 不允许外部程序直接打开内部扩展页。\n\n"
            "点击“确定”后会打开 Chrome；请在地址栏按 Ctrl+V，"
            "再按 Enter。",
            parent=self,
        )
        if not launch_chrome():
            messagebox.showwarning(
                "无法启动 Chrome",
                "扩展页地址仍在剪贴板中。\n\n"
                "请手动打开 Chrome，在地址栏按 Ctrl+V，再按 Enter。",
                parent=self,
            )

    def _copy_extension_path(self) -> None:
        if not self.downloaded_extension_dir:
            return
        self.clipboard_clear()
        self.clipboard_append(str(self.downloaded_extension_dir))
        self.update()
        self.extension_status_label.configure(
            text="扩展文件夹路径已复制。",
            fg=self.COLORS["success"],
        )

    @staticmethod
    def _find_existing_extension() -> Path | None:
        if not EXTENSION_DOWNLOAD_DIR.is_dir():
            return None
        candidates: list[Path] = []
        for path in EXTENSION_DOWNLOAD_DIR.glob("emoji-bridge-extension*"):
            if path.is_dir() and (path / "manifest.json").is_file():
                candidates.append(path)
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    @staticmethod
    def _display_drive(path: Path) -> str:
        return path.drive or path.name or str(path)

    @staticmethod
    def _drain_queue(target: queue.Queue[tuple[str, object]]) -> None:
        while True:
            try:
                target.get_nowait()
            except queue.Empty:
                return

    @staticmethod
    def _format_size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / 1024 / 1024:.1f} MB"

    @staticmethod
    def open_folder(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    @staticmethod
    def _load_config() -> dict:
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        qq_roots = data.get("qq_roots", [])
        return {
            "qq_roots": [item for item in qq_roots if isinstance(item, str)]
            if isinstance(qq_roots, list)
            else []
        }

    def _save_config(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        temporary = CONFIG_FILE.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.config_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(CONFIG_FILE)


def main() -> None:
    app = EmojiBridgeApp()
    app.mainloop()
