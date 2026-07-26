import QtQuick 2.15

Rectangle {
    id: control

    property string text: ""
    property color enabledTextColor: "white"
    property color disabledTextColor: "gray"
    property color standardBorderColor: "gray"
    property color focusColor: "white"
    property real focusBorderWidth: 2
    property real labelSize: 12
    property string accessibleDescription: (
        "Controls the diagnostic task lifecycle only; never submits an order."
    )
    readonly property bool focusVisible: activeFocus
    signal invoked()
    signal focusEntered(var item)

    activeFocusOnTab: enabled
    implicitWidth: Math.max(144, label.implicitWidth + 24)
    implicitHeight: Math.max(38, label.implicitHeight + 12)
    opacity: enabled ? 1.0 : 0.55
    scale: 1.0
    border.color: activeFocus ? focusColor : standardBorderColor
    border.width: activeFocus ? focusBorderWidth : 1
    Accessible.name: text
    Accessible.description: accessibleDescription
    Accessible.role: Accessible.Button
    Accessible.focusable: enabled
    Accessible.focused: activeFocus
    Accessible.onPressAction: {
        if (control.enabled)
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
            control.invoked()
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
    }

    MouseArea {
        id: pointer
        anchors.fill: parent
        enabled: control.enabled
        onClicked: control.invoked()
    }
}
