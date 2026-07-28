from __future__ import annotations

import os
import json
import queue
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
    detect_media,
    discover_qq_locations,
    discover_wechat_locations,
    extract_extension_bundle,
    export_asset,
    prepare_for_wechat,
    scan_douyin,
    scan_local_folder,
    scan_qq,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = PROJECT_ROOT / "library"
WECHAT_INBOX_DIR = LIBRARY_DIR / "wechat-inbox"
DEFAULT_DOUYIN_DIR = Path.home() / "Downloads" / "EmojiBridge"
EXTENSION_DOWNLOAD_DIR = DEFAULT_DOUYIN_DIR
EXTENSION_ARCHIVE_URL = (
    "https://github.com/sujingyan12138/Emoji-download/archive/refs/heads/main.zip"
)
CONFIG_DIR = Path(os.getenv("APPDATA", Path.home())) / "EmojiBridge"
CONFIG_FILE = CONFIG_DIR / "config.json"


class EmojiBridgeApp(tk.Tk):
    COLORS = {
        "ink": "#1f1c18",
        "paper": "#f4efe3",
        "cream": "#fffaf0",
        "red": "#d7523f",
        "teal": "#177f78",
        "muted": "#746e64",
        "line": "#d8cdbb",
        "gold": "#d7a943",
    }

    def __init__(self) -> None:
        super().__init__()
        self.title("表情中转站 · Emoji Bridge")
        self.geometry("1000x660")
        self.minsize(860, 560)
        self.configure(bg=self.COLORS["paper"])

        self.config_data = self._load_config()
        self.platform = "QQ"
        self.locations: dict[str, list[Location]] = {"QQ": [], "微信": []}
        self.assets: list[Asset] = []
        self.thumbnail_images: list[ImageTk.PhotoImage] = []
        self.preview_image: ImageTk.PhotoImage | None = None
        self.preview_frames: list[ImageTk.PhotoImage] = []
        self.preview_job: str | None = None
        self.extension_guide: tk.Toplevel | None = None
        self.extension_download_running = False
        self.extension_download_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.downloaded_extension_dir: Path | None = None
        self.target_var = tk.StringVar(value="保留原件（QQ / 抖音）")
        self._build_styles()
        self._build_ui()
        if os.name == "nt":
            self.state("zoomed")
        self.after(80, self.refresh_sources)

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Bridge.Treeview",
            background=self.COLORS["cream"],
            fieldbackground=self.COLORS["cream"],
            foreground=self.COLORS["ink"],
            rowheight=76,
            borderwidth=0,
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Bridge.Treeview.Heading",
            background=self.COLORS["ink"],
            foreground=self.COLORS["cream"],
            borderwidth=0,
            relief="flat",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map(
            "Bridge.Treeview",
            background=[("selected", self.COLORS["teal"])],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Bridge.TCombobox",
            fieldbackground=self.COLORS["cream"],
            background=self.COLORS["cream"],
            padding=7,
        )

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=self.COLORS["ink"], height=96)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text="EMOJI TRANSFER DESK  /  本地原件中转",
            bg=self.COLORS["ink"],
            fg=self.COLORS["gold"],
            font=("Consolas", 10, "bold"),
        ).pack(anchor="w", padx=28, pady=(18, 2))
        tk.Label(
            header,
            text="表情中转站",
            bg=self.COLORS["ink"],
            fg="#fff8e9",
            font=("Microsoft YaHei UI", 24, "bold"),
        ).pack(anchor="w", padx=27)

        route = tk.Frame(self, bg=self.COLORS["paper"], pady=10, height=68)
        route.pack(fill="x", padx=24)
        tk.Button(
            route,
            text="打开表情库",
            command=lambda: self.open_folder(LIBRARY_DIR),
            bd=0,
            bg=self.COLORS["gold"],
            fg=self.COLORS["ink"],
            padx=15,
            pady=8,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="right")
        tk.Label(
            route,
            text="来源",
            bg=self.COLORS["paper"],
            fg=self.COLORS["muted"],
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(2, 10))
        self.source_buttons: dict[str, tk.Button] = {}
        for platform in ("抖音网页", "QQ", "微信"):
            button = tk.Button(
                route,
                text=platform,
                command=lambda value=platform: self.set_platform(value),
                bd=0,
                padx=18,
                pady=8,
                cursor="hand2",
                font=("Microsoft YaHei UI", 10, "bold"),
            )
            button.pack(side="left", padx=3)
            self.source_buttons[platform] = button
        tk.Label(
            route,
            text="→  本地表情库  →  微信 / QQ / 抖音",
            bg=self.COLORS["paper"],
            fg=self.COLORS["ink"],
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left", padx=18)

        controls = tk.Frame(self, bg=self.COLORS["paper"], height=54)
        controls.pack(fill="x", padx=26, pady=(0, 12))
        tk.Button(
            controls,
            text="手动选择",
            command=self.choose_folder,
            bd=0,
            bg=self.COLORS["cream"],
            fg=self.COLORS["ink"],
            padx=16,
            pady=8,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right", padx=4)
        tk.Button(
            controls,
            text="重新发现",
            command=self.refresh_sources,
            bd=0,
            bg=self.COLORS["teal"],
            fg="white",
            padx=16,
            pady=8,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="right", padx=(8, 4))
        tk.Button(
            controls,
            text="全选当前",
            command=self.select_all,
            bd=0,
            bg=self.COLORS["cream"],
            fg=self.COLORS["ink"],
            padx=14,
            pady=8,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right", padx=4)
        self.location_var = tk.StringVar()
        self.location_combo = ttk.Combobox(
            controls,
            textvariable=self.location_var,
            state="readonly",
            style="Bridge.TCombobox",
            width=32,
        )
        self.location_combo.pack(side="left", fill="x", expand=True)
        self.location_combo.bind("<<ComboboxSelected>>", lambda _event: self.scan())

        self.source_notice = tk.Frame(
            self,
            bg="#fff3cf",
            highlightthickness=1,
            highlightbackground="#e2c46b",
        )
        self.source_notice_text = tk.Label(
            self.source_notice,
            text="",
            justify="left",
            anchor="w",
            wraplength=760,
            bg="#fff3cf",
            fg=self.COLORS["ink"],
            font=("Microsoft YaHei UI", 9),
        )
        self.source_notice_text.pack(side="left", fill="x", expand=True, padx=14, pady=10)
        self.notice_buttons = tk.Frame(self.source_notice, bg="#fff3cf")
        self.notice_buttons.pack(side="right", padx=8, pady=6)

        self.body = tk.Frame(
            self,
            bg=self.COLORS["line"],
            bd=0,
        )
        self.body.pack(fill="both", expand=True, padx=24, pady=(0, 14))
        left = tk.Frame(self.body, bg=self.COLORS["cream"])
        right = tk.Frame(self.body, bg=self.COLORS["ink"], width=300)
        right.pack(side="right", fill="y", padx=(6, 0))
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
            "format": "格式",
            "dimensions": "尺寸",
            "frames": "动画",
            "size": "大小",
            "modified": "缓存时间",
        }
        widths = {"format": 110, "dimensions": 100, "frames": 90, "size": 90, "modified": 155}
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
            text="PREVIEW / 原件检查",
            bg=self.COLORS["ink"],
            fg=self.COLORS["gold"],
            font=("Consolas", 10, "bold"),
        ).pack(anchor="w", padx=22, pady=(20, 8))
        self.preview = tk.Label(
            right,
            text="选择一个表情\n检查格式和动画",
            bg="#29251f",
            fg="#d9d0c1",
            width=28,
            height=13,
            font=("Microsoft YaHei UI", 11),
        )
        self.preview.pack(fill="x", padx=22)
        self.detail = tk.Label(
            right,
            text="",
            justify="left",
            anchor="nw",
            wraplength=290,
            bg=self.COLORS["ink"],
            fg="#eee5d7",
            font=("Microsoft YaHei UI", 9),
        )
        self.detail.pack(fill="x", padx=22, pady=16)
        tk.Label(
            right,
            text="输出方案",
            anchor="w",
            bg=self.COLORS["ink"],
            fg=self.COLORS["gold"],
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(fill="x", padx=22, pady=(0, 5))
        self.target_combo = ttk.Combobox(
            right,
            textvariable=self.target_var,
            values=("保留原件（QQ / 抖音）", "微信兼容版"),
            state="readonly",
            style="Bridge.TCombobox",
        )
        self.target_combo.pack(fill="x", padx=22, pady=(0, 10))
        self.target_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._refresh_export_button()
        )
        self.export_button = tk.Button(
            right,
            text="复制选中到本地表情库",
            command=self.export_selected,
            state="disabled",
            bd=0,
            bg=self.COLORS["red"],
            activebackground="#b64031",
            fg="white",
            padx=15,
            pady=12,
            cursor="hand2",
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.export_button.pack(fill="x", padx=22, pady=(0, 9))
        tk.Label(
            right,
            text="不修改 QQ / 微信数据库；导入目标平台走官方发送与收藏流程。",
            justify="left",
            wraplength=290,
            bg=self.COLORS["ink"],
            fg="#a79d8e",
            font=("Microsoft YaHei UI", 8),
        ).pack(fill="x", padx=22)

        self.status = tk.Label(
            self,
            text="正在发现客户端数据目录…",
            anchor="w",
            bg=self.COLORS["paper"],
            fg=self.COLORS["muted"],
            font=("Microsoft YaHei UI", 9),
        )
        self.status.pack(fill="x", padx=27, pady=(0, 16))
        self._paint_source_buttons()

    def _update_source_notice(self) -> None:
        for child in self.notice_buttons.winfo_children():
            child.destroy()
        self.source_notice.pack_forget()
        if self.platform == "QQ":
            return

        is_douyin = self.platform == "抖音网页"
        background = "#fff3cf" if is_douyin else "#fde5df"
        border = "#e2c46b" if is_douyin else "#dc8173"
        self.source_notice.configure(bg=background, highlightbackground=border)
        self.source_notice_text.configure(bg=background)
        self.notice_buttons.configure(bg=background)
        self.source_notice.pack(
            fill="x",
            padx=24,
            pady=(0, 10),
            before=self.body,
        )

        if not is_douyin:
            self.source_notice_text.configure(
                text=(
                    "微信自动读取不可用：微信 4.x 的个人表情缓存已加密。可用流程是把表情"
                    "发送到文件传输助手，右键消息选择“另存为…”，保存到微信接收箱；"
                    "本页会读取并预览接收箱。静态图片菜单已实测，动态表情仍待验证。"
                )
            )
            tk.Button(
                self.notice_buttons,
                text="打开微信接收箱",
                command=lambda: self.open_folder(WECHAT_INBOX_DIR),
                bd=0,
                bg=self.COLORS["cream"],
                fg=self.COLORS["ink"],
                padx=10,
                pady=6,
                cursor="hand2",
                font=("Microsoft YaHei UI", 8, "bold"),
            ).pack(side="left", padx=3)
            return

        self.source_notice_text.configure(
            text=(
                "抖音下载箱：Chrome 扩展负责提取网页表情，本页负责预览、筛选和生成"
                "微信兼容版。首次使用请先下载扩展并按安装票据完成设置。"
            )
        )
        tk.Button(
            self.notice_buttons,
            text="下载 Chrome 扩展",
            command=lambda: self.show_extension_guide(start_download=True),
            bd=0,
            bg=self.COLORS["red"],
            fg="white",
            padx=12,
            pady=6,
            cursor="hand2",
            font=("Microsoft YaHei UI", 8, "bold"),
        ).pack(side="left", padx=3)
        actions = (
            ("安装教程", lambda: self.show_extension_guide(start_download=False)),
            ("Chrome 扩展页", lambda: webbrowser.open("chrome://extensions/")),
            ("打开抖音", lambda: webbrowser.open("https://www.douyin.com/")),
        )
        for text, command in actions:
            tk.Button(
                self.notice_buttons,
                text=text,
                command=command,
                bd=0,
                bg=self.COLORS["cream"],
                fg=self.COLORS["ink"],
                padx=10,
                pady=6,
                cursor="hand2",
                font=("Microsoft YaHei UI", 8, "bold"),
            ).pack(side="left", padx=3)

    def show_extension_guide(self, *, start_download: bool) -> None:
        if self.extension_guide and self.extension_guide.winfo_exists():
            self.extension_guide.deiconify()
            self.extension_guide.lift()
            self.extension_guide.focus_force()
            if start_download:
                self._start_extension_download()
            return

        dialog = tk.Toplevel(self)
        self.extension_guide = dialog
        dialog.title("安装抖音提取扩展 · Emoji Bridge")
        dialog.geometry("780x600")
        dialog.minsize(720, 560)
        dialog.configure(bg=self.COLORS["paper"])
        dialog.transient(self)
        dialog.protocol("WM_DELETE_WINDOW", self._close_extension_guide)

        header = tk.Frame(dialog, bg=self.COLORS["ink"], height=108)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text="CHROME EXTENSION / INSTALL TICKET",
            bg=self.COLORS["ink"],
            fg=self.COLORS["gold"],
            font=("Consolas", 10, "bold"),
        ).pack(anchor="w", padx=28, pady=(17, 2))
        tk.Label(
            header,
            text="安装抖音提取扩展",
            bg=self.COLORS["ink"],
            fg=self.COLORS["cream"],
            font=("Microsoft YaHei UI", 22, "bold"),
        ).pack(anchor="w", padx=27)

        status_card = tk.Frame(
            dialog,
            bg="#fff3cf",
            highlightthickness=1,
            highlightbackground="#e2c46b",
        )
        status_card.pack(fill="x", padx=24, pady=(18, 12))
        self.extension_status_label = tk.Label(
            status_card,
            text="尚未下载 · 点击下方按钮获取最新版扩展。",
            anchor="w",
            bg="#fff3cf",
            fg=self.COLORS["ink"],
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.extension_status_label.pack(fill="x", padx=14, pady=(10, 2))
        self.extension_path_label = tk.Label(
            status_card,
            text="来源：github.com/sujingyan12138/Emoji-download",
            anchor="w",
            justify="left",
            wraplength=690,
            bg="#fff3cf",
            fg=self.COLORS["muted"],
            font=("Consolas", 8),
        )
        self.extension_path_label.pack(fill="x", padx=14, pady=(0, 8))
        self.extension_progress = ttk.Progressbar(status_card, mode="indeterminate")
        self.extension_progress.pack(fill="x", padx=14, pady=(0, 10))

        steps = (
            ("01", "下载完成", "程序会自动下载、解压并验证 manifest.json。不要选择 ZIP 文件。"),
            ("02", "打开扩展管理", "在 Chrome 地址栏输入 chrome://extensions/。"),
            ("03", "开启开发者模式", "打开扩展页右上角的“开发者模式”开关。"),
            (
                "04",
                "加载文件夹",
                "点击“加载已解压的扩展程序”，选择下面显示的 emoji-bridge-extension 文件夹。",
            ),
            ("05", "刷新抖音", "固定扩展图标，刷新已打开的抖音页面，再进入私信。"),
            ("06", "扫描与下载", "打开黄色“表情中转站”，扫描当前会话并下载选中原件。"),
        )
        steps_frame = tk.Frame(dialog, bg=self.COLORS["paper"])
        steps_frame.pack(fill="both", expand=True, padx=24)
        steps_frame.grid_columnconfigure(0, weight=1, uniform="ticket")
        steps_frame.grid_columnconfigure(1, weight=1, uniform="ticket")
        for index, (number, title, body) in enumerate(steps):
            row = tk.Frame(
                steps_frame,
                bg=self.COLORS["cream"],
                highlightthickness=1,
                highlightbackground=self.COLORS["line"],
            )
            row.grid(
                row=index // 2,
                column=index % 2,
                sticky="nsew",
                padx=3,
                pady=3,
            )
            tk.Label(
                row,
                text=number,
                width=4,
                bg=self.COLORS["red"],
                fg="white",
                font=("Consolas", 10, "bold"),
            ).pack(side="left", fill="y")
            copy = tk.Frame(row, bg=self.COLORS["cream"])
            copy.pack(side="left", fill="x", expand=True, padx=12, pady=7)
            tk.Label(
                copy,
                text=title,
                anchor="w",
                bg=self.COLORS["cream"],
                fg=self.COLORS["ink"],
                font=("Microsoft YaHei UI", 9, "bold"),
            ).pack(fill="x")
            tk.Label(
                copy,
                text=body,
                anchor="w",
                justify="left",
                wraplength=280,
                bg=self.COLORS["cream"],
                fg=self.COLORS["muted"],
                font=("Microsoft YaHei UI", 8),
            ).pack(fill="x")

        tk.Label(
            dialog,
            text=(
                "关键：必须选择里面直接含有 manifest.json 的 emoji-bridge-extension 文件夹；"
                "不要选择上层 EmojiBridge，也不要把 ZIP 直接拖进 Chrome。"
            ),
            anchor="w",
            justify="left",
            wraplength=700,
            bg=self.COLORS["paper"],
            fg=self.COLORS["red"],
            font=("Microsoft YaHei UI", 8, "bold"),
        ).pack(fill="x", padx=27, pady=(8, 5))

        footer = tk.Frame(dialog, bg=self.COLORS["ink"])
        footer.pack(fill="x", side="bottom")
        self.extension_download_button = tk.Button(
            footer,
            text="下载 / 更新扩展",
            command=self._start_extension_download,
            bd=0,
            bg=self.COLORS["red"],
            fg="white",
            padx=13,
            pady=10,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.extension_download_button.pack(side="left", padx=(18, 5), pady=12)
        self.extension_open_button = tk.Button(
            footer,
            text="打开下载文件夹",
            command=self._open_downloaded_extension,
            state="disabled",
            bd=0,
            bg=self.COLORS["gold"],
            fg=self.COLORS["ink"],
            padx=13,
            pady=10,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.extension_open_button.pack(side="left", padx=5, pady=12)
        self.extension_copy_button = tk.Button(
            footer,
            text="复制文件夹路径",
            command=self._copy_extension_path,
            state="disabled",
            bd=0,
            bg=self.COLORS["cream"],
            fg=self.COLORS["ink"],
            padx=13,
            pady=10,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        )
        self.extension_copy_button.pack(side="left", padx=5, pady=12)
        tk.Button(
            footer,
            text="打开 Chrome 扩展页",
            command=lambda: webbrowser.open("chrome://extensions/"),
            bd=0,
            bg=self.COLORS["teal"],
            fg="white",
            padx=13,
            pady=10,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="right", padx=18, pady=12)

        if self.downloaded_extension_dir:
            self._show_extension_download_success(self.downloaded_extension_dir)
        if start_download:
            self._start_extension_download()

    def _close_extension_guide(self) -> None:
        if self.extension_guide:
            self.extension_guide.destroy()
        self.extension_guide = None

    def _start_extension_download(self) -> None:
        if self.extension_download_running:
            return
        self.extension_download_running = True
        if self.extension_guide and self.extension_guide.winfo_exists():
            self.extension_status_label.configure(text="正在从 GitHub 下载扩展源码…")
            self.extension_path_label.configure(text=EXTENSION_ARCHIVE_URL)
            self.extension_download_button.configure(state="disabled")
            self.extension_open_button.configure(state="disabled")
            self.extension_copy_button.configure(state="disabled")
            self.extension_progress.start(12)
        threading.Thread(
            target=self._download_extension_worker,
            daemon=True,
        ).start()
        self.after(100, self._poll_extension_download)

    def _download_extension_worker(self) -> None:
        temporary_path: Path | None = None
        try:
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
                with temporary_path.open("wb") as destination:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > max_download:
                            raise ValueError("仓库压缩包超过 100 MB，已停止下载。")
                        destination.write(chunk)
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
        handled = False
        while True:
            try:
                kind, payload = self.extension_download_queue.get_nowait()
            except queue.Empty:
                break
            handled = True
            self.extension_download_running = False
            if kind == "success":
                self.downloaded_extension_dir = Path(payload)
                self._show_extension_download_success(self.downloaded_extension_dir)
            else:
                self._show_extension_download_error(str(payload))
        if self.extension_download_running and not handled:
            self.after(100, self._poll_extension_download)

    def _show_extension_download_success(self, target: Path) -> None:
        if not self.extension_guide or not self.extension_guide.winfo_exists():
            return
        self.extension_progress.stop()
        self.extension_status_label.configure(text="下载、解压与 manifest 校验已完成。")
        self.extension_path_label.configure(text=f"安装时请选择：{target}")
        self.extension_download_button.configure(state="normal")
        self.extension_open_button.configure(state="normal")
        self.extension_copy_button.configure(state="normal")

    def _show_extension_download_error(self, error: str) -> None:
        if not self.extension_guide or not self.extension_guide.winfo_exists():
            return
        self.extension_progress.stop()
        self.extension_status_label.configure(text="扩展下载失败，可以稍后重试。")
        self.extension_path_label.configure(text=error)
        self.extension_download_button.configure(state="normal")

    def _open_downloaded_extension(self) -> None:
        if self.downloaded_extension_dir:
            self.open_folder(self.downloaded_extension_dir)

    def _copy_extension_path(self) -> None:
        if not self.downloaded_extension_dir:
            return
        self.clipboard_clear()
        self.clipboard_append(str(self.downloaded_extension_dir))
        self.update()
        if self.extension_guide and self.extension_guide.winfo_exists():
            self.extension_status_label.configure(text="扩展文件夹路径已复制。")

    def _paint_source_buttons(self) -> None:
        for name, button in self.source_buttons.items():
            active = name == self.platform
            button.configure(
                bg=self.COLORS["red"] if active else self.COLORS["cream"],
                fg="white" if active else self.COLORS["ink"],
            )

    def refresh_sources(self) -> None:
        self.status.configure(text="正在验证 QQ 与微信数据目录…")
        self.update_idletasks()
        try:
            self.locations["QQ"] = discover_qq_locations(
                extra_roots=[
                    Path(path) for path in self.config_data.get("qq_roots", [])
                ]
            )
            self.locations["微信"] = discover_wechat_locations(
                extra_roots=[
                    Path(path) for path in self.config_data.get("wechat_roots", [])
                ]
            )
            self.set_platform(self.platform, force=True)
            self.status.configure(
                text=(
                    f"已验证：QQ {len(self.locations['QQ'])} 个账号目录，"
                    f"微信 {len(self.locations['微信'])} 个账号目录。"
                )
            )
        except Exception as error:
            self.status.configure(text=f"目录发现失败：{error}")

    def set_platform(self, platform: str, force: bool = False) -> None:
        if platform == self.platform and not force:
            return
        self.platform = platform
        self._paint_source_buttons()
        self._update_source_notice()
        if platform == "抖音网页":
            root = Path(self.config_data.get("douyin_root", DEFAULT_DOUYIN_DIR))
            self.location_combo["values"] = [str(root)]
            self.location_var.set(str(root))
        elif platform == "微信":
            root = Path(self.config_data.get("wechat_inbox_root", WECHAT_INBOX_DIR))
            self.location_combo["values"] = [f"微信接收箱  ·  {root}"]
            self.location_var.set(f"微信接收箱  ·  {root}")
        else:
            values = [
                f"{item.label}  ·  {item.source}  ·  {item.account_root}"
                for item in self.locations[platform]
            ]
            self.location_combo["values"] = values
            self.location_var.set(values[0] if values else "")
        self.scan()

    def _selected_location(self) -> Location | None:
        if self.platform in ("抖音网页", "微信"):
            return None
        index = self.location_combo.current()
        values = self.locations[self.platform]
        return values[index] if 0 <= index < len(values) else None

    @staticmethod
    def _scan_douyin_with_samples(root: Path) -> list[Asset]:
        assets = scan_douyin(root)
        known = {os.path.normcase(str(asset.path.resolve())) for asset in assets}
        for sample in PROJECT_ROOT.glob("douyin_*"):
            if not sample.is_file():
                continue
            key = os.path.normcase(str(sample.resolve()))
            if key in known:
                continue
            asset = detect_media(sample, "抖音网页")
            if asset.readable:
                assets.append(asset)
                known.add(key)
        return sorted(assets, key=lambda asset: asset.modified, reverse=True)

    def scan(self) -> None:
        self._cancel_preview()
        self.preview.configure(image="", text="正在读取当前来源…")
        self.detail.configure(text="")
        self.preview_image = None
        self.preview_frames = []
        self.tree.delete(*self.tree.get_children())
        self.thumbnail_images = []
        self.assets = []
        self._refresh_export_button()
        try:
            if self.platform == "抖音网页":
                root = Path(self.location_var.get() or DEFAULT_DOUYIN_DIR)
                self.assets = self._scan_douyin_with_samples(root)
                path_note = str(root)
            elif self.platform == "微信":
                configured = Path(
                    self.config_data.get("wechat_inbox_root", WECHAT_INBOX_DIR)
                )
                self.assets = scan_local_folder(configured, "微信")
                path_note = f"微信官方导出接收箱 · {configured}"
                if not self.assets:
                    self.preview.configure(
                        image="",
                        text="微信接收箱为空\n先在微信消息上右键“另存为…”",
                    )
                    self.detail.configure(
                        text=(
                            "已验证：静态图片消息菜单包含“另存为…”。\n\n"
                            "未验证：动态收藏表情发送后是否仍提供“另存为…”。\n\n"
                            f"接收箱：{configured}"
                        )
                    )
            else:
                location = self._selected_location()
                if location is None:
                    self.status.configure(text=f"未自动发现 {self.platform} 目录，请手动选择。")
                    return
                self.assets = scan_qq(location)
                path_note = (
                    f"QQ · 喜欢 · {location.media_root / 'personal_emoji' / 'Ori'}"
                )
            for index, asset in enumerate(self.assets):
                dimensions = (
                    f"{asset.width}×{asset.height}"
                    if asset.width and asset.height
                    else "—"
                )
                animation = f"{asset.frames} 帧" if asset.frames > 1 else ("静态" if asset.readable else "待解密")
                size = self._format_size(asset.size)
                modified = datetime.fromtimestamp(asset.modified).strftime("%m-%d %H:%M:%S")
                thumbnail = self._make_thumbnail(asset)
                if thumbnail is not None:
                    self.thumbnail_images.append(thumbnail)
                self.tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    image=thumbnail or "",
                    text="" if thumbnail else "🔒",
                    values=(asset.format, dimensions, animation, size, modified),
                )
            readable = sum(asset.readable for asset in self.assets)
            self.status.configure(
                text=f"{path_note} · 找到 {len(self.assets)} 项，可直接导出 {readable} 项。"
            )
            if self.assets:
                self.tree.selection_set("0")
                self.tree.focus("0")
                self.show_selected()
        except Exception as error:
            self.status.configure(text=f"扫描失败：{error}")

    def choose_folder(self) -> None:
        chosen = filedialog.askdirectory(title=f"选择 {self.platform} 数据目录")
        if not chosen:
            return
        root = Path(chosen)
        if self.platform == "抖音网页":
            self.location_combo["values"] = [str(root)]
            self.location_var.set(str(root))
            self.config_data["douyin_root"] = str(root)
            self._save_config()
            self.scan()
            return
        if self.platform == "微信":
            self.config_data["wechat_inbox_root"] = str(root)
            self._save_config()
            self.set_platform(self.platform, force=True)
            return

        if self.platform == "QQ":
            found = discover_qq_locations(drives=[], extra_roots=[root])
        else:
            found = discover_wechat_locations(
                drives=[], process_roots=[], extra_roots=[root]
            )
        if not found:
            messagebox.showwarning(
                "目录未通过验证",
                "所选目录内没有发现该平台的表情缓存结构。可以选择更上层的数据目录。",
            )
            return
        key = "qq_roots" if self.platform == "QQ" else "wechat_roots"
        saved = list(self.config_data.get(key, []))
        normalized = os.path.normcase(str(root.resolve()))
        if all(os.path.normcase(str(Path(item).resolve())) != normalized for item in saved):
            saved.append(str(root))
            self.config_data[key] = saved
            self._save_config()
        self.locations[self.platform] = found
        self.set_platform(self.platform, force=True)

    def show_selected(self, _event: object | None = None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        asset = self.assets[int(selection[0])]
        self._show_preview(asset)
        duration = (
            f"{asset.duration_ms / 1000:.2f} 秒" if asset.duration_ms is not None else "—"
        )
        self.detail.configure(
            text=(
                f"来源：{asset.platform}\n"
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
            self.preview.configure(
                image="",
                text="微信 4.x 加密缓存\n路径已发现，原件尚未解密",
            )
            return
        try:
            with Image.open(asset.path) as image:
                count = min(int(getattr(image, "n_frames", 1)), 80)
                for index in range(count):
                    image.seek(index)
                    frame = image.convert("RGBA")
                    frame.thumbnail((300, 300), Image.Resampling.LANCZOS)
                    self.preview_frames.append(ImageTk.PhotoImage(frame.copy()))
                durations = []
                for index in range(count):
                    image.seek(index)
                    durations.append(max(40, int(image.info.get("duration", 100))))
            self.preview.configure(text="", image=self.preview_frames[0])
            self.preview_image = self.preview_frames[0]
            if len(self.preview_frames) > 1:
                self._animate_preview(0, durations)
        except (OSError, ValueError, UnidentifiedImageError):
            self.preview.configure(image="", text="预览失败，但原始文件仍可导出。")

    def _make_thumbnail(self, asset: Asset) -> ImageTk.PhotoImage | None:
        if not asset.readable:
            return None
        try:
            with Image.open(asset.path) as image:
                image.seek(0)
                frame = image.convert("RGBA")
                frame.thumbnail((64, 64), Image.Resampling.LANCZOS)
                tile = Image.new("RGBA", (68, 68), self.COLORS["cream"])
                x = (68 - frame.width) // 2
                y = (68 - frame.height) // 2
                tile.alpha_composite(frame, (x, y))
                return ImageTk.PhotoImage(tile.convert("RGB"))
        except (OSError, ValueError, UnidentifiedImageError):
            return None

    def _animate_preview(self, index: int, durations: list[int]) -> None:
        frame = self.preview_frames[index % len(self.preview_frames)]
        self.preview.configure(image=frame)
        self.preview_image = frame
        delay = durations[index % len(durations)]
        self.preview_job = self.after(
            delay, self._animate_preview, (index + 1) % len(self.preview_frames), durations
        )

    def _cancel_preview(self) -> None:
        if self.preview_job:
            self.after_cancel(self.preview_job)
            self.preview_job = None

    def export_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        selected_assets = [
            self.assets[int(item)]
            for item in selection
            if self.assets[int(item)].readable
        ]
        if not selected_assets:
            return
        try:
            wechat_mode = self.target_var.get() == "微信兼容版"
            output_dir = LIBRARY_DIR / "wechat-ready" if wechat_mode else LIBRARY_DIR
            targets = [
                (
                    prepare_for_wechat(asset, output_dir)
                    if wechat_mode
                    else export_asset(asset, output_dir)
                )
                for asset in selected_assets
            ]
            self.status.configure(text=f"已校验并生成 {len(targets)} 项到：{output_dir}")
            messagebox.showinfo(
                "已进入本地表情库",
                (
                    f"已生成 {len(targets)} 项。\n\n"
                    + (
                        "请用微信的图片入口或直接拖入聊天，再添加为表情。"
                        if wechat_mode
                        else "现在可发送到 QQ 或抖音。"
                    )
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
        action = (
            "生成微信兼容版"
            if self.target_var.get() == "微信兼容版"
            else "复制原件到表情库"
        )
        self.export_button.configure(
            state="normal" if readable_selected else "disabled",
            text=f"{action} · {readable_selected} 项",
        )

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
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

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
