import sys
import os
import subprocess
import json
from pathlib import Path

import win32gui
import win32con
import win32api
import ctypes
from ctypes import wintypes

from PySide6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtGui import QFont


if getattr(sys, "frozen", False):
    FILE = Path(sys.executable).resolve()
    ROOT_DIR = FILE.parent
    ICON_PATH = ROOT_DIR/ "_internal" / "icon" / "bb-video-wallpaper.ico"
else:
    FILE = Path(__file__).resolve()
    ROOT_DIR = FILE.parent
    ICON_PATH = ROOT_DIR / "icon" / "bb-video-wallpaper.ico"


TASK_NAME = "BBVideoWallpaper"


APPDATA_DIR = (Path(os.getenv("LOCALAPPDATA")) / "BB" / "BB Video Wallpaper")  # type: ignore
APPDATA_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_DIR = APPDATA_DIR / "video"
VIDEO_DIR.mkdir(exist_ok=True)

CONFIG_PATH = APPDATA_DIR / "config.json"


VLC_DIR = ROOT_DIR / "VLC"

if VLC_DIR.is_dir():
    os.add_dll_directory(str(VLC_DIR))
    os.environ["PYTHON_VLC_LIB_PATH"] = str(VLC_DIR / "libvlc.dll")
    os.environ["PYTHON_VLC_MODULE_PATH"] = str(VLC_DIR)

    try:
        ctypes.CDLL(str(VLC_DIR / "libvlccore.dll"))
        ctypes.CDLL(str(VLC_DIR / "libvlc.dll"))
    except OSError:
        print("VLC 載入失敗")
        sys.exit(1)
else:
    print("找不到 VLC/")
    sys.exit(1)

import vlc


WM_POWERBROADCAST = 0x0218
PBT_POWERSETTINGCHANGE = 0x8013
DEVICE_NOTIFY_WINDOW_HANDLE = 0

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [
        ("PowerSetting", GUID),
        ("DataLength", wintypes.DWORD),
        ("Data", wintypes.DWORD),
    ]


GUID_CONSOLE_DISPLAY_STATE = GUID(
    0x6FE69556,
    0x704A,
    0x47A0,
    (ctypes.c_ubyte * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47)
)


# 明確指定 Windows API 的參數與回傳值型別, 避免 64 位元 Handle 被截斷
ctypes.windll.user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
ctypes.windll.user32.RegisterPowerSettingNotification.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD
]

ctypes.windll.user32.UnregisterPowerSettingNotification.restype = wintypes.BOOL
ctypes.windll.user32.UnregisterPowerSettingNotification.argtypes = [
    wintypes.HANDLE
]


def run_as_admin():
    """
    檢查是否為系統管理員權限
    """

    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
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

    cmd = [
        "powershell",
        "-Command",
        f"""
        $task = Get-ScheduledTask -TaskName '{TASK_NAME}'
        $task.Settings.DisallowStartIfOnBatteries = $false
        $task.Settings.StopIfGoingOnBatteries = $false
        Set-ScheduledTask -InputObject $task
        """.strip()
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


def create_workerw(parent_hwnd):
    """
    手動創建一個 WorkerW 視窗
    """

    try:

        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)                                                         # type: ignore
        wc.lpszClassName = "WorkerW"                                                                          # type: ignore
        wc.style = win32con.CS_VREDRAW | win32con.CS_HREDRAW                                                  # type: ignore
        wc.lpfnWndProc = lambda hwnd, msg, wParam, lParam: win32gui.DefWindowProc(hwnd, msg, wParam, lParam)  # type: ignore
        win32gui.RegisterClass(wc)

    except Exception:
        # WorkerW 類別可能已經註冊, 直接忽略即可
        pass


    rect = win32gui.GetClientRect(parent_hwnd)
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]

    hwnd = win32gui.CreateWindowEx(
        win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW,
        "WorkerW",
        "",
        win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_CLIPSIBLINGS,
        0, 0, width, height,
        parent_hwnd,
        None,
        win32api.GetModuleHandle(None),
        None
    )

    return hwnd


def set_windows_as_wallpaper(hwnd):
    """
    將視窗放到桌布
    """

    progman = win32gui.FindWindow("Progman", "Program Manager")

    if not progman:
        progman = win32gui.FindWindow("Progman", None)

    if not progman:
        raise RuntimeError("找不到 Progman 視窗")


    # 發送舊版 0x052C 訊息讓桌面分裂
    # 把本來黏在一起的 "桌面圖示" 與 "背景桌布" 分離開來, 希望在中間炸出一個獨立的 WorkerW 視窗
    win32gui.SendMessageTimeout(progman, 0x052C, 0, None, 0, 0x03E8)
    win32gui.SendMessageTimeout(progman, 0x052C, 0xD, None, 0, 0x03E8)
    win32gui.SendMessageTimeout(progman, 0x052C, 0xD, 1, 0, 0x03E8)


    WorkerW_top = None
    SHELLDLL_DefView = None
    WorkerW_first = None
    WorkerW_old = None


    # 嘗試搜尋舊版分裂產生的 WorkerW
    while True:

        WorkerW_top = win32gui.FindWindowEx(None, WorkerW_top, "WorkerW", None)
        if WorkerW_top == WorkerW_first:
            # 直到找不到分裂的桌面圖示層
            break

        if WorkerW_first is None:
            WorkerW_first = WorkerW_top

        if not WorkerW_top:
            continue

        SHELLDLL_DefView = win32gui.FindWindowEx(WorkerW_top, None, "SHELLDLL_DefView", None)
        if not SHELLDLL_DefView:
            continue

        WorkerW_old = win32gui.FindWindowEx(None, WorkerW_top, "WorkerW", None)
        break


    # 判斷使用新版或舊版機制
    if not WorkerW_old:

        # 新版 Windows 11: 直接在 Progman 底下找尋或創建 WorkerW
        new_workerw = win32gui.FindWindowEx(progman, None, "WorkerW", None)
        if not new_workerw:
            new_workerw = create_workerw(progman)
            
        ctypes.windll.user32.SetParent(hwnd, new_workerw)

    else:

        # 舊版: 直接掛載到分裂後的 WorkerW
        ctypes.windll.user32.SetParent(hwnd, WorkerW_old)
        ctypes.windll.user32.SetWindowPos(
            hwnd,

            SHELLDLL_DefView,

            0, 0, 0, 0,

            0x0001 | 0x0002
        )


def is_foreground_fullscreen():
    """
    偵測畫面上是否有全螢幕程式
    """

    # 邊界容許值
    FULLSCREEN_MARGIN = 4


    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return False


    # 自己不算
    if hwnd == int(w.winId()):
        return False

    # 隱藏視窗不算
    if not win32gui.IsWindowVisible(hwnd):
        return False

    # 最小化視窗不算
    if win32gui.IsIconic(hwnd):
        return False


    try:
        monitor = win32api.MonitorFromWindow(
            hwnd,
            win32con.MONITOR_DEFAULTTONEAREST
        )
        info = win32api.GetMonitorInfo(monitor)
        monitor_left, monitor_top, monitor_right, monitor_bottom = info["Work"]
    except Exception:
        return False
    
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception:
        return False


    return (
        left <= monitor_left + FULLSCREEN_MARGIN and
        top <= monitor_top + FULLSCREEN_MARGIN and
        right >= monitor_right - FULLSCREEN_MARGIN and
        bottom >= monitor_bottom - FULLSCREEN_MARGIN
    )


class Wallpaper(QWidget):

    def __init__(self):

        super().__init__()


        self.current_video: Path | None = None
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
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # type: ignore

        # 設成螢幕大小
        screen = QApplication.primaryScreen()
        self.setGeometry(screen.geometry())


        # VLC
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


        self.enable_auto_pause = True
        self.paused = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_auto_pause)
        self.timer.start(500)


        self.screen_off = False
        self.power_notify = None

        self.auto_pause_if_fullscreen = True
        self.auto_pause_if_screen_off = True


    def nativeEvent(self, eventType, message):
        """
        處理原生 Windows 訊息迴圈
        """

        if eventType in (b"windows_generic_MSG", "windows_generic_MSG"):

            # 解析 MSG 結構
            msg = wintypes.MSG.from_address(int(message))

            if msg.message == WM_POWERBROADCAST and msg.wParam == PBT_POWERSETTINGCHANGE:

                setting = ctypes.cast(msg.lParam, ctypes.POINTER(POWERBROADCAST_SETTING)).contents

                # 比對 GUID 是否為螢幕顯示狀態變更
                if bytes(setting.PowerSetting) == bytes(GUID_CONSOLE_DISPLAY_STATE):

                    if setting.Data == 0:
                        self.screen_off = True

                    else:
                        self.screen_off = False

                    self.check_auto_pause()

                    return True, 0

        return super().nativeEvent(eventType, message)  # type: ignore


    def set_video(self, path: Path):

        self.player.stop()
        print("stop")

        media = self.instance.media_new(str(path))  # type: ignore
        self.player.set_media(media)

        self.current_video = path

        config = load_config()
        config["recentVideo"] = path.name
        save_config(config)

        self.player.play()
        self.enable_auto_pause = True
        self.paused = False
        print("play")


    def attach_to_desktop(self):
        """
        將 Qt 視窗移到 Windows 桌布層
        """

        hwnd = int(self.winId())

        set_windows_as_wallpaper(hwnd)

        # 重新設定 HWND 給 VLC 指向
        self.player.set_hwnd(hwnd)


        self.power_notify = ctypes.windll.user32.RegisterPowerSettingNotification(
            hwnd,
            ctypes.byref(GUID_CONSOLE_DISPLAY_STATE),
            DEVICE_NOTIFY_WINDOW_HANDLE
        )

        if not self.power_notify:
            print("螢幕電源通知註冊失敗")


    def check_auto_pause(self):
        """
        檢查是否需要自動暫停
        """

        if not self.enable_auto_pause:
            return


        need_auto_pause = False

        need_auto_pause = (self.auto_pause_if_fullscreen and is_foreground_fullscreen()) or need_auto_pause

        need_auto_pause = (self.auto_pause_if_screen_off and self.screen_off) or need_auto_pause


        if need_auto_pause:
            if not self.paused:

                self.player.pause()
                self.paused = True
                print("pause")

        else:
            if self.paused:
                self.player.play()
                self.paused = False
                print("play")


    def unregister_power_notification(self):
        """
        取消註冊 Windows 螢幕電源通知
        """

        if self.power_notify:
            try:
                ctypes.windll.user32.UnregisterPowerSettingNotification(self.power_notify)
            except Exception as e:
                print(f"取消註冊電源通知時發生錯誤")
                print(f" > {e}")
            finally:
                self.power_notify = None


class Tray:

    def __init__(self, app, wallpaper):

        self.app = app
        self.wallpaper = wallpaper


        self.tray = QSystemTrayIcon()
        self.tray.setIcon(QIcon(str(ICON_PATH)))
        self.tray.setToolTip("BB Video Wallpaper")


        menu = QMenu()


        play_action = QAction("播放", menu)
        pause_action = QAction("暫停", menu)
        stop_action = QAction("停止", menu)
        exit_action = QAction("退出", menu)


        open_video_action = QAction("開啟影片資料夾", menu)
        open_video_action.triggered.connect(self.open_video_folder)


        auto_pause_if_fullscreen_action = QAction("全螢幕時自動暫停", menu)
        auto_pause_if_fullscreen_action.setCheckable(True)
        auto_pause_if_fullscreen_action.setChecked(True)

        auto_pause_if_screen_off_action = QAction("螢幕關閉時自動暫停", menu)
        auto_pause_if_screen_off_action.setCheckable(True)
        auto_pause_if_screen_off_action.setChecked(True)

        startup_action = QAction("開機自動啟動", menu)
        startup_action.setCheckable(True)
        startup_action.setChecked(task_exists())


        play_action.triggered.connect(self.play)
        pause_action.triggered.connect(self.pause)
        stop_action.triggered.connect(self.stop)
        exit_action.triggered.connect(self.exit)


        auto_pause_if_fullscreen_action.triggered.connect(self.toggle_auto_pause_if_fullscreen)
        auto_pause_if_screen_off_action.triggered.connect(self.toggle_auto_pause_if_screen_off)
        startup_action.triggered.connect(self.toggle_startup)


        menu.addAction(play_action)
        menu.addAction(pause_action)
        menu.addAction(stop_action)


        menu.addSeparator()


        self.video_menu = menu.addMenu("選擇影片")
        self.video_menu.aboutToShow.connect(
            self.refresh_video_menu
        )

        menu.addAction(open_video_action)


        menu.addSeparator()


        self.options_menu = menu.addMenu("選項")

        self.options_menu.addAction(auto_pause_if_fullscreen_action)
        self.options_menu.addAction(auto_pause_if_screen_off_action)

        self.options_menu.addSeparator()

        self.options_menu.addAction(startup_action)


        menu.addSeparator()


        menu.addAction(exit_action)


        self.tray.setContextMenu(menu)

        self.tray.show()


    def play(self):
        if self.wallpaper.current_video:
            self.wallpaper.player.play()
            self.wallpaper.enable_auto_pause = True
            self.wallpaper.paused = False
            print("play")


    def pause(self):
        self.wallpaper.player.pause()
        self.wallpaper.enable_auto_pause = False
        self.wallpaper.paused = True
        print("pause")


    def stop(self):
        self.wallpaper.player.stop()
        self.wallpaper.enable_auto_pause = False
        self.wallpaper.paused = True
        print("stop")


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

            action.setCheckable(True)
            action.setChecked(video == self.wallpaper.current_video)

            self.video_menu.addAction(action)


    def open_video_folder(self):
        os.startfile(str(VIDEO_DIR))


    def toggle_auto_pause_if_fullscreen(self, checked):
        if checked:
            self.wallpaper.auto_pause_if_fullscreen = True
        else:
            self.wallpaper.auto_pause_if_fullscreen = False


    def toggle_auto_pause_if_screen_off(self, checked):
        if checked:
            self.wallpaper.auto_pause_if_screen_off = True
        else:
            self.wallpaper.auto_pause_if_screen_off = False


    def toggle_startup(self, checked):
        if checked:
            create_task()
        else:
            delete_task()


    def exit(self):
        self.wallpaper.unregister_power_notification()
        self.wallpaper.player.stop()
        self.app.quit()
        print("exit")


if __name__ == "__main__":

    if "--task" not in sys.argv:
        # 不是工作排程啟動
        run_as_admin()


    # 建立 Qt 應用程式
    app = QApplication(sys.argv)


    font = QFont()
    font.setPointSize(11)
    app.setFont(font)


    # 建立播放器
    w = Wallpaper()
    w.show()

    # 塞進 Windows 桌布層
    w.attach_to_desktop()

    # 開始播放
    if w.current_video:
        QTimer.singleShot(100, w.player.play)


    tray = Tray(app, w)


    # Qt 主迴圈
    sys.exit(app.exec())