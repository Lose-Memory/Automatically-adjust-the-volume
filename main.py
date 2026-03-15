from __future__ import annotations

import argparse
import ctypes
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from comtypes import CoInitialize, CoUninitialize
from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

KEYEVENTF_KEYUP = 0x0002
AUDIO_THRESHOLD = 0.01
HOTKEY_RETRY_LIMIT = 3
HOTKEY_VERIFY_DELAY_SECONDS = 0.25
PAUSE_VERIFY_TIMEOUT_SECONDS = 1.2
RESUME_VERIFY_TIMEOUT_SECONDS = 1.5
VERIFY_POLL_INTERVAL_SECONDS = 0.1
VERIFY_CONSECUTIVE_HITS_PAUSE = 1
VERIFY_CONSECUTIVE_HITS_RESUME = 2
RETRY_GAP_SECONDS = 0.25


@dataclass
class Settings:
    music_processes: set[str]
    video_processes: set[str]
    poll_interval_ms: int
    video_stop_grace_ms: int
    toggle_hotkey: str
    enable_logs: bool


DEFAULT_CONFIG: dict[str, object] = {
    "music_processes": ["cloudmusic.exe", "qqmusic.exe", "spotify.exe"],
    "video_processes": [
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "potplayermini64.exe",
    ],
    "poll_interval_ms": 80,
    "video_stop_grace_ms": 1200,
    "toggle_hotkey": "alt+ctrl+q",
    "enable_logs": True,
}


class Logger:
    def __init__(self, config_path: Path, enabled: bool) -> None:
        self.enabled = enabled
        self.log_path = config_path.with_name("auto-volume-ducker.log")

    def log(self, message: str) -> None:
        if not self.enabled:
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        print(line)
        try:
            with self.log_path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
        except Exception:
            pass


class RuntimeControl:
    def __init__(self, settings: Settings):
        self.stop_event = threading.Event()
        self.reload_event = threading.Event()
        self._lock = threading.Lock()
        self.settings = settings
        self.hotkey_vks = parse_hotkey(settings.toggle_hotkey)

    def snapshot(self) -> tuple[Settings, list[int]]:
        with self._lock:
            return self.settings, list(self.hotkey_vks)

    def request_reload(self) -> None:
        self.reload_event.set()

    def apply_reload(self, config_path: Path, logger: Logger) -> bool:
        try:
            new_settings = load_or_create_config(config_path)
            new_hotkey_vks = parse_hotkey(new_settings.toggle_hotkey)
        except Exception as exc:
            logger.log(f"Reload failed: {exc}")
            return False

        with self._lock:
            self.settings = new_settings
            self.hotkey_vks = new_hotkey_vks

        logger.log("Config reloaded.")
        logger.log(f"music_processes={sorted(new_settings.music_processes)}")
        logger.log(f"video_processes={sorted(new_settings.video_processes)}")
        logger.log(f"poll_interval_ms={new_settings.poll_interval_ms}")
        logger.log(f"video_stop_grace_ms={new_settings.video_stop_grace_ms}")
        logger.log(f"toggle_hotkey={new_settings.toggle_hotkey}")
        return True


def get_base_dir() -> Path:
    return Path(__file__).resolve().parent


def normalize_process_name(name: str | None) -> str:
    return (name or "").strip().lower()


def load_or_create_config(config_path: Path) -> Settings:
    if not config_path.exists():
        config_path.write_text(
            json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    raw = json.loads(config_path.read_text(encoding="utf-8"))

    music_processes = {
        normalize_process_name(item)
        for item in raw.get("music_processes", DEFAULT_CONFIG["music_processes"])
        if item
    }
    video_processes = {
        normalize_process_name(item)
        for item in raw.get("video_processes", DEFAULT_CONFIG["video_processes"])
        if item
    }

    return Settings(
        music_processes=music_processes,
        video_processes=video_processes,
        poll_interval_ms=max(
            20, int(raw.get("poll_interval_ms", DEFAULT_CONFIG["poll_interval_ms"]))
        ),
        video_stop_grace_ms=max(
            0,
            int(raw.get("video_stop_grace_ms", DEFAULT_CONFIG["video_stop_grace_ms"])),
        ),
        toggle_hotkey=str(raw.get("toggle_hotkey", DEFAULT_CONFIG["toggle_hotkey"])),
        enable_logs=bool(raw.get("enable_logs", DEFAULT_CONFIG["enable_logs"])),
    )


def get_session_process_name(session: object) -> str:
    try:
        process = session.Process
        if process:
            return normalize_process_name(process.name())
    except Exception:
        return ""
    return ""


def session_has_audio(session: object, threshold: float) -> bool:
    try:
        meter = session._ctl.QueryInterface(IAudioMeterInformation)
        return meter.GetPeakValue() >= threshold
    except Exception:
        return False


def get_play_states(settings: Settings) -> tuple[bool, bool]:
    music_playing = False
    video_playing = False

    for session in AudioUtilities.GetAllSessions():
        process_name = get_session_process_name(session)
        if not process_name:
            continue

        if (not music_playing) and process_name in settings.music_processes:
            music_playing = session_has_audio(session, AUDIO_THRESHOLD)

        if (not video_playing) and process_name in settings.video_processes:
            video_playing = session_has_audio(session, AUDIO_THRESHOLD)

        if music_playing and video_playing:
            break

    return music_playing, video_playing


def vk_from_token(token: str) -> int | None:
    key = token.strip().lower()
    special: dict[str, int] = {
        "ctrl": 0x11,
        "control": 0x11,
        "alt": 0x12,
        "shift": 0x10,
        "win": 0x5B,
        "windows": 0x5B,
        "space": 0x20,
        "enter": 0x0D,
        "tab": 0x09,
        "esc": 0x1B,
        "escape": 0x1B,
        "up": 0x26,
        "down": 0x28,
        "left": 0x25,
        "right": 0x27,
        "media_play_pause": 0xB3,
        "media_stop": 0xB2,
        "media_next": 0xB0,
        "media_prev": 0xB1,
    }
    if key in special:
        return special[key]

    if len(key) == 1 and "a" <= key <= "z":
        return ord(key.upper())
    if len(key) == 1 and "0" <= key <= "9":
        return ord(key)
    if len(key) >= 2 and key.startswith("f") and key[1:].isdigit():
        fn = int(key[1:])
        if 1 <= fn <= 24:
            return 0x6F + fn
    return None


def parse_hotkey(combo: str) -> list[int]:
    parts = [part.strip() for part in combo.split("+") if part.strip()]
    if not parts:
        raise ValueError("toggle_hotkey cannot be empty")

    vks: list[int] = []
    for part in parts:
        vk = vk_from_token(part)
        if vk is None:
            raise ValueError(f"Unsupported hotkey token: {part}")
        vks.append(vk)
    return vks


def send_hotkey(vks: list[int]) -> bool:
    try:
        for vk in vks:
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        for vk in reversed(vks):
            ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        return False


def wait_for_music_target(
    target_music_playing: bool,
    video_expected: bool,
    timeout_seconds: float,
    required_hits: int,
    settings: Settings,
    logger: Logger,
) -> tuple[bool, bool]:
    deadline = time.monotonic() + timeout_seconds
    hit_count = 0

    while True:
        current_music, current_video = get_play_states(settings)

        if current_video != video_expected:
            logger.log("Video state changed while verifying hotkey result.")
            return False, True

        if current_music == target_music_playing:
            hit_count += 1
            if hit_count >= required_hits:
                return True, False
        else:
            hit_count = 0

        if time.monotonic() >= deadline:
            return False, False

        time.sleep(VERIFY_POLL_INTERVAL_SECONDS)


def try_reach_music_state(
    target_music_playing: bool,
    video_expected: bool,
    hotkey_vks: list[int],
    settings: Settings,
    logger: Logger,
) -> bool:
    for attempt in range(1, HOTKEY_RETRY_LIMIT + 1):
        current_music, current_video = get_play_states(settings)

        if current_video != video_expected:
            logger.log("Video state changed before sending hotkey; cancel transition.")
            return False

        if current_music == target_music_playing:
            logger.log(
                f"Target already reached before attempt {attempt}; music_playing={current_music}."
            )
            return True

        if not send_hotkey(hotkey_vks):
            logger.log(f"Hotkey send failed on attempt {attempt}/{HOTKEY_RETRY_LIMIT}.")
            time.sleep(RETRY_GAP_SECONDS)
            continue

        if target_music_playing:
            verify_timeout = RESUME_VERIFY_TIMEOUT_SECONDS
            required_hits = VERIFY_CONSECUTIVE_HITS_RESUME
        else:
            # Pause state may take a few hundred ms to reflect on audio meters.
            verify_timeout = max(
                HOTKEY_VERIFY_DELAY_SECONDS, PAUSE_VERIFY_TIMEOUT_SECONDS
            )
            required_hits = VERIFY_CONSECUTIVE_HITS_PAUSE

        ok, video_changed = wait_for_music_target(
            target_music_playing=target_music_playing,
            video_expected=video_expected,
            timeout_seconds=verify_timeout,
            required_hits=required_hits,
            settings=settings,
            logger=logger,
        )

        if ok:
            logger.log(f"Hotkey succeeded on attempt {attempt}/{HOTKEY_RETRY_LIMIT}.")
            return True

        if video_changed:
            return False

        logger.log(
            f"Hotkey attempt {attempt}/{HOTKEY_RETRY_LIMIT} did not reach target state."
        )
        time.sleep(RETRY_GAP_SECONDS)

    logger.log("Hotkey retries exhausted; target music state not reached.")
    return False


def service_loop(
    config_path: Path,
    control: RuntimeControl,
    once: bool,
) -> None:
    settings, hotkey_vks = control.snapshot()
    logger = Logger(config_path, settings.enable_logs)
    poll_seconds = settings.poll_interval_ms / 1000.0

    video_active = False
    music_was_playing_before_video = False
    music_paused_by_service = False
    video_stop_started_at: float | None = None

    logger.log("Service started.")
    logger.log(f"music_processes={sorted(settings.music_processes)}")
    logger.log(f"video_processes={sorted(settings.video_processes)}")
    logger.log(f"poll_interval_ms={settings.poll_interval_ms}")
    logger.log(f"video_stop_grace_ms={settings.video_stop_grace_ms}")
    logger.log(f"toggle_hotkey={settings.toggle_hotkey}")

    CoInitialize()
    try:
        while not control.stop_event.is_set():
            if control.reload_event.is_set():
                if control.apply_reload(config_path, logger):
                    settings, hotkey_vks = control.snapshot()
                    poll_seconds = settings.poll_interval_ms / 1000.0
                    logger.enabled = settings.enable_logs
                    # Reset transition memory to avoid toggling on stale state.
                    video_active = False
                    music_was_playing_before_video = False
                    music_paused_by_service = False
                    video_stop_started_at = None
                control.reload_event.clear()

            settings, hotkey_vks = control.snapshot()
            poll_seconds = settings.poll_interval_ms / 1000.0
            music_playing, video_playing = get_play_states(settings)

            if (not video_active) and video_playing:
                video_active = True
                video_stop_started_at = None
                music_was_playing_before_video = music_playing
                logger.log(
                    f"Transition nq->q detected; music_playing_before_video={music_was_playing_before_video}."
                )

                if music_was_playing_before_video:
                    music_paused_by_service = try_reach_music_state(
                        target_music_playing=False,
                        video_expected=True,
                        hotkey_vks=hotkey_vks,
                        settings=settings,
                        logger=logger,
                    )
                else:
                    music_paused_by_service = False

            elif video_active:
                if video_playing:
                    video_stop_started_at = None
                else:
                    now = time.monotonic()
                    if video_stop_started_at is None:
                        video_stop_started_at = now
                    else:
                        gap_ms = int((now - video_stop_started_at) * 1000)
                        if gap_ms >= settings.video_stop_grace_ms:
                            video_active = False
                            video_stop_started_at = None
                            logger.log("Transition q->nq confirmed after grace period.")

                            if (
                                music_was_playing_before_video
                                and music_paused_by_service
                            ):
                                try_reach_music_state(
                                    target_music_playing=True,
                                    video_expected=False,
                                    hotkey_vks=hotkey_vks,
                                    settings=settings,
                                    logger=logger,
                                )
                            music_was_playing_before_video = False
                            music_paused_by_service = False

            if once:
                break

            control.stop_event.wait(poll_seconds)
    finally:
        CoUninitialize()


class TrayHost:
    def __init__(self, control: RuntimeControl, config_path: Path):
        self.control = control
        self.config_path = config_path
        self.worker = threading.Thread(
            target=service_loop,
            args=(config_path, self.control, False),
            daemon=True,
        )
        self.icon: Any = None

        pystray_module = __import__("pystray")
        image_module = __import__("PIL.Image", fromlist=["Image"])
        draw_module = __import__("PIL.ImageDraw", fromlist=["ImageDraw"])
        self.pystray = pystray_module
        self.Image = image_module
        self.ImageDraw = draw_module

    def _build_icon_image(self) -> Any:
        size = 64
        image = self.Image.new("RGBA", (size, size), (28, 28, 32, 255))
        draw = self.ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill=(66, 133, 244, 255))
        draw.rectangle((20, 30, 32, 42), fill=(255, 255, 255, 255))
        draw.polygon(
            [(32, 28), (44, 22), (44, 50), (32, 44)], fill=(255, 255, 255, 255)
        )
        return image

    def _on_reload(self, _icon: Any, _item: Any) -> None:
        self.control.request_reload()

    def _on_exit(self, icon: Any, _item: Any) -> None:
        self.control.stop_event.set()
        icon.stop()

    def run(self) -> None:
        self.worker.start()
        self.icon = self.pystray.Icon(
            "auto_music_pause",
            self._build_icon_image(),
            "Auto Music Pause",
            self.pystray.Menu(
                self.pystray.MenuItem("Reload Config", self._on_reload),
                self.pystray.MenuItem("Exit", self._on_exit),
            ),
        )
        self.icon.run()
        self.control.stop_event.set()
        self.worker.join(timeout=2.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pause music when video plays")
    parser.add_argument(
        "--once", action="store_true", help="run one poll loop then exit"
    )
    parser.add_argument("--no-tray", action="store_true", help="run foreground mode")
    parser.add_argument("--config", type=str, default="", help="custom config path")
    return parser.parse_args()


def run() -> None:
    args = parse_args()
    config_path = (
        Path(args.config).resolve() if args.config else get_base_dir() / "config.json"
    )
    settings = load_or_create_config(config_path)
    control = RuntimeControl(settings)

    if args.once:
        service_loop(config_path, control, once=True)
        return

    if args.no_tray:
        service_loop(config_path, control, once=False)
        return

    try:
        tray = TrayHost(control, config_path)
    except Exception as exc:
        raise RuntimeError(
            "Tray dependencies missing. Install with: pip install pystray pillow"
        ) from exc

    tray.run()


if __name__ == "__main__":
    run()
