import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Popup {
    id: popup
    objectName: "researchHealthPopup"
    required property var tokens
    required property var adapter
    property var returnFocusItem: null
    parent: Overlay.overlay
    width: Math.max(0, Math.min(parent.width, 920))
    height: Math.max(0, Math.min(parent.height, 680 * tokens.textScale))
    x: (parent.width - width) / 2
    y: (parent.height - height) / 2
    padding: tokens.spaceMd
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    enter: Transition {}
    exit: Transition {}
    Accessible.name: "系统状态详情，只读"
    onOpened: closeButton.forceActiveFocus()
    onClosed: {
        if (returnFocusItem !== null && returnFocusItem.visible && returnFocusItem.enabled)
            returnFocusItem.forceActiveFocus()
    }
    background: Rectangle {
        color: tokens.surface
        border.color: tokens.border
    }
    contentItem: ColumnLayout {
        spacing: tokens.spaceSm
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "系统状态"
                Layout.fillWidth: true
                color: tokens.textPrimary
                font.pixelSize: tokens.titleSize
                Accessible.role: Accessible.Heading
            }
            DiagnosticCommandButton {
                id: closeButton
                objectName: "researchHealthCloseButton"
                tokens: popup.tokens
                text: "关闭"
                Accessible.name: "关闭系统状态详情"
                accessibleDescription: "关闭详情并返回顶部系统状态按钮，不停止后台运行。"
                onInvoked: popup.close()
                KeyNavigation.tab: facts
                KeyNavigation.backtab: facts
            }
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            TextArea {
                id: facts
                objectName: "researchHealthFacts"
                readOnly: true
                Accessible.readOnly: true
                selectByMouse: true
                selectByKeyboard: true
                wrapMode: TextEdit.WrapAnywhere
                font.pixelSize: tokens.bodySize
                color: tokens.textPrimary
                Accessible.name: "六类系统事实与当前影响"
                KeyNavigation.tab: closeButton
                KeyNavigation.backtab: closeButton
                readonly property string observedText: adapter === null ? "未知：尚无权威系统状态观察。" : [
                    adapter.statusText,
                    "当前影响\n" + adapter.componentImpactText,
                    "关联工作\n" + adapter.diagnosticObservationText
                        + (adapter.phase === "loading" ? "" : "\n" + adapter.diagnosticContextExplanation),
                    adapter.observationDetailsText + "\n功能接口 · " + adapter.featureRegistryText,
                    "精确关联与版本\n" + (adapter.phase === "loading"
                        ? "等待权威观察返回。" : adapter.diagnosticIdentityText),
                    "只读观察；打开或关闭本窗口不会暂停实验。"
                ].join("\n\n")
                function presentObservation() {
                    if (text === observedText)
                        return
                    const previousPosition = cursorPosition
                    const wasAtEnd = text.length > 0 && previousPosition === text.length
                    text = observedText
                    cursorPosition = wasAtEnd ? text.length : Math.min(previousPosition, text.length)
                }
                onObservedTextChanged: presentObservation()
                Component.onCompleted: presentObservation()
                background: Rectangle {
                    color: tokens.surface
                    border.width: facts.activeFocus ? tokens.focusWidth : 0
                    border.color: tokens.focus
                }
            }
        }
    }
}
