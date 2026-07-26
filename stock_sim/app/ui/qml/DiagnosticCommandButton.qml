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
    property int pressDuration: 120
    signal invoked()

    activeFocusOnTab: enabled
    opacity: enabled ? 1.0 : 0.55
    scale: pointer.pressed ? 0.97 : 1.0
    border.color: activeFocus ? focusColor : standardBorderColor
    border.width: activeFocus ? focusBorderWidth : 1
    Accessible.name: text
    Accessible.role: Accessible.Button

    Behavior on scale {
        NumberAnimation {
            duration: control.pressDuration
            easing.type: Easing.OutCubic
        }
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
