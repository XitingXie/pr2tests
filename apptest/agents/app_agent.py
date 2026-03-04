"""App agent: install, uninstall, clear data."""

from .base import SetupAgent


class AppAgent(SetupAgent):
    """Handles app lifecycle operations on the device."""

    name = "app"
    actions = {
        "clear_data": "Clear all app data (fresh state, triggers onboarding)",
        "install": "Install APK on device (params: apk_path)",
        "uninstall": "Uninstall the app from device",
    }

    def __init__(self, apk_path: str | None = None):
        self.apk_path = apk_path

    def execute(self, action: str, device, params: dict) -> str:
        pkg = params.get("app_package", "")

        if action == "clear_data":
            device.clear_app_data(pkg)
            return f"cleared data for {pkg}"

        elif action == "install":
            apk = params.get("apk_path", self.apk_path)
            if apk:
                # Uninstall first to avoid INSTALL_FAILED_VERSION_DOWNGRADE
                # when the PR branch has a lower version code than what's on device.
                if pkg:
                    try:
                        device.uninstall(pkg)
                    except Exception:
                        pass  # OK if not installed
                device.install(apk)
                return f"installed {apk}"
            return "no APK path provided"

        elif action == "uninstall":
            device.uninstall(pkg)
            return f"uninstalled {pkg}"

        return f"unknown action: {action}"
