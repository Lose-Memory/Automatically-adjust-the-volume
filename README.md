# Windows 11 音量自动压低（音乐避让）

本项目用于实现以下效果：

- 音乐软件正在播放时，如果网页视频或本地播放器开始出声，自动压低音乐音量。
- 视频停止后，音乐音量自动恢复。
- 降低和恢复都采用淡入淡出过渡，减少突兀感。
- 可静默后台运行，并在系统托盘显示图标，支持右键退出。

## 功能特点

- 基于 Windows 音频会话检测（`pycaw`），不是窗口标题检测，稳定性更高。
- 低延时检测策略：活动场景高频轮询，空闲场景低频轮询，兼顾响应速度与资源占用。
- 平滑过渡：音量按时间渐变，避免突然跳变。
- 所有参数都在 `config.json` 配置。
- 支持打包为无控制台窗口 EXE（托盘图标可退出）。

## 安装与运行（Python）

1. 进入项目目录并激活虚拟环境。
2. 安装依赖：

```powershell
python -m pip install -e .
```

3. 运行程序：

```powershell
python main.py
```

首次运行会自动在程序目录创建 `config.json`。

## 配置文件说明

`config.json` 与程序同级，所有行为都在这里调整。

示例：

```json
{
	"music_processes": ["cloudmusic.exe", "qqmusic.exe", "spotify.exe"],
	"trigger_processes": [
		"chrome.exe",
		"msedge.exe",
		"firefox.exe",
		"potplayermini64.exe",
		"vlc.exe",
		"mpv.exe"
	],
	"ignored_processes": [
		"system",
		"svchost.exe",
		"audiodg.exe",
		"searchhost.exe",
		"explorer.exe"
	],
	"target_volume": 0.2,
	"active_poll_interval_seconds": 0.08,
	"idle_poll_interval_seconds": 0.25,
	"audio_threshold": 0.02,
	"active_checks_to_trigger": 1,
	"silent_checks_to_restore": 2,
	"fade_down_seconds": 0.22,
	"fade_up_seconds": 0.3,
	"tray_title": "Auto Volume Ducker",
	"enable_console_logs": true
}
```

参数建议：

- `target_volume`：压低后的目标音量，`0.2` 表示 20%。
- `active_poll_interval_seconds`：有音频活动时轮询间隔，越小响应越快，但 CPU 会略升。
- `idle_poll_interval_seconds`：空闲时轮询间隔，越大越省资源。
- `audio_threshold`：判定“正在出声”的阈值。
- `active_checks_to_trigger`：连续多少次检测到视频音频后触发压低。
- `silent_checks_to_restore`：连续多少次检测到静音后开始恢复。
- `fade_down_seconds` / `fade_up_seconds`：淡出/淡入时长。

## 托盘与退出

直接运行 `python main.py` 时，会在右下角托盘显示图标。

- 右键菜单 `Reload Config`：重载配置文件。
- 右键菜单 `Exit`：退出程序。

## 打包为 EXE（无控制台窗口）

已提供打包脚本：`build_exe.ps1`

```powershell
./build_exe.ps1
```

打包完成后输出目录：`dist/auto-volume-ducker`

- 可执行文件：`dist/auto-volume-ducker/auto-volume-ducker.exe`
- 将 `config.json` 放在 EXE 同级目录。
- EXE 运行时无 cmd 弹窗，托盘有图标，可直接退出。

## 自检模式

用于快速检查程序和配置是否可用：

```powershell
python main.py --once
```

该模式只执行一次检测后退出，适合脚本验证与排错。
