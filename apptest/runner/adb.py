"""ADB device wrapper for Android emulator/device control."""

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def start_fresh_emulator(
    avd: str | None = None,
    timeout: int = 120,
) -> str:
    """Start a fresh emulator on an available port.

    Args:
        avd: AVD name to launch. If None, picks the first from ``emulator -list-avds``.
        timeout: Seconds to wait for the emulator to boot.

    Returns:
        ADB serial string, e.g. ``"emulator-5556"``.
    """
    # Find emulator binary
    emulator_bin = shutil.which("emulator")
    if not emulator_bin:
        sdk_path = Path.home() / "Library" / "Android" / "sdk" / "emulator" / "emulator"
        if sdk_path.exists():
            emulator_bin = str(sdk_path)
        else:
            raise RuntimeError(
                "emulator binary not found. Ensure Android SDK emulator is on PATH "
                "or installed at ~/Library/Android/sdk/emulator/emulator"
            )

    # Pick AVD
    if not avd:
        result = subprocess.run(
            [emulator_bin, "-list-avds"],
            capture_output=True, text=True, timeout=10,
        )
        avds = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not avds:
            raise RuntimeError("No AVDs found. Create one with: avdmanager create avd ...")
        avd = avds[0]
        logger.info("Auto-selected AVD: %s", avd)

    # Find an available port (even ports: 5554, 5556, 5558, ...)
    port = _find_available_emulator_port()
    serial = f"emulator-{port}"
    logger.info("Starting emulator %s on port %d (AVD=%s)", serial, port, avd)

    # Launch emulator in background
    subprocess.Popen(
        [emulator_bin, "-avd", avd, "-port", str(port), "-no-boot-anim"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for boot
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["adb", "-s", serial, "shell", "getprop", "sys.boot_completed"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip() == "1":
                logger.info("Emulator %s booted successfully", serial)
                return serial
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        time.sleep(2)

    raise RuntimeError(f"Emulator {serial} did not boot within {timeout}s")


def _find_available_emulator_port(start: int = 5554, end: int = 5600) -> int:
    """Scan even ports and return the first one with no running emulator."""
    for port in range(start, end, 2):
        try:
            result = subprocess.run(
                ["adb", "-s", f"emulator-{port}", "get-state"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode != 0 or "device" not in result.stdout:
                return port
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return port
    raise RuntimeError(f"No available emulator port in range {start}-{end}")


class ADBDevice:
    """Wraps ADB subprocess calls for device interaction."""

    def __init__(self, serial: str = "emulator-5554"):
        self.serial = serial

    def _run(self, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Run an ADB command and return the result."""
        cmd = ["adb", "-s", self.serial] + args
        logger.debug("ADB: %s", " ".join(cmd))
        try:
            return subprocess.run(
                cmd, capture_output=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"ADB command timed out: {' '.join(cmd)}") from e
        except FileNotFoundError:
            raise RuntimeError(
                "adb not found. Ensure Android SDK platform-tools is on PATH."
            )

    def _run_check(self, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Run an ADB command, raising on failure."""
        result = self._run(args, timeout=timeout)
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"ADB command failed: {' '.join(args)}: {stderr}")
        return result

    # ---- Connection ----

    def is_connected(self) -> bool:
        """Check if the device is connected and responsive."""
        result = self._run(["get-state"])
        return result.returncode == 0 and b"device" in result.stdout

    def wait_for_device(self, timeout: int = 30) -> None:
        """Block until device is online, with timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_connected():
                return
            time.sleep(1)
        raise RuntimeError(
            f"Device {self.serial} not connected after {timeout}s. "
            "Start an emulator with: emulator -avd <avd_name>"
        )

    def wake_and_unlock(self) -> None:
        """Wake the device screen and dismiss the lock screen.

        Sends WAKEUP keyevent to turn on the display, then MENU (82)
        to dismiss the lock screen.  Safe to call if already awake.
        """
        self._run(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])
        time.sleep(0.5)
        # Dismiss lock screen (swipe up / MENU keyevent)
        self._run(["shell", "input", "keyevent", "82"])
        time.sleep(1.0)
        # Verify wakefulness
        result = self._run(["shell", "dumpsys", "power"])
        text = result.stdout.decode(errors="replace") if result.stdout else ""
        if "mWakefulness=Awake" not in text:
            # Try swipe as second attempt
            w, h = self.get_screen_size()
            self._run(["shell", "input", "swipe",
                        str(w // 2), str(h * 3 // 4),
                        str(w // 2), str(h // 4), "300"])
            time.sleep(1.0)
        logger.info("Device woken and unlocked")

    # ---- Screenshots ----

    def screenshot_bytes(self) -> bytes:
        """Capture a screenshot and return raw PNG bytes.

        Tries the fast ``exec-out screencap -p`` path first.  Some real
        devices return 0 bytes with ``exec-out``, so we fall back to
        ``shell screencap`` + ``pull`` if the result is empty.
        """
        result = self._run(["exec-out", "screencap", "-p"])
        if result.returncode == 0 and result.stdout and len(result.stdout) > 100:
            return result.stdout

        # Fallback: write to device temp file, then pull
        logger.debug("exec-out screencap returned empty, falling back to pull")
        remote_path = "/sdcard/_apptest_screenshot.png"
        self._run_check(["shell", "screencap", "-p", remote_path])
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            local_path = tmp.name
        try:
            self._run_check(["pull", remote_path, local_path])
            png = Path(local_path).read_bytes()
        finally:
            Path(local_path).unlink(missing_ok=True)
            self._run(["shell", "rm", "-f", remote_path])
        if not png:
            raise RuntimeError("screencap returned empty image")
        return png

    def screenshot(self, path: str | Path) -> bytes:
        """Capture a screenshot, save to path, and return PNG bytes."""
        png = self.screenshot_bytes()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(png)
        return png

    # ---- Input ----

    def tap(self, x: int, y: int) -> None:
        """Tap at (x, y) coordinates."""
        self._run_check(["shell", "input", "tap", str(x), str(y)])

    def type_text(self, text: str) -> None:
        """Type text via ADB input. Spaces are escaped."""
        escaped = text.replace(" ", "%s")
        self._run_check(["shell", "input", "text", escaped])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """Swipe from (x1,y1) to (x2,y2)."""
        self._run_check([
            "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration_ms),
        ])

    def swipe_up(self) -> None:
        """Swipe up from center-bottom to center-top."""
        w, h = self.get_screen_size()
        cx = w // 2
        self.swipe(cx, h * 3 // 4, cx, h // 4)

    def swipe_down(self) -> None:
        """Swipe down from center-top to center-bottom."""
        w, h = self.get_screen_size()
        cx = w // 2
        self.swipe(cx, h // 4, cx, h * 3 // 4)

    def press_back(self) -> None:
        """Press the Android back button."""
        self._run_check(["shell", "input", "keyevent", "KEYCODE_BACK"])

    def press_home(self) -> None:
        """Press the Android home button."""
        self._run_check(["shell", "input", "keyevent", "KEYCODE_HOME"])

    def press_enter(self) -> None:
        """Press the enter key."""
        self._run_check(["shell", "input", "keyevent", "KEYCODE_ENTER"])

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        """Long-press at (x, y) via swipe-in-place with long duration."""
        self._run_check([
            "shell", "input", "swipe",
            str(x), str(y), str(x), str(y), str(duration_ms),
        ])

    def swipe_left(self) -> None:
        """Swipe left from right-center to left-center."""
        w, h = self.get_screen_size()
        self.swipe(w * 3 // 4, h // 2, w // 4, h // 2)

    def swipe_right(self) -> None:
        """Swipe right from left-center to right-center."""
        w, h = self.get_screen_size()
        self.swipe(w // 4, h // 2, w * 3 // 4, h // 2)

    # ---- App management ----

    def install(self, apk_path: str) -> None:
        """Install an APK (replace if exists, allow version downgrade)."""
        self._run_check(["install", "-r", "-d", apk_path], timeout=120)

    def uninstall(self, package: str) -> None:
        """Uninstall an app. No error if not installed."""
        self._run(["uninstall", package], timeout=30)

    def launch_app(self, package: str) -> None:
        """Launch an app by package name using monkey."""
        self._run_check([
            "shell", "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1",
        ])

    def force_stop(self, package: str) -> None:
        """Force-stop an app."""
        self._run_check(["shell", "am", "force-stop", package])

    def clear_app_data(self, package: str) -> None:
        """Clear all app data."""
        self._run_check(["shell", "pm", "clear", package])

    def set_locale(self, locale: str) -> None:
        """Change device locale (e.g. 'el', 'en-US')."""
        self._run_check([
            "shell", "settings", "put", "system", "system_locales", locale,
        ])

    def set_setting(self, key: str, value: str) -> None:
        """Change a system setting via ``adb shell settings put system``."""
        self._run_check(["shell", "settings", "put", "system", key, value])

    # ---- Device info ----

    def get_screen_size(self) -> tuple[int, int]:
        """Return (width, height) of the screen in pixels."""
        result = self._run_check(["shell", "wm", "size"])
        # Output: "Physical size: 1080x2400"
        text = result.stdout.decode().strip()
        for line in text.splitlines():
            if ":" in line:
                size_str = line.split(":")[-1].strip()
                w, h = size_str.split("x")
                return int(w), int(h)
        raise RuntimeError(f"Could not parse screen size from: {text}")

    def is_keyboard_shown(self) -> bool:
        """Check if the soft keyboard is currently fully visible.

        Uses Gboard's internal ``isShown`` flag when available, which
        accurately distinguishes a fully-visible keyboard from a collapsed
        floating toolbar.  Falls back to ``mInputShown`` for non-Gboard IMEs.
        """
        result = self._run_check(["shell", "dumpsys", "input_method"])
        text = result.stdout.decode(errors="replace")
        # Gboard reports "isShown = true/false" for actual keyboard visibility
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("isShown ="):
                return "true" in stripped
        # Fallback for non-Gboard keyboards
        return "mInputShown=true" in text

    def ensure_keyboard_visible(self) -> None:
        """Force the on-screen keyboard to show on emulators.

        Emulators with a hardware keyboard hide the on-screen keyboard by
        default, showing only a floating IME toolbar.  This sets the system
        flag that forces the software keyboard to appear alongside the
        hardware keyboard.
        """
        self._run_check([
            "shell", "settings", "put", "secure",
            "show_ime_with_hard_keyboard", "1",
        ])

    def get_foreground_package(self) -> str:
        """Return the package name of the app currently in the foreground."""
        result = self._run_check([
            "shell", "dumpsys", "activity", "recents",
        ])
        # Look for "realActivity={pkg/activity}" in the top entry
        text = result.stdout.decode(errors="replace")
        for line in text.splitlines():
            if "realActivity=" in line:
                # Format: "realActivity={org.wikipedia.alpha/.main.MainActivity}"
                part = line.split("realActivity=")[-1].strip()
                part = part.strip("{}")
                return part.split("/")[0]
        return ""
