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

下方示例和参数说明顺序与 `config.json` 文件中的字段顺序保持一致，便于对照查看。

当前完整示例：

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
	"fallback_duck_non_trigger_sessions": true,
	"target_volume": 0.02,
	"active_poll_interval_seconds": 0.02,
	"idle_poll_interval_seconds": 0.05,
	"audio_threshold": 0.01,
	"active_checks_to_trigger": 1,
	"silent_checks_to_restore": 1,
	"min_duck_seconds": 0.15,
	"restore_silence_seconds": 0.35,
	"fade_down_seconds": 0.2,
	"fade_up_seconds": 0.2,
	"tray_title": "Auto Volume Ducker",
	"enable_console_logs": false,
	"enable_file_logs": true,
	"debug_session_logs": true
}
```

### 参数逐项说明（含推荐值）

1. `music_processes`

- 含义：需要被压低/恢复音量的音乐软件进程名列表。
- 格式：字符串数组，建议写完整进程名（如 `cloudmusic.exe`）。
- 推荐值：`["cloudmusic.exe", "qqmusic.exe", "spotify.exe"]`

2. `trigger_processes`

- 含义：允许触发“压低音乐音量”的视频类进程名列表。
- 格式：字符串数组。
- 推荐值：包含你常用浏览器和播放器，例如 `chrome.exe`、`msedge.exe`、`potplayermini64.exe`。

3. `ignored_processes`

- 含义：检测时忽略的系统进程，避免误触发。
- 格式：字符串数组。
- 推荐值：保留默认值，不建议随意删除。

4. `fallback_duck_non_trigger_sessions`

- 含义：当 `music_processes` 未命中时，是否启用兜底音乐会话匹配。
- 取值：`true` / `false`。
- 推荐值：`true`（兼容多进程音乐软件）。

5. `target_volume`

- 含义：触发后音乐目标音量，范围 `0.0 ~ 1.0`。
- 推荐值：`0.02 ~ 0.15`。
- 说明：`0.02` 非常低，`0.1` 更自然。

6. `active_poll_interval_seconds`

- 含义：检测到有触发活动时的轮询间隔（秒）。
- 推荐值：`0.02 ~ 0.05`。
- 说明：越小响应越快，CPU 占用会略增。

7. `idle_poll_interval_seconds`

- 含义：空闲时轮询间隔（秒）。
- 推荐值：`0.05 ~ 0.2`。
- 说明：越大越省资源，但从空闲到触发的首帧响应会变慢。

8. `audio_threshold`

- 含义：判定“该会话正在出声”的峰值阈值。
- 推荐值：`0.005 ~ 0.02`。
- 说明：太高会漏检，太低会更敏感。

9. `active_checks_to_trigger`

- 含义：连续检测到触发音频多少次才开始压低。
- 推荐值：`1`（最低延时）或 `2`（更稳）。

10. `silent_checks_to_restore`

- 含义：连续检测到静音多少次才开始恢复。
- 推荐值：`1 ~ 2`。

11. `min_duck_seconds`

- 含义：进入压低后至少保持的最短时长（秒）。
- 推荐值：`0.1 ~ 0.6`。
- 说明：过小可能抖动，过大则恢复慢。

12. `restore_silence_seconds`

- 含义：触发源持续静音多久后才允许恢复（秒）。
- 推荐值：`0.2 ~ 1.0`。
- 说明：你当前追求快速恢复可用 `0.2 ~ 0.4`。

13. `fade_down_seconds`

- 含义：压低音量的淡出时长（秒）。
- 推荐值：`0.12 ~ 0.3`。

14. `fade_up_seconds`

- 含义：恢复音量的淡入时长（秒）。
- 推荐值：`0.12 ~ 0.35`。

15. `tray_title`

- 含义：托盘图标显示的标题文本。
- 推荐值：`"Auto Volume Ducker"` 或自定义中文名。

16. `enable_console_logs`

- 含义：是否在终端打印日志。
- 取值：`true` / `false`。
- 推荐值：调试时 `true`，长期后台运行可 `false`。

17. `enable_file_logs`

- 含义：是否写入日志文件 `auto-volume-ducker.log`。
- 取值：`true` / `false`。
- 推荐值：`true`（排错方便）。

18. `debug_session_logs`

- 含义：是否输出匹配到的会话详情日志。
- 取值：`true` / `false`。
- 推荐值：调试阶段 `true`，稳定后可改 `false` 以减少日志量。

### 两套推荐模板

1. 低延时优先（你当前场景）

- `active_poll_interval_seconds`: `0.02`
- `idle_poll_interval_seconds`: `0.05`
- `audio_threshold`: `0.01`
- `active_checks_to_trigger`: `1`
- `silent_checks_to_restore`: `1`
- `min_duck_seconds`: `0.15`
- `restore_silence_seconds`: `0.35`
- `fade_down_seconds`: `0.2`
- `fade_up_seconds`: `0.2`

2. 稳定省资源优先

- `active_poll_interval_seconds`: `0.05`
- `idle_poll_interval_seconds`: `0.15`
- `audio_threshold`: `0.015`
- `active_checks_to_trigger`: `2`
- `silent_checks_to_restore`: `2`
- `min_duck_seconds`: `0.4`
- `restore_silence_seconds`: `0.8`
- `fade_down_seconds`: `0.25`
- `fade_up_seconds`: `0.35`

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
