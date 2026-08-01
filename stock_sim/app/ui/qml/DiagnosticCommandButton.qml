import QtQuick 2.15

Rectangle {
    id: control

    property var tokens: null
    property string text: ""
    property string accessibleName: text
    property color enabledTextColor: tokens === null
        ? "white" : tokens.textPrimary
    property color disabledTextColor: tokens === null
        ? "gray" : tokens.textQuiet
    property color standardBorderColor: tokens === null
        ? "gray" : tokens.border
    property color focusColor: tokens === null
        ? "white" : tokens.focus
    property real focusBorderWidth: tokens === null
        ? 2 : tokens.focusWidth
    property real labelSize: tokens === null
        ? 12 : tokens.labelSize
    property string accessibleDescription: (
        "Controls the diagnostic task lifecycle only; never submits an order."
    )
    readonly property bool focusVisible: activeFocus
    signal invoked()
    signal focusEntered(var item)

    activeFocusOnTab: enabled
    implicitWidth: Math.max(144, label.implicitWidth + 24)
    implicitHeight: Math.max(
        tokens === null ? 38 : tokens.controlHeight,
        label.implicitHeight + (tokens === null ? 12 : tokens.spaceSm)
    )
    radius: tokens === null ? 0 : tokens.radiusSm
    color: tokens === null ? "transparent" : tokens.surfaceRaised
    opacity: enabled ? 1.0 : 0.55
    scale: 1.0
    border.color: activeFocus ? focusColor : standardBorderColor
    border.width: activeFocus ? focusBorderWidth : 1
    Accessible.name: accessibleName
    Accessible.description: accessibleDescription
    Accessible.role: Accessible.Button
    Accessible.focusable: enabled
    Accessible.focused: activeFocus
    Accessible.onPressAction: {
        control.activate()
    }

    function activate() {
        if (!control.enabled)
            return
        control.invoked()
    }

    onActiveFocusChanged: {
        if (activeFocus)
            focusEntered(control)
    }

    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Return
                || event.key === Qt.Key_Enter
                || event.key === Qt.Key_Space) {
            control.activate()
            event.accepted = true
        }
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: control.text
        color: control.enabled
            ? control.enabledTextColor
            : control.disabledTextColor
        font.pixelSize: control.labelSize
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
    }

    MouseArea {
        id: pointer
        anchors.fill: parent
        enabled: control.enabled
        cursorShape: Qt.PointingHandCursor
        onClicked: control.activate()
    }
}
