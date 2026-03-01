"""Device agent: locale, settings, device configuration."""

from .base import SetupAgent


class DeviceAgent(SetupAgent):
    """Handles device-level configuration before tests run."""

    name = "device"
    actions = {
        "set_locale": "Change device language/locale (params: locale, e.g. 'el', 'en-US')",
        "set_setting": "Change a system setting (params: key, value)",
    }

    def execute(self, action: str, device, params: dict) -> str:
        if action == "set_locale":
            locale = params.get("locale", "")
            if locale:
                device.set_locale(locale)
                return f"locale set to {locale}"
            return "no locale provided"

        elif action == "set_setting":
            key = params.get("key", "")
            value = params.get("value", "")
            device.set_setting(key, value)
            return f"set {key}={value}"

        return f"unknown action: {action}"
