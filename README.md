# Auto Music Pause

最小化版本：只做一件事。

- 严格匹配你配置的音乐进程和视频进程（完全匹配进程名，不匹配不处理）。
- 当音乐在播放且视频开始播放时，发送一次快捷键暂停音乐。
- 当视频停止后：
- 如果视频开始前音乐是播放状态，则发送一次快捷键恢复。
- 如果视频开始前音乐不是播放状态，则保持不播放。

如果发送快捷键后未达到目标状态，程序会自动重试，最多重试固定次数并写日志，避免死循环。

程序默认以托盘模式运行（后台无控制台窗口），右键托盘图标可退出。

## 配置参数（6 项）

配置文件： [config.json](config.json)

```json
{
	"music_processes": ["cloudmusic.exe", "qqmusic.exe"],
	"video_processes": ["chrome.exe", "msedge.exe", "potplayermini64.exe"],
	"poll_interval_ms": 80,
	"video_stop_grace_ms": 1500,
	"toggle_hotkey": "alt+ctrl+q",
	"enable_logs": true
}
```

- `music_processes`：监控的音乐进程列表。
- `video_processes`：监控的视频进程列表。
- `poll_interval_ms`：轮询间隔，单位毫秒。
- `video_stop_grace_ms`：视频从有声到无声后，至少持续多久才判定为真正停止，单位毫秒。用于避免短暂空窗导致误恢复。推荐 `1200~2500`。
- `toggle_hotkey`：一个快捷键，同时用于暂停和恢复。
- `enable_logs`：是否记录日志（终端 + `auto-volume-ducker.log`）。

## 运行

```powershell
python -m pip install -e .
python main.py
```

## 自检

```powershell
python main.py --once
```

## 打包

```powershell
./build_exe.ps1
```

输出： [dist/auto-volume-ducker/auto-volume-ducker.exe](dist/auto-volume-ducker/auto-volume-ducker.exe)
