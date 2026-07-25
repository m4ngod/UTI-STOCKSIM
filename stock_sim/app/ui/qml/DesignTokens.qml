import QtQuick 2.15

QtObject {
    readonly property color background: "#090d12"
    readonly property color rail: "#0d131a"
    readonly property color surface: "#121a23"
    readonly property color surfaceRaised: "#17212c"
    readonly property color border: "#273544"
    readonly property color textPrimary: "#f2f5f7"
    readonly property color textMuted: "#9aa8b6"
    readonly property color textQuiet: "#6f7d8a"
    readonly property color accent: "#71d5b5"
    readonly property color focus: "#9fbfff"

    readonly property int spaceXs: 6
    readonly property int spaceSm: 10
    readonly property int spaceMd: 16
    readonly property int spaceLg: 24
    readonly property int spaceXl: 36

    readonly property int radiusSm: 6
    readonly property int radiusMd: 10
    readonly property int bodySize: 13
    readonly property int labelSize: 11
    readonly property int titleSize: 26
    readonly property int focusWidth: 2
    readonly property int elevationRaised: 8
    readonly property int durationBrief: 100
    readonly property int durationReducedMotion: 0
    readonly property bool reducedMotion: true
    readonly property int durationForMotion: reducedMotion
        ? durationReducedMotion
        : durationBrief
}
