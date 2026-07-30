import QtQuick 2.15

Rectangle {
    id: control

    property var tokens
    property string text: ""
    property bool selected: false
    property string accessibleName: text
    property string accessibleDescription: (
        "Read-only Strategy Diagnostics research control"
    )
    readonly property bool focusVisible: activeFocus
    signal invoked()
    signal focusEntered(var item)

    activeFocusOnTab: enabled
    implicitWidth: Math.max(88, label.implicitWidth + tokens.spaceLg)
    implicitHeight: Math.max(
        Math.round(32 * tokens.textScale),
        label.implicitHeight + tokens.spaceSm
    )
    radius: tokens.radiusSm
    color: selected ? tokens.surfaceRaised : tokens.surface
    border.color: activeFocus ? tokens.focus : tokens.border
    border.width: activeFocus ? tokens.focusWidth : 1
    Accessible.name: accessibleName
    Accessible.description: accessibleDescription
    Accessible.role: Accessible.Button
    Accessible.focusable: enabled
    Accessible.focused: activeFocus
    Accessible.selectable: true
    Accessible.selected: selected
    Accessible.onPressAction: {
        if (control.enabled)
            control.invoked()
    }

    onActiveFocusChanged: {
        if (activeFocus)
            focusEntered(control)
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: control.text
        color: selected ? tokens.textPrimary : tokens.textMuted
        font.pixelSize: tokens.labelSize
        font.bold: selected
    }

    MouseArea {
        anchors.fill: parent
        enabled: control.enabled
        cursorShape: Qt.PointingHandCursor
        onClicked: control.invoked()
    }

    Keys.onReturnPressed: function(event) {
        if (control.enabled)
            control.invoked()
        event.accepted = true
    }
    Keys.onSpacePressed: function(event) {
        if (control.enabled)
            control.invoked()
        event.accepted = true
    }
}
