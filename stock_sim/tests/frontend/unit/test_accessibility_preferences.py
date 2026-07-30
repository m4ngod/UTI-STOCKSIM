from collections.abc import Mapping

from app.ui.accessibility import (
    AccessibilityPreferences,
    AccessibilitySettingsQtAdapter,
    detect_accessibility_preferences,
)


def test_explicit_accessibility_environment_overrides_are_parsed_and_clamped():
    environment: Mapping[str, str] = {
        "STOCKSIM_TEXT_SCALE_PERCENT": "275",
        "STOCKSIM_REDUCED_MOTION": "yes",
        "STOCKSIM_HIGH_CONTRAST": "1",
    }

    preferences = detect_accessibility_preferences(
        environment=environment,
        platform_name="linux",
    )

    assert preferences == AccessibilityPreferences(
        text_scale=2.0,
        reduced_motion=True,
        high_contrast=True,
    )


def test_invalid_overrides_fall_back_to_safe_cross_platform_defaults():
    preferences = detect_accessibility_preferences(
        environment={
            "STOCKSIM_TEXT_SCALE_PERCENT": "not-a-number",
            "STOCKSIM_REDUCED_MOTION": "sometimes",
            "STOCKSIM_HIGH_CONTRAST": "perhaps",
        },
        platform_name="linux",
    )

    assert preferences == AccessibilityPreferences(
        text_scale=1.0,
        reduced_motion=False,
        high_contrast=False,
    )


def test_non_finite_text_scale_overrides_use_the_safe_fallback():
    for value in ("NaN", "Inf", "-Inf"):
        preferences = detect_accessibility_preferences(
            environment={"STOCKSIM_TEXT_SCALE_PERCENT": value},
            platform_name="linux",
        )

        assert preferences.text_scale == 1.0


def test_windows_preferences_are_read_without_becoming_runtime_dependencies():
    preferences = detect_accessibility_preferences(
        environment={},
        platform_name="win32",
        windows_text_scale_reader=lambda: 175,
        windows_flags_reader=lambda: (True, True),
    )

    assert preferences == AccessibilityPreferences(
        text_scale=1.75,
        reduced_motion=True,
        high_contrast=True,
    )


def test_qt_adapter_exposes_immutable_preferences_to_qml():
    adapter = AccessibilitySettingsQtAdapter(
        AccessibilityPreferences(
            text_scale=2.0,
            reduced_motion=True,
            high_contrast=True,
        )
    )

    assert adapter.textScale == 2.0
    assert adapter.reducedMotion is True
    assert adapter.highContrast is True
