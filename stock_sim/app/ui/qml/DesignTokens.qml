import QtQuick 2.15

QtObject {
    readonly property var settings: (
        typeof accessibilitySettings === "undefined"
            ? null
            : accessibilitySettings
    )
    readonly property real textScale: settings === null
        ? 1.0
        : settings.textScale
    readonly property bool reducedMotion: settings === null
        ? false
        : settings.reducedMotion
    readonly property bool highContrast: settings === null
        ? false
        : settings.highContrast

    readonly property color background: highContrast ? "#000000" : "#090d12"
    readonly property color rail: highContrast ? "#000000" : "#0d131a"
    readonly property color surface: highContrast ? "#080808" : "#121a23"
    readonly property color surfaceRaised: highContrast ? "#121212" : "#17212c"
    readonly property color border: highContrast ? "#ffffff" : "#5b7085"
    readonly property color textPrimary: highContrast ? "#ffffff" : "#f2f5f7"
    readonly property color textMuted: highContrast ? "#f2f2f2" : "#9aa8b6"
    readonly property color textQuiet: highContrast ? "#d6d6d6" : "#788897"
    readonly property color accent: highContrast ? "#7fffd4" : "#71d5b5"
    readonly property color focus: highContrast ? "#ffff00" : "#9fbfff"

    readonly property int spaceXs: 6
    readonly property int spaceSm: 10
    readonly property int spaceMd: 16
    readonly property int spaceLg: 24
    readonly property int spaceXl: 36

    readonly property int radiusSm: 6
    readonly property int radiusMd: 10
    readonly property int bodySize: Math.round(13 * textScale)
    readonly property int labelSize: Math.round(11 * textScale)
    readonly property int titleSize: Math.round(26 * textScale)
    readonly property int controlHeight: Math.round(38 * textScale)
    readonly property int focusWidth: 2
    readonly property int elevationRaised: 8
    readonly property int durationBrief: 100
    readonly property int durationReducedMotion: 0
    readonly property int durationForMotion: reducedMotion
        ? durationReducedMotion
        : durationBrief
}
