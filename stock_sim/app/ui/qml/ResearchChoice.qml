import QtQuick 2.15

Rectangle {
    id: control

    property var tokens
    property string text: ""
    property bool selected: false
    property string accessibleName: text
    signal invoked()

    activeFocusOnTab: true
    implicitWidth: Math.max(88, label.implicitWidth + tokens.spaceLg)
    implicitHeight: 32
    radius: tokens.radiusSm
    color: selected ? tokens.surfaceRaised : tokens.surface
    border.color: activeFocus ? tokens.focus : tokens.border
    border.width: activeFocus ? tokens.focusWidth : 1
    Accessible.name: accessibleName
    Accessible.role: Accessible.Button

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
        cursorShape: Qt.PointingHandCursor
        onClicked: control.invoked()
    }

    Keys.onReturnPressed: control.invoked()
    Keys.onSpacePressed: control.invoked()
}
