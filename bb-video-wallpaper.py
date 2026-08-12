import sys
import os
import subprocess
import json
from pathlib import Path
import time

import win32gui
import win32con
import win32api
import ctypes
from ctypes import wintypes

from PySide6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QFont


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


VLC_DIR = next(
    (
        path
        for path in (ROOT_DIR / "VLC-lite", ROOT_DIR / "VLC")
        if path.is_dir()
    ),
    None
)

if VLC_DIR:
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
    print("找不到 VLC-lite/ 或 VLC/")
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


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("Reserved1", ctypes.c_ubyte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


# 螢幕顯示狀態 (亮暗關) 的 GUID
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


SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi",}
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp",}


def run_as_admin() -> None:
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


def is_on_battery():
    """
    檢查目前是否使用電池供電
    """

    status = SYSTEM_POWER_STATUS()

    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return False


    # 0 = 沒插電
    # 1 = 接上 AC 電源
    # 255 = 未知
    return status.ACLineStatus == 0


def load_config() -> dict:

    if not CONFIG_PATH.exists():
        return {}

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return {}


def save_config(config) -> None:

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(
            config,
            f,
            indent=2,
            ensure_ascii=False
        )


def create_task() -> None:
    """
    加入 Windows 工作排程器
    """

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


def delete_task() -> None:
    """
    從 Windows 工作排程器中刪除
    """

    subprocess.run(
        [
            "schtasks",
            "/Delete",
            "/TN", TASK_NAME,
            "/F"
        ],
        creationflags=subprocess.CREATE_NO_WINDOW
    )


def task_exists() -> bool:
    """
    檢查 Windows 工作排程器中是否存在這項工作
    """

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


def get_media() -> list:
    """
    從 VIDEO_DIR 取得媒體
    """

    return [
        p
        for p in sorted(
            VIDEO_DIR.iterdir(),
            key=lambda p: p.name.casefold()
        )
        if (
            p.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
            or
            p.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
        )
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


def set_windows_as_wallpaper(hwnd) -> None:
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


def is_fullscreen(hwnd) -> bool:
    """
    偵測視窗是否最大化
    """

    # 邊界容許值
    FULLSCREEN_MARGIN = 4


    # 隱藏視窗不算
    if not win32gui.IsWindowVisible(hwnd):
        return False

    # 最小化視窗不算
    if win32gui.IsIconic(hwnd):
        return False


    # 取得最上層視窗
    root_hwnd = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)

    # Progman 不算
    progman = win32gui.FindWindow("Progman", "Program Manager")

    if root_hwnd == progman:
        return False

    # WorkerW 不算
    # 自己的桌面相關視窗不算
    class_name = win32gui.GetClassName(root_hwnd)

    shell_classes = {
        "Progman",
        "WorkerW",
        "Shell_TrayWnd",
        "Shell_SecondaryTrayWnd",
    }

    if class_name in shell_classes:
        return False

    # 開始功能表相關視窗不算
    window_title = win32gui.GetWindowText(root_hwnd)

    if window_title in {
        "開始",
        "Start",
    }:
        return False


    try:
        monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)

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


fullscreen_windows = set()


def is_any_fullscreen(wallpaper_hwnd) -> bool:
    """
    偵測是否有任何視窗最大化
    """

    hwnd = win32gui.GetForegroundWindow()

    if (
        hwnd == wallpaper_hwnd or               # 自己不算
        win32gui.IsChild(wallpaper_hwnd, hwnd)  # 自己的子視窗不算
    ):
        hwnd = None


    windows_new = set()


    if hwnd:
        fullscreen_windows.add(hwnd)


    for h in fullscreen_windows:
        if is_fullscreen(h):
            windows_new.add(h)


    # 更新快取
    fullscreen_windows.clear()
    fullscreen_windows.update(windows_new)


    return bool(fullscreen_windows)


class Wallpaper(QWidget):

    def __init__(self):

        super().__init__()


        # 用於防止重複執行重建的標記
        self.is_recreating = False


        self.current_video: Path | None = None
        videos = get_media()


        config = load_config()

        recent = config.get("recentVideo")

        if recent:
            recent_path = VIDEO_DIR / recent

            if recent_path.is_file():
                self.current_video = recent_path

        if not self.current_video and videos:
            self.current_video = videos[0]


        # 建立視窗
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


        self.enable_auto_pause = True
        self.play_state = "stop"  # "play", "pause", "stop"

        self.screen_off = False
        self.power_notify = None

        self.auto_pause_if_fullscreen = config.get("autoPauseIfFullscreen", True)
        self.auto_pause_if_screen_off = config.get("autoPauseIfScreenOff", True)
        self.auto_pause_if_on_battery = config.get("autoPauseIfOnBattery", False)


        # 掛載到桌布
        self.attach_to_desktop()


        # 播放
        if self.current_video:

            self.set_play_media(self.current_video)

            self.player.play()
            self.play_state = "play"
            print("init - play")


        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_auto_pause)
        self.timer.start(500)


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


            # 監聽 切換虛擬桌面/用戶 時的 WM_DESTROY 訊息
            if msg.message == win32con.WM_DESTROY:

                if not self.is_recreating:

                    # 重新掛載
                    QTimer.singleShot(200, self.reattach_to_desktop)

                return True, 0


        return super().nativeEvent(eventType, message)  # type: ignore


    def reattach_to_desktop(self) -> None:
        """
        重新建立視窗並掛載桌布
        """

        if self.is_recreating:
            return
        self.is_recreating = True

        
        print("reattach_to_desktop - start")


        # 紀錄當前播放時間進度
        curr_time = self.player.get_time()


        self.unregister_power_notification()
        self.hide()


        # 銷毀失效的 HWND , 重新向 Windows 申請新的 HWND
        self.destroy(True, True)
        self.create()


        # 建立視窗
        screen = QApplication.primaryScreen()

        self.setGeometry(screen.geometry())

        self.setWindowFlags(
            Qt.FramelessWindowHint |     # type: ignore
            Qt.Tool |                    # type: ignore
            Qt.WindowDoesNotAcceptFocus  # type: ignore
        )

        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # type: ignore
        self.show()


        # 掛載到桌布
        self.attach_to_desktop()


        # 恢復播放與時間進度
        if self.current_video:

            self.set_play_media(self.current_video)

            if curr_time > 0:
                self.player.set_time(curr_time)


        print("reattach_to_desktop - finish")
        self.is_recreating = False


    def set_play_media(self, path: Path) -> None:

        self.current_video = path

        config = load_config()
        config["recentVideo"] = path.name
        save_config(config)


        self.player.stop()
        print("set_play_media - stop")


        media = self.instance.media_new(str(path))  # type: ignore
        self.player.set_media(media)
        print(f"set_play_media - {path}")

        # 裁切填滿螢幕
        self.player.video_set_crop_geometry(self.get_screen_aspect_ratio())


        # 讓畫面跑出來
        self.player.play()
        print("set_play_media - play")


        # 回復原樣
        if self.play_state == "pause":

            self.player.pause()
            print("set_play_media - pause")

        elif self.play_state == "stop":

            self.player.stop()
            print("set_play_media - stop")


    def attach_to_desktop(self) -> None:
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


    def get_screen_aspect_ratio(self) -> str:

        screen = QApplication.primaryScreen()
        geometry = screen.geometry()

        width = geometry.width()
        height = geometry.height()

        return f"{width}:{height}"


    def check_auto_pause(self) -> None:
        """
        檢查是否需要自動暫停
        """

        # 若正在重建視窗則跳過
        if self.is_recreating:
            return

        if not self.enable_auto_pause:
            return


        hwnd = int(self.winId())


        need_auto_pause = False

        need_auto_pause = (self.auto_pause_if_fullscreen and is_any_fullscreen(hwnd)) or need_auto_pause

        need_auto_pause = (self.auto_pause_if_screen_off and self.screen_off) or need_auto_pause

        need_auto_pause = (self.auto_pause_if_on_battery and is_on_battery()) or need_auto_pause


        if need_auto_pause:
            if self.play_state == "play":

                if self.current_video and self.current_video.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
                    self.player.pause()

                self.play_state = "pause"
                print("auto_pause - pause")

        else:
            if self.play_state == "pause":

                self.player.play()
                self.play_state = "play"
                print("auto_pause - play")


    def unregister_power_notification(self) -> None:
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


        config = load_config()


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


        auto_pause_if_fullscreen_action = QAction("視窗最大化時自動暫停", menu)
        auto_pause_if_fullscreen_action.setCheckable(True)
        auto_pause_if_fullscreen_action.setChecked(
            config.get("autoPauseIfFullscreen", True)
        )

        auto_pause_if_screen_off_action = QAction("螢幕關閉時自動暫停", menu)
        auto_pause_if_screen_off_action.setCheckable(True)
        auto_pause_if_screen_off_action.setChecked(
            config.get("autoPauseIfScreenOff", True)
        )

        auto_pause_if_on_battery_action = QAction("沒插電時自動暫停", menu)
        auto_pause_if_on_battery_action.setCheckable(True)
        auto_pause_if_on_battery_action.setChecked(
            config.get("autoPauseIfOnBattery", False)
        )

        startup_action = QAction("開機自動啟動", menu)
        startup_action.setCheckable(True)
        startup_action.setChecked(task_exists())


        play_action.triggered.connect(self.play)
        pause_action.triggered.connect(self.pause)
        stop_action.triggered.connect(self.stop)
        exit_action.triggered.connect(self.exit)


        auto_pause_if_fullscreen_action.triggered.connect(self.toggle_auto_pause_if_fullscreen)
        auto_pause_if_screen_off_action.triggered.connect(self.toggle_auto_pause_if_screen_off)
        auto_pause_if_on_battery_action.triggered.connect(self.toggle_auto_pause_if_on_battery)
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
        self.options_menu.addAction(auto_pause_if_on_battery_action)

        self.options_menu.addSeparator()

        self.options_menu.addAction(startup_action)


        menu.addSeparator()


        menu.addAction(exit_action)


        self.tray.setContextMenu(menu)

        self.tray.show()


    def play(self) -> None:
        if self.wallpaper.current_video:

            self.wallpaper.player.play()

        self.wallpaper.enable_auto_pause = True
        self.wallpaper.play_state = "play"
        print("manual - play")


    def pause(self) -> None:
        if self.wallpaper.current_video:

            if self.wallpaper.current_video.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:

                if self.wallpaper.play_state == "play":

                    self.wallpaper.player.pause()


        self.wallpaper.enable_auto_pause = False
        self.wallpaper.play_state = "pause"
        print("manual - pause")


    def stop(self) -> None:

        self.wallpaper.player.stop()
        self.wallpaper.enable_auto_pause = False
        self.wallpaper.play_state = "stop"
        print("manual - stop")


    def refresh_video_menu(self) -> None:

        self.video_menu.clear()

        videos = get_media()

        if not videos:
            action = QAction("沒有影片", self.video_menu)
            action.setEnabled(False)
            self.video_menu.addAction(action)
            return

        for video in videos:
            action = QAction(video.stem, self.video_menu)

            action.triggered.connect(
                lambda checked=False, v=video: self.play_from_menu(v)
            )

            action.setCheckable(True)
            action.setChecked(video == self.wallpaper.current_video)

            self.video_menu.addAction(action)


    def play_from_menu(self, v):
        self.wallpaper.set_play_media(v)

        if self.wallpaper.current_video:

            self.wallpaper.player.play()

            self.wallpaper.enable_auto_pause = True
            self.wallpaper.play_state = "play"
            print("play_from_menu - play")


    def open_video_folder(self) -> None:
        os.startfile(str(VIDEO_DIR))


    def toggle_auto_pause_if_fullscreen(self, checked) -> None:

        config = load_config()
        config["autoPauseIfFullscreen"] = checked
        save_config(config)

        self.wallpaper.auto_pause_if_fullscreen = checked


    def toggle_auto_pause_if_screen_off(self, checked) -> None:

        config = load_config()
        config["autoPauseIfScreenOff"] = checked
        save_config(config)

        self.wallpaper.auto_pause_if_screen_off = checked


    def toggle_auto_pause_if_on_battery(self, checked) -> None:

        config = load_config()
        config["autoPauseIfOnBattery"] = checked
        save_config(config)

        self.wallpaper.auto_pause_if_on_battery = checked


    def toggle_startup(self, checked) -> None:
        if checked:
            create_task()
        else:
            delete_task()


    def exit(self) -> None:
        try:

            self.wallpaper.unregister_power_notification()

            self.wallpaper.player.stop()

            self.wallpaper.player.release()
            self.wallpaper.instance.release()

        except:
            pass

        self.app.quit()
        print("exit")


if __name__ == "__main__":

    if "--task" in sys.argv:
        # 排程啟動, 剛開機等一下
        time.sleep(1)

    else:
        run_as_admin()


    # 建立 Qt 應用程式
    app = QApplication(sys.argv)


    font = QFont()
    font.setPointSize(11)
    app.setFont(font)


    # 建立播放器
    w = Wallpaper()
    w.show()


    tray = Tray(app, w)


    # Qt 主迴圈
    sys.exit(app.exec())