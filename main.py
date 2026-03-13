from __future__ import annotations

import argparse
import importlib
import json
import msvcrt
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from comtypes import CoInitialize, CoUninitialize
from pycaw.pycaw import AudioUtilities, IAudioMeterInformation, ISimpleAudioVolume


@dataclass
class Settings:
    music_processes: set[str]
    trigger_processes: set[str]
    ignored_processes: set[str]
    strict_trigger_processes: bool
    fallback_duck_non_trigger_sessions: bool
    target_volume: float
    active_poll_interval_seconds: float
    idle_poll_interval_seconds: float
    audio_threshold: float
    active_checks_to_trigger: int
    silent_checks_to_restore: int
    min_duck_seconds: float
    restore_silence_seconds: float
    fade_down_seconds: float
    fade_up_seconds: float
    tray_title: str
    enable_console_logs: bool
    enable_file_logs: bool
    debug_session_logs: bool


DEFAULT_CONFIG: dict[str, Any] = {
    "music_processes": ["cloudmusic.exe", "qqmusic.exe", "spotify.exe"],
    "trigger_processes": [
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "potplayermini64.exe",
        "vlc.exe",
        "mpv.exe",
    ],
    "ignored_processes": [
        "system",
        "svchost.exe",
        "audiodg.exe",
        "searchhost.exe",
        "explorer.exe",
    ],
    "strict_trigger_processes": False,
    "fallback_duck_non_trigger_sessions": True,
    "target_volume": 0.20,
    "active_poll_interval_seconds": 0.08,
    "idle_poll_interval_seconds": 0.25,
    "audio_threshold": 0.02,
    "active_checks_to_trigger": 1,
    "silent_checks_to_restore": 2,
    "min_duck_seconds": 1.0,
    "restore_silence_seconds": 1.2,
    "fade_down_seconds": 0.22,
    "fade_up_seconds": 0.30,
    "tray_title": "Auto Volume Ducker",
    "enable_console_logs": True,
    "enable_file_logs": True,
    "debug_session_logs": True,
}


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _normalize_process_name(name: str | None) -> str:
    return (name or "").strip().lower()


def _process_name_stem(name: str) -> str:
    if name.endswith(".exe"):
        return name[:-4]
    return name


def _in_process_set(process_name: str, process_set: set[str]) -> bool:
    if process_name in process_set:
        return True
    stem = _process_name_stem(process_name)
    for item in process_set:
        if _process_name_stem(item) == stem:
            return True
    return False


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def load_or_create_config(config_path: Path) -> Settings:
    if not config_path.exists():
        config_path.write_text(
            json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Created config file: {config_path}")

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    merged = DEFAULT_CONFIG | raw

    return Settings(
        music_processes={
            _normalize_process_name(x) for x in merged["music_processes"] if x
        },
        trigger_processes={
            _normalize_process_name(x) for x in merged["trigger_processes"] if x
        },
        ignored_processes={
            _normalize_process_name(x) for x in merged["ignored_processes"] if x
        },
        strict_trigger_processes=bool(merged["strict_trigger_processes"]),
        fallback_duck_non_trigger_sessions=bool(
            merged["fallback_duck_non_trigger_sessions"]
        ),
        target_volume=_clamp_unit(float(merged["target_volume"])),
        active_poll_interval_seconds=max(
            0.03, float(merged["active_poll_interval_seconds"])
        ),
        idle_poll_interval_seconds=max(
            0.08, float(merged["idle_poll_interval_seconds"])
        ),
        audio_threshold=max(0.0, float(merged["audio_threshold"])),
        active_checks_to_trigger=max(1, int(merged["active_checks_to_trigger"])),
        silent_checks_to_restore=max(1, int(merged["silent_checks_to_restore"])),
        min_duck_seconds=max(0.0, float(merged["min_duck_seconds"])),
        restore_silence_seconds=max(0.0, float(merged["restore_silence_seconds"])),
        fade_down_seconds=max(0.01, float(merged["fade_down_seconds"])),
        fade_up_seconds=max(0.01, float(merged["fade_up_seconds"])),
        tray_title=str(merged["tray_title"]),
        enable_console_logs=bool(merged["enable_console_logs"]),
        enable_file_logs=bool(merged["enable_file_logs"]),
        debug_session_logs=bool(merged["debug_session_logs"]),
    )


def _get_session_process_name(session: Any) -> str:
    try:
        if session.Process:
            return _normalize_process_name(session.Process.name())
    except Exception:
        return ""
    return ""


def _get_session_pid(session: Any) -> int:
    try:
        if session.Process:
            return int(session.Process.pid)
    except Exception:
        return -1
    return -1


def _is_trigger_candidate(process_name: str, settings: Settings) -> bool:
    if not process_name:
        return False
    if _in_process_set(process_name, settings.music_processes):
        return False
    if _in_process_set(process_name, settings.ignored_processes):
        return False

    # If trigger list is configured, only these processes can trigger ducking.
    if settings.trigger_processes:
        return _in_process_set(process_name, settings.trigger_processes)

    # Backward-compatible fallback: no trigger list means any non-ignored app can trigger.
    return True


def _is_in_trigger_list(process_name: str, settings: Settings) -> bool:
    return bool(settings.trigger_processes) and _in_process_set(
        process_name, settings.trigger_processes
    )


def _session_has_audio(session: Any, threshold: float) -> bool:
    try:
        meter = session._ctl.QueryInterface(IAudioMeterInformation)
        return meter.GetPeakValue() >= threshold
    except Exception:
        return False


def _approach(current: float, target: float, max_delta: float) -> float:
    if abs(target - current) <= max_delta:
        return target
    if target > current:
        return current + max_delta
    return current - max_delta


class AudioDucker:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.settings = load_or_create_config(config_path)
        self.log_path = config_path.with_name("auto-volume-ducker.log")
        self.stop_event = threading.Event()
        self.reload_event = threading.Event()
        self.ducking = False
        self.active_streak = 0
        self.silent_streak = 0
        self.original_volumes: dict[int, float] = {}
        self._last_no_music_log_at = 0.0
        self._last_session_debug_log_at = 0.0
        self._duck_started_at = 0.0
        self._last_trigger_audio_at = 0.0
        self._session_volume_cache: dict[int, tuple[Any, float]] = {}

    def _log(self, msg: str) -> None:
        if self.settings.enable_console_logs:
            print(msg)
        if self.settings.enable_file_logs:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                with self.log_path.open("a", encoding="utf-8") as f:
                    f.write(f"[{timestamp}] {msg}\n")
            except Exception:
                pass

    def request_reload(self) -> None:
        self.reload_event.set()

    def stop(self) -> None:
        self.stop_event.set()

    def _restore_all_known_volumes(self) -> None:
        # Try to restore every process volume we touched, even when exiting mid-duck.
        for pid, (vol, original) in list(self._session_volume_cache.items()):
            try:
                vol.SetMasterVolume(_clamp_unit(original), None)
            except Exception:
                continue

        # Best-effort restore for any sessions currently visible.
        try:
            for session in AudioUtilities.GetAllSessions():
                process_name = _get_session_process_name(session)
                if not _in_process_set(process_name, self.settings.music_processes):
                    continue
                pid = _get_session_pid(session)
                if pid not in self.original_volumes:
                    continue
                try:
                    vol = session._ctl.QueryInterface(ISimpleAudioVolume)
                    vol.SetMasterVolume(_clamp_unit(self.original_volumes[pid]), None)
                except Exception:
                    continue
        except Exception:
            pass

        self.original_volumes.clear()
        self._session_volume_cache.clear()
        self.ducking = False

    def _collect_audio_state(
        self,
    ) -> tuple[bool, list[tuple[int, str, str, Any, float]], bool]:
        trigger_audio = False
        music_sessions: list[tuple[int, str, str, Any, float]] = []
        fallback_sessions: list[tuple[int, str, str, Any, float]] = []

        for session in AudioUtilities.GetAllSessions():
            process_name = _get_session_process_name(session)

            if _is_trigger_candidate(process_name, self.settings):
                if _session_has_audio(session, self.settings.audio_threshold):
                    trigger_audio = True

            if _in_process_set(process_name, self.settings.music_processes):
                try:
                    pid = _get_session_pid(session)
                    volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                    current = _clamp_unit(volume.GetMasterVolume())
                    music_sessions.append(
                        (pid, process_name, "configured", volume, current)
                    )
                except Exception:
                    continue
                continue

            if (
                self.settings.fallback_duck_non_trigger_sessions
                and process_name
                and (not _in_process_set(process_name, self.settings.ignored_processes))
                and (not _is_in_trigger_list(process_name, self.settings))
            ):
                try:
                    if not _session_has_audio(
                        session, max(0.005, self.settings.audio_threshold * 0.5)
                    ):
                        continue
                    pid = _get_session_pid(session)
                    volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                    current = _clamp_unit(volume.GetMasterVolume())
                    fallback_sessions.append(
                        (pid, process_name, "fallback", volume, current)
                    )
                except Exception:
                    continue

        used_fallback = False
        if not music_sessions and fallback_sessions:
            music_sessions = fallback_sessions
            used_fallback = True

        return trigger_audio, music_sessions, used_fallback

    def _update_mode(self, trigger_audio: bool, now: float) -> str | None:
        if trigger_audio:
            self._last_trigger_audio_at = now
            self.active_streak += 1
            self.silent_streak = 0
        else:
            self.silent_streak += 1
            self.active_streak = 0

        if (
            not self.ducking
            and self.active_streak >= self.settings.active_checks_to_trigger
        ):
            self.ducking = True
            self._duck_started_at = now
            self._log("Video audio detected, start ducking.")
            return "duck_start"

        if (
            self.ducking
            and self.silent_streak >= self.settings.silent_checks_to_restore
            and (now - self._last_trigger_audio_at)
            >= self.settings.restore_silence_seconds
            and (now - self._duck_started_at) >= self.settings.min_duck_seconds
        ):
            self.ducking = False
            self._log("Video audio stopped, start restoring.")
            return "duck_stop"

        return None

    def _log_matched_sessions(
        self,
        music_sessions: list[tuple[int, str, str, Any, float]],
        trigger_audio: bool,
    ) -> None:
        if not self.settings.debug_session_logs:
            return

        now = time.monotonic()
        if now - self._last_session_debug_log_at < 4.0:
            return

        self._last_session_debug_log_at = now

        if not music_sessions:
            self._log("Matched music sessions: none")
            return

        labels = [
            f"{name or 'unknown'}(pid={pid},src={src},vol={current:.2f})"
            for pid, name, src, _, current in music_sessions
        ]
        state = "trigger_on" if trigger_audio else "trigger_off"
        self._log(f"Matched music sessions [{state}]: " + ", ".join(labels))

    def _apply_volume_step(
        self,
        music_sessions: list[tuple[int, str, str, Any, float]],
        loop_interval: float,
    ) -> None:
        seen_pids = {pid for pid, _, _, _, _ in music_sessions}

        for pid, _, _, vol, current in music_sessions:
            if self.ducking and pid not in self.original_volumes:
                self.original_volumes[pid] = current
                self._session_volume_cache[pid] = (vol, current)
            elif pid in self.original_volumes:
                self._session_volume_cache[pid] = (vol, self.original_volumes[pid])

            if self.ducking:
                target = self.settings.target_volume
                max_delta = loop_interval / self.settings.fade_down_seconds
            else:
                target = self.original_volumes.get(pid, current)
                max_delta = loop_interval / self.settings.fade_up_seconds

            # Keep transitions smooth and avoid abrupt jumps.
            max_delta = min(0.12, max(0.005, max_delta))

            next_volume = _clamp_unit(_approach(current, target, max_delta))
            if abs(next_volume - current) >= 0.001:
                try:
                    vol.SetMasterVolume(next_volume, None)
                except Exception:
                    continue

            if (not self.ducking) and (pid in self.original_volumes):
                if abs(target - next_volume) < 0.01:
                    self.original_volumes.pop(pid, None)
                    self._session_volume_cache.pop(pid, None)

        for pid in tuple(self.original_volumes):
            if pid not in seen_pids:
                self.original_volumes.pop(pid, None)
                self._session_volume_cache.pop(pid, None)

    def run_once(self) -> None:
        CoInitialize()
        try:
            trigger_audio, music_sessions, _ = self._collect_audio_state()
            self._update_mode(trigger_audio, time.monotonic())
            self._apply_volume_step(
                music_sessions, self.settings.active_poll_interval_seconds
            )
        finally:
            CoUninitialize()

    def run_forever(self) -> None:
        CoInitialize()
        try:
            self._log("Auto volume ducking started.")
            self._log(f"Config: {self.config_path}")
            self._log(f"Music processes: {sorted(self.settings.music_processes)}")
            self._log(f"Trigger processes: {sorted(self.settings.trigger_processes)}")

            while not self.stop_event.is_set():
                if self.reload_event.is_set():
                    self.settings = load_or_create_config(self.config_path)
                    self.reload_event.clear()
                    self._log("Config reloaded.")

                trigger_audio, music_sessions, used_fallback = (
                    self._collect_audio_state()
                )
                now = time.monotonic()
                transition = self._update_mode(trigger_audio, now)

                if transition == "duck_start":
                    self._log_matched_sessions(music_sessions, trigger_audio)

                if used_fallback and trigger_audio:
                    now = time.monotonic()
                    if now - self._last_no_music_log_at >= 5.0:
                        self._log(
                            "Using fallback music session matching (config music_processes not matched)."
                        )
                        self._last_no_music_log_at = now

                if trigger_audio and not music_sessions:
                    now = time.monotonic()
                    if now - self._last_no_music_log_at >= 5.0:
                        self._log(
                            "Trigger audio detected but no music session matched; check music_processes in config.json."
                        )
                        self._last_no_music_log_at = now

                interval = (
                    self.settings.active_poll_interval_seconds
                    if (self.ducking or trigger_audio)
                    else self.settings.idle_poll_interval_seconds
                )
                self._apply_volume_step(music_sessions, interval)
                self.stop_event.wait(interval)
        finally:
            self._restore_all_known_volumes()
            self._log("Volumes restored; service stopped.")
            CoUninitialize()


def _watch_esc_to_stop(ducker: AudioDucker) -> None:
    while not ducker.stop_event.is_set():
        try:
            if msvcrt.kbhit():
                key = msvcrt.getwch()
                if key == "\x1b":  # ESC
                    ducker._log("ESC pressed, stopping service.")
                    ducker.stop()
                    return
        except Exception:
            return
        time.sleep(0.05)


def _watch_stdin_command_to_stop(ducker: AudioDucker) -> None:
    # Allows users to type "esc" + Enter when ESC key capture is unavailable.
    while not ducker.stop_event.is_set():
        try:
            line = sys.stdin.readline()
        except Exception:
            return

        if not line:
            return

        cmd = line.strip().lower()
        if cmd in {"esc", "exit", "quit", "q"}:
            ducker._log("Stop command received from stdin, stopping service.")
            ducker.stop()
            return


class TrayHost:
    def __init__(self, ducker: AudioDucker):
        self.ducker = ducker
        self.icon: Any = None
        self.worker = threading.Thread(target=self.ducker.run_forever, daemon=True)
        self.pystray = importlib.import_module("pystray")
        pil_image = importlib.import_module("PIL.Image")
        pil_draw = importlib.import_module("PIL.ImageDraw")
        self.Image = pil_image
        self.ImageDraw = pil_draw

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
        self.ducker.request_reload()

    def _on_exit(self, icon: Any, _item: Any) -> None:
        self.ducker.stop()
        icon.stop()

    def run(self) -> None:
        self.worker.start()
        self.icon = self.pystray.Icon(
            "auto_volume_ducker",
            self._build_icon_image(),
            self.ducker.settings.tray_title,
            self.pystray.Menu(
                self.pystray.MenuItem("Reload Config", self._on_reload),
                self.pystray.MenuItem("Exit", self._on_exit),
            ),
        )
        self.icon.run()
        self.ducker.stop()
        self.worker.join(timeout=2.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Windows audio ducking service")
    parser.add_argument("--once", action="store_true", help="run one loop then exit")
    parser.add_argument(
        "--no-tray", action="store_true", help="run in foreground without tray icon"
    )
    parser.add_argument("--config", type=str, default="", help="custom config path")
    return parser.parse_args()


def run() -> None:
    args = parse_args()
    config_path = (
        Path(args.config).resolve() if args.config else get_base_dir() / "config.json"
    )
    ducker = AudioDucker(config_path)

    if args.once:
        ducker.run_once()
        print("Self-check done.")
        return

    if args.no_tray:
        print("Press ESC, or type 'esc' then Enter, to stop and restore volume.")
        esc_thread = threading.Thread(
            target=_watch_esc_to_stop, args=(ducker,), daemon=True
        )
        esc_thread.start()
        stdin_thread = threading.Thread(
            target=_watch_stdin_command_to_stop, args=(ducker,), daemon=True
        )
        stdin_thread.start()
        ducker.run_forever()
        return

    try:
        importlib.import_module("pystray")
        importlib.import_module("PIL.Image")
        importlib.import_module("PIL.ImageDraw")
    except ImportError as exc:
        raise RuntimeError(
            "Missing tray dependencies. Install with: pip install pystray pillow"
        ) from exc

    tray = TrayHost(ducker)
    tray.run()


if __name__ == "__main__":
    run()
