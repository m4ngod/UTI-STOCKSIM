import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Popup {
    id: inspector
    objectName: "strategyExactAssetInspector"
    required property var adapter
    required property var tokens
    property var returnFocusItem: null
    parent: Overlay.overlay
    width: Math.max(0, Math.min(parent.width - 32, 1000))
    height: Math.max(0, Math.min(parent.height - 32, 620 * tokens.textScale))
    x: (parent.width - width) / 2
    y: (parent.height - height) / 2
    padding: tokens.spaceMd
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    enter: Transition {}
    exit: Transition {}
    Accessible.name: "精确资产检查"
    onOpened: {
        adapter.setActive(true)
        refreshButton.forceActiveFocus()
    }
    onClosed: {
        adapter.setActive(false)
        if (returnFocusItem !== null)
            returnFocusItem.forceActiveFocus()
    }
    background: Rectangle {
        color: tokens.surface
        border.color: tokens.border
        radius: tokens.radiusMd
    }
    function reveal(item) {
        var point = item.mapToItem(body.contentItem, 0, 0)
        if (point.y < body.contentY || item.height > body.height)
            body.contentY = Math.max(0, point.y)
        else if (point.y + item.height > body.contentY + body.height)
            body.contentY = Math.min(body.contentHeight - body.height, point.y + item.height - body.height)
    }
    function revealCursor(item) {
        if (!item.activeFocus)
            return
        var rect = item.cursorRectangle
        var point = item.mapToItem(body.contentItem, rect.x, rect.y)
        if (point.y < body.contentY)
            body.contentY = Math.max(0, point.y)
        else if (point.y + rect.height > body.contentY + body.height)
            body.contentY = Math.max(0, Math.min(body.contentHeight - body.height, point.y + rect.height - body.height))
    }
    contentItem: ColumnLayout {
        spacing: tokens.spaceMd
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: "精确资产"
                color: tokens.textPrimary
                font.pixelSize: tokens.titleSize
                font.bold: true
                wrapMode: Text.Wrap
                Accessible.role: Accessible.Heading
            }
            DiagnosticCommandButton {
                objectName: "strategyExactAssetCloseButton"
                tokens: inspector.tokens
                text: "关闭"
                Accessible.name: "关闭精确资产检查"
                accessibleDescription: "关闭检查并返回打开按钮，不取消后台读取。"
                onInvoked: inspector.close()
            }
        }
        Flickable {
            id: body
            objectName: "strategyExactAssetBody"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: width
            contentHeight: fields.implicitHeight
            ScrollBar.vertical: ScrollBar {}
            ColumnLayout {
                id: fields
                width: body.width
                spacing: tokens.spaceMd
                Text {
                    objectName: "strategyExactAssetStatus"
                    Layout.fillWidth: true
                    text: adapter.statusText
                    color: tokens.accent
                    font.pixelSize: tokens.bodySize
                    wrapMode: Text.Wrap
                    Accessible.role: Accessible.StatusBar
                    Accessible.name: text
                }
                Text {
                    Layout.fillWidth: true
                    text: adapter.limitationText
                    color: tokens.textMuted
                    font.pixelSize: tokens.bodySize
                    wrapMode: Text.Wrap
                    Accessible.role: Accessible.StaticText
                    Accessible.name: text
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: width < 740 * tokens.textScale ? 1 : 3
                    rowSpacing: tokens.spaceSm
                    columnSpacing: tokens.spaceSm
                    DiagnosticCommandButton {
                        id: refreshButton
                        objectName: "strategyExactAssetRefreshButton"
                        Layout.fillWidth: true
                        tokens: inspector.tokens
                        text: "重新读取目录"
                        enabled: adapter.available && !adapter.busy
                        accessibleDescription: "重新读取当前目录；不改变所选精确版本。"
                        onInvoked: adapter.refresh()
                        onFocusEntered: function(item) { inspector.reveal(item) }
                    }
                    ComboBox {
                        id: picker
                        objectName: "strategyExactAssetPicker"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredHeight: tokens.controlHeight
                        model: adapter.assets
                        textRole: "label"
                        valueRole: "key"
                        currentIndex: adapter.selectedIndex
                        displayText: currentIndex < 0 ? "选择精确版本" : currentText
                        enabled: adapter.available && !adapter.busy && count > 0
                        font.pixelSize: tokens.bodySize
                        palette.text: tokens.textPrimary
                        palette.buttonText: tokens.textPrimary
                        palette.base: tokens.surfaceRaised
                        palette.window: tokens.surfaceRaised
                        activeFocusOnTab: true
                        Accessible.name: "选择精确策略版本"
                        Accessible.description: "名称仅用于显示，读取固定身份、版本和内容哈希。"
                        background: Rectangle {
                            color: tokens.surfaceRaised
                            border.color: picker.activeFocus ? tokens.focus : tokens.border
                            border.width: picker.activeFocus ? tokens.focusWidth : 1
                            radius: tokens.radiusSm
                        }
                        onActivated: adapter.selectKey(currentValue)
                        onActiveFocusChanged: if (activeFocus) inspector.reveal(picker)
                    }
                    DiagnosticCommandButton {
                        objectName: "strategyExactAssetQueryButton"
                        Layout.fillWidth: true
                        tokens: inspector.tokens
                        text: "读取固定内容"
                        enabled: adapter.canQuery
                        accessibleDescription: "按已选择的身份、版本、内容哈希和源 revision 读取，不使用最新版本替代。"
                        onInvoked: adapter.querySelected()
                        onFocusEntered: function(item) { inspector.reveal(item) }
                    }
                }
                TextArea {
                    id: resultText
                    objectName: "strategyExactAssetResult"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: adapter.resultText
                    color: tokens.textPrimary
                    font.pixelSize: tokens.bodySize
                    wrapMode: TextEdit.WrapAnywhere
                    readOnly: true
                    selectByMouse: true
                    activeFocusOnTab: true
                    background: null
                    Accessible.role: Accessible.EditableText
                    Accessible.readOnly: true
                    Accessible.name: "精确资产读取结果"
                    Accessible.description: "只读结果；可用键盘阅读和复制固定身份、哈希及限制原因。"
                    onActiveFocusChanged: if (activeFocus) inspector.revealCursor(resultText)
                    onCursorRectangleChanged: inspector.revealCursor(resultText)
                }
            }
        }
    }
}
