import sys
import os
import ctypes
import time
import subprocess
import json
from pathlib import Path

import win32gui
import win32con

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QSystemTrayIcon,
    QMenu
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon


if getattr(sys, "frozen", False):
    FILE = Path(sys.executable)
    ROOT_DIR = FILE.parent
    ICON_PATH = ROOT_DIR/ "_internal" / "icon" / "bb-video-wallpaper.ico"
else:
    FILE = Path(__file__).resolve()
    ROOT_DIR = FILE.parent
    ICON_PATH = ROOT_DIR / "icon" / "bb-video-wallpaper.ico"

VLC_DIR = ROOT_DIR / "VLC"
VIDEO_DIR = ROOT_DIR / "video"
CONFIG_PATH = ROOT_DIR / "config.json"

TASK_NAME = "BBVideoWallpaper"



if VLC_DIR.exists():
    os.add_dll_directory(str(VLC_DIR))
    
    ctypes.CDLL(str(VLC_DIR / "libvlccore.dll"))
    ctypes.CDLL(str(VLC_DIR / "libvlc.dll"))

import vlc


VIDEO_DIR.mkdir(exist_ok=True)


def run_as_admin():
    """
    檢查是否為系統管理員權限
    """

    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except:
        is_admin = False

    if not is_admin:
        print()
        print("請以系統管理員執行")
        input("Press Enter...")

        sys.exit()


def load_config():

    if not CONFIG_PATH.exists():
        return {}

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return {}


def save_config(config):

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(
            config,
            f,
            indent=2,
            ensure_ascii=False
        )


def run_task():

    subprocess.run(
        [
            "schtasks",
            "/Run",
            "/TN",
            TASK_NAME
        ],
        creationflags=subprocess.CREATE_NO_WINDOW
    )


def create_task():

    cmd = [
        "schtasks",
        "/Create",
        "/TN", TASK_NAME,
        "/TR", f'"{str(FILE)}" --task',
        "/SC", "ONLOGON",
        "/RL", "HIGHEST",
        "/F"
    ]

    subprocess.run(
        cmd,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW
    )


def delete_task():

    subprocess.run(
        [
            "schtasks",
            "/Delete",
            "/TN", TASK_NAME,
            "/F"
        ],
        creationflags=subprocess.CREATE_NO_WINDOW
    )


def task_exists():

    result = subprocess.run(
        [
            "schtasks",
            "/Query",
            "/TN",
            TASK_NAME
        ],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW
    )

    return result.returncode == 0


def get_videos():

    return [
        v
        for v in sorted(
            VIDEO_DIR.iterdir(),
            key=lambda p: p.name.casefold()
        )
        if v.suffix.lower() == ".mp4"
    ]


def get_workerw():
    """
    取得 WorkerW 視窗
    """

    progman = win32gui.FindWindow("Progman", None)
    if not progman:
        raise RuntimeError("找不到 Progman 視窗")

    # 發送訊息讓 Explorer 建立 WorkerW
    win32gui.SendMessageTimeout(
        progman, 0x052C, 0, 0, win32con.SMTO_NORMAL, 1000
    )

    workerw = None

    def enum_windows(hwnd, lparam):

        nonlocal workerw

        shell_view = win32gui.FindWindowEx(hwnd, 0, "SHELLDLL_DefView", None)

        if shell_view:
            # 嘗試找與它同層的 WorkerW
            w = win32gui.FindWindowEx(0, hwnd, "WorkerW", None)
            if w:
                workerw = w

        return True

    for _ in range(5):
        win32gui.EnumWindows(enum_windows, None)

        if workerw:
            break

        time.sleep(0.2)

    # 找不到, 可能 SHELLDLL_DefView 在 Progman 下
    if not workerw:
        shell_view = win32gui.FindWindowEx(progman, 0, "SHELLDLL_DefView", None)
        if shell_view:
            workerw = progman

    if not workerw:
        raise RuntimeError("找不到 WorkerW 視窗")
    return workerw


class Wallpaper(QWidget):

    def __init__(self):

        super().__init__()


        self.current_video = ""
        
        videos = get_videos()

        config = load_config()

        recent = config.get("recentVideo")

        if recent:

            recent_path = VIDEO_DIR / recent

            if recent_path.is_file():
                self.current_video = recent_path

        if not self.current_video and videos:
            self.current_video = videos[0]


        # 建立無邊框視窗
        # FramelessWindowHint: 移除標題列, 邊框
        # Tool: 不出現在工作列
        self.setWindowFlags(
            Qt.FramelessWindowHint |     # type: ignore
            Qt.Tool |                    # type: ignore
            Qt.WindowDoesNotAcceptFocus  # type: ignore
        )

        # 不接受滑鼠事件
        self.setAttribute(
            Qt.WA_TransparentForMouseEvents,  # type: ignore
            True
        )

        # 設成螢幕大小
        screen = QApplication.primaryScreen()

        self.setGeometry(
            screen.geometry()
        )

        # VLC 核心
        self.instance = vlc.Instance(
            "--no-video-title-show",
            "--input-repeat=65535",
            "--no-audio"
        )

        # 建立 VLC 播放器物件
        self.player = self.instance.media_player_new()  # type: ignore

        # 建立影片媒體
        if self.current_video:
            media = self.instance.media_new(str(self.current_video))  # type: ignore
            self.player.set_media(media)

        # Qt 視窗本身在 Windows 有 HWND
        # VLC 需要知道影片畫面要畫在哪個 Windows 視窗
        hwnd = int(self.winId())

        # 將 VLC 輸出綁定到 Qt 視窗
        self.player.set_hwnd(
            hwnd
        )


    def set_video(self, path: Path):

        self.player.stop()

        media = self.instance.media_new(str(path))  # type: ignore
        self.player.set_media(media)

        self.current_video = path

        config = load_config()
        config["recentVideo"] = path.name
        save_config(config)

        self.player.play()


    def attach_to_desktop(self):
        """
        將 Qt 視窗移到 Windows 桌布層
        """

        workerw = get_workerw()

        if workerw:

            # 取得自己的 HWND
            hwnd = int(self.winId())

            # 掛到 WorkerW
            win32gui.SetParent(hwnd,workerw)

            # 取得 WorkerW 大小
            rect = win32gui.GetWindowRect(workerw)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]

            # 設定大小
            win32gui.SetWindowPos(
                hwnd,

                win32con.HWND_TOP,

                0,
                0,
                width,
                height,

                win32con.SWP_NOACTIVATE |
                win32con.SWP_SHOWWINDOW
            )

            style = win32gui.GetWindowLong(
                hwnd,
                win32con.GWL_EXSTYLE
            )


            style |= (
                win32con.WS_EX_NOACTIVATE |
                win32con.WS_EX_TRANSPARENT
            )


            win32gui.SetWindowLong(
                hwnd,
                win32con.GWL_EXSTYLE,
                style
            )


class Tray:

    def __init__(self, app, wallpaper):

        self.app = app
        self.wallpaper = wallpaper


        self.tray = QSystemTrayIcon()

        self.tray.setIcon(QIcon(str(ICON_PATH)))

        self.tray.setToolTip(
            "BB Video Wallpaper"
        )

        menu = QMenu()

        play_action = QAction("播放", menu)
        stop_action = QAction("停止", menu)
        exit_action = QAction("退出", menu)


        open_video_action = QAction("開啟影片資料夾", menu)
        open_video_action.triggered.connect(self.open_video_folder)

        startup_action = QAction("開機自動啟動", menu)
        startup_action.setCheckable(True)
        startup_action.setChecked(task_exists())

        play_action.triggered.connect(self.play)
        stop_action.triggered.connect(self.stop)
        exit_action.triggered.connect(self.exit)

        startup_action.triggered.connect(self.toggle_startup)

        self.startup_action = startup_action


        menu.addAction(play_action)
        menu.addAction(stop_action)

        menu.addSeparator()

        self.video_menu = menu.addMenu("選擇影片")
        
        self.video_menu.aboutToShow.connect(
            self.refresh_video_menu
        )

        menu.addAction(open_video_action)

        menu.addSeparator()

        menu.addAction(startup_action)

        menu.addSeparator()

        menu.addAction(exit_action)

        self.tray.setContextMenu(menu)

        self.tray.show()


    def play(self):
        if self.wallpaper.current_video:
            self.wallpaper.player.play()


    def stop(self):
        self.wallpaper.player.stop()


    def refresh_video_menu(self):

        self.video_menu.clear()

        videos = get_videos()

        if not videos:
            action = QAction("沒有影片", self.video_menu)
            action.setEnabled(False)
            self.video_menu.addAction(action)
            return

        for video in videos:
            action = QAction(video.stem, self.video_menu)

            action.triggered.connect(
                lambda checked=False, v=video:
                    self.wallpaper.set_video(v)
            )

            self.video_menu.addAction(action)


    def open_video_folder(self):
        os.startfile(str(VIDEO_DIR))


    def toggle_startup(self, checked):
        if checked:
            create_task()
        else:
            delete_task()


    def exit(self):
        self.wallpaper.player.stop()
        self.app.quit()


if __name__ == "__main__":

    if "--task" in sys.argv:
        # 已經是工作排程啟動
        pass

    else:
        if task_exists():
            run_task()
            sys.exit()

        run_as_admin()

        # 建立 Qt 應用程式
        app = QApplication(sys.argv)

        # 建立播放器
        w = Wallpaper()
        w.show()

        # 塞進 Windows 桌布層
        w.attach_to_desktop()

        tray = Tray(
            app,
            w
        )

        # 開始播放
        if w.current_video:
            QTimer.singleShot(
                100,
                w.player.play
            )

        # Qt 主迴圈
        sys.exit(app.exec())