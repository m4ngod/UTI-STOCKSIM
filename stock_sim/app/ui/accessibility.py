"""Stable accessibility preferences shared by the Widgets/QML boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import isfinite
import os
import sys

from PySide6.QtCore import QObject, Property


_MIN_TEXT_SCALE = 1.0
_MAX_TEXT_SCALE = 2.0


@dataclass(frozen=True, slots=True)
class AccessibilityPreferences:
    """Immutable accessibility inputs captured before the QML route mounts."""

    text_scale: float = 1.0
    reduced_motion: bool = False
    high_contrast: bool = False

    def __post_init__(self) -> None:
        if not _MIN_TEXT_SCALE <= self.text_scale <= _MAX_TEXT_SCALE:
            raise ValueError("text_scale must be between 1.0 and 2.0")


def _parse_boolean(value: str | None, *, fallback: bool) -> bool:
    if value is None:
        return fallback
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return fallback


def _parse_text_scale(value: str | None, *, fallback: float) -> float:
    if value is None:
        return fallback
    try:
        percentage = float(value)
    except ValueError:
        return fallback
    if not isfinite(percentage):
        return fallback
    return max(_MIN_TEXT_SCALE, min(_MAX_TEXT_SCALE, percentage / 100.0))


def _read_windows_text_scale() -> int:
    import winreg

    path = r"Software\Microsoft\Accessibility"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
        value, _ = winreg.QueryValueEx(key, "TextScaleFactor")
    return int(value)


def _read_windows_accessibility_flags() -> tuple[bool, bool]:
    import ctypes
    from ctypes import wintypes

    spi_get_client_area_animation = 0x1042
    spi_get_high_contrast = 0x0042
    animations_enabled = wintypes.BOOL()

    class HighContrast(ctypes.Structure):
        _fields_ = (
            ("cbSize", wintypes.UINT),
            ("dwFlags", wintypes.DWORD),
            ("lpszDefaultScheme", wintypes.LPWSTR),
        )

    user32 = ctypes.windll.user32
    animations_result = user32.SystemParametersInfoW(
        spi_get_client_area_animation,
        0,
        ctypes.byref(animations_enabled),
        0,
    )
    high_contrast = HighContrast()
    high_contrast.cbSize = ctypes.sizeof(HighContrast)
    contrast_result = user32.SystemParametersInfoW(
        spi_get_high_contrast,
        high_contrast.cbSize,
        ctypes.byref(high_contrast),
        0,
    )
    reduced_motion = bool(animations_result and not animations_enabled.value)
    high_contrast_enabled = bool(
        contrast_result and high_contrast.dwFlags & 0x00000001
    )
    return reduced_motion, high_contrast_enabled


def detect_accessibility_preferences(
    *,
    environment: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    windows_text_scale_reader: Callable[[], int] = _read_windows_text_scale,
    windows_flags_reader: Callable[[], tuple[bool, bool]] = (
        _read_windows_accessibility_flags
    ),
) -> AccessibilityPreferences:
    """Capture OS preferences once, with deterministic test/CI overrides."""

    values = os.environ if environment is None else environment
    platform_value = sys.platform if platform_name is None else platform_name
    text_scale = 1.0
    reduced_motion = False
    high_contrast = False

    if platform_value == "win32":
        try:
            text_scale = max(
                _MIN_TEXT_SCALE,
                min(_MAX_TEXT_SCALE, windows_text_scale_reader() / 100.0),
            )
        except (OSError, TypeError, ValueError):
            text_scale = 1.0
        try:
            reduced_motion, high_contrast = windows_flags_reader()
        except (OSError, TypeError, ValueError):
            reduced_motion = False
            high_contrast = False

    return AccessibilityPreferences(
        text_scale=_parse_text_scale(
            values.get("STOCKSIM_TEXT_SCALE_PERCENT"),
            fallback=text_scale,
        ),
        reduced_motion=_parse_boolean(
            values.get("STOCKSIM_REDUCED_MOTION"),
            fallback=reduced_motion,
        ),
        high_contrast=_parse_boolean(
            values.get("STOCKSIM_HIGH_CONTRAST"),
            fallback=high_contrast,
        ),
    )


class AccessibilitySettingsQtAdapter(QObject):
    """Read-only QObject projection for the QML design-token layer."""

    def __init__(
        self,
        preferences: AccessibilityPreferences,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._preferences = preferences

    @Property(float, constant=True)
    def textScale(self) -> float:  # noqa: N802 - QML convention
        return self._preferences.text_scale

    @Property(bool, constant=True)
    def reducedMotion(self) -> bool:  # noqa: N802 - QML convention
        return self._preferences.reduced_motion

    @Property(bool, constant=True)
    def highContrast(self) -> bool:  # noqa: N802 - QML convention
        return self._preferences.high_contrast


__all__ = [
    "AccessibilityPreferences",
    "AccessibilitySettingsQtAdapter",
    "detect_accessibility_preferences",
]
