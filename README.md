# BB 影片桌布

極簡版的桌布引擎, 只留下撥放影片的功能  

- 輕量
- 自動啟動

### 截圖

![截圖](./assets/screenshot.png)

# 下載

### 到 Releases 下載最新版

BB Video Wallpaper.exe  

# 使用

1. 開啟影片資料夾
2. 放影片到裡面
3. 選擇影片

# 想自己編譯?

## 需求

- [VLC](https://www.videolan.org/)

### 把 `VLC` 放在適當位置

```
bb-yt-downloader/
 ├─ icon/
 │   └─ bb-video-wallpaper.ico
 ├─ VLC/
 │   ├─ plugins/
 │   ├─ libvlc.dll
 │   ├─ libvlccore.dll
 │   └─ ...
 ├─ bb-video-wallpaper.py
 ├─ libvlc.dll
 └─ requirements.txt
```

## 執行

```bash
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
```bash
pyinstaller --noconfirm --onedir --noconsole --uac-admin --icon=icon/bb-video-wallpaper.ico --name="BB Video Wallpaper" --add-data "icon;icon" bb-video-wallpaper.py
```

打包後會在 `./dist`,  
然後將 `VLC/`, `libvlc.dll` 放在 .exe 旁邊  
像是這樣:  

```
Folder/
 ├─ icon/
 │   └─ bb-video-wallpaper.ico
 ├─ VLC/
 │   ├─ plugins/
 │   ├─ libvlc.dll
 │   ├─ libvlccore.dll
 │   └─ ...
 ├─ BB Video Wallpaper.exe
 └─ libvlc.dll
```

# 版權

MIT License