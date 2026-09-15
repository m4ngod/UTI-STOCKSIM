import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: page
    required property var adapter
    required property var tokens
    readonly property real listMinimumWidth: Math.max(300,
        metrics.advanceWidth("组合名称与精确版本 · 历史资源") + tokens.spaceMd * 2)
    readonly property real detailMinimumWidth: Math.max(640,
        metrics.advanceWidth("精确版本、固定输入、状态与限制原因始终可以读取") + tokens.spaceMd * 2)
    readonly property bool compact: width < listMinimumWidth + detailMinimumWidth + tokens.spaceMd
    FontMetrics { id: metrics; font.pixelSize: tokens.bodySize }

    function reflowList() {
        if (!assetList || !listDrawer)
            return
        // Move the existing view only after capturing its focus. A parent binding
        // can otherwise hide it in a closed drawer before focus can be restored.
        const restoreList = assetList.activeFocus
        assetList.parent = compact ? listDrawer.contentItem : listContainer
        if (compact && restoreList) {
            listDrawer.open()
        } else if (!compact) {
            listDrawer.close()
            if (restoreList) {
                Qt.callLater(function() {
                    if (page.visible && !page.compact)
                        assetList.forceActiveFocus()
                })
            }
        }
    }
    onCompactChanged: reflowList()
    Component.onCompleted: reflowList()
    onVisibleChanged: {
        if (!visible)
            listDrawer.close()
    }

    function choose(index) {
        if (index < 0 || index >= adapter.assets.length)
            return
        adapter.selectKey(adapter.assets[index].key)
        if (compact)
            listDrawer.close()
        readButton.forceActiveFocus()
    }

    Drawer {
        id: listDrawer
        objectName: "researchAssetListDrawer"
        parent: Overlay.overlay
        width: Math.min(parent.width, Math.max(page.listMinimumWidth, parent.width * 0.65))
        height: parent.height
        edge: Qt.LeftEdge
        modal: true
        focus: true
        enter: Transition {}
        exit: Transition {}
        Accessible.name: "组合库对象列表"
        onOpened: assetList.forceActiveFocus()
        onClosed: {
            if (listButton.visible)
                listButton.forceActiveFocus()
        }
        background: Rectangle { color: tokens.surface }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: tokens.spaceSm
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: "组合库"
                color: tokens.textPrimary
                font.pixelSize: tokens.titleSize
                font.bold: true
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            DiagnosticCommandButton {
                id: listButton
                objectName: "researchAssetListButton"
                visible: page.compact
                tokens: page.tokens
                text: "对象列表"
                Accessible.name: "打开组合库对象列表"
                accessibleDescription: "打开精确资源列表，关闭后返回本按钮。不会启动实验。"
                onInvoked: listDrawer.open()
            }
            DiagnosticCommandButton {
                objectName: "researchAssetRefreshButton"
                tokens: page.tokens
                text: "刷新"
                Accessible.name: "刷新组合库精确资源目录"
                accessibleDescription: "重新读取目录；不修改资产或替换已选择的精确版本。"
                enabled: adapter.available && !adapter.busy
                onInvoked: adapter.refresh()
            }
        }
        Text {
            Layout.fillWidth: true
            text: adapter.statusText
            color: tokens.textMuted
            font.pixelSize: tokens.bodySize
            wrapMode: Text.WrapAnywhere
            Accessible.role: Accessible.StatusBar
            Accessible.name: text
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: tokens.spaceMd
            Item {
                id: listContainer
                visible: assetList.parent === listContainer
                Layout.preferredWidth: page.listMinimumWidth
                Layout.fillHeight: true
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                DiagnosticCommandButton {
                    id: readButton
                    objectName: "researchAssetReadButton"
                    tokens: page.tokens
                    text: "读取精确版本"
                    Accessible.name: "读取所选精确策略版本"
                    accessibleDescription: "只读核验所选版本、固定输入和依赖，不创建组合或执行实验。"
                    enabled: adapter.canQuery
                    onInvoked: adapter.querySelected()
                }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: availableWidth
                    TextArea {
                        id: details
                        objectName: "researchAssetDetails"
                        text: adapter.resultText + "\n\n" + adapter.limitationText
                        readOnly: true
                        Accessible.readOnly: true
                        selectByMouse: true
                        selectByKeyboard: true
                        wrapMode: TextEdit.WrapAnywhere
                        font.pixelSize: tokens.bodySize
                        color: tokens.textPrimary
                        Accessible.name: "精确策略版本、身份与能力限制"
                        background: Rectangle {
                            color: tokens.background
                            border.width: details.activeFocus ? tokens.focusWidth : 0
                            border.color: tokens.focus
                        }
                    }
                }
            }
        }
    }
    ListView {
        id: assetList
        objectName: "researchAssetList"
        parent: listContainer
        anchors.fill: parent
        anchors.margins: page.compact ? tokens.spaceMd : 0
        model: adapter.assets
        clip: true
        currentIndex: -1
        activeFocusOnTab: true
        Accessible.role: Accessible.List
        Accessible.name: "组合库精确资源，共 " + count + " 项"
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}
        Keys.onReturnPressed: page.choose(currentIndex)
        Keys.onEnterPressed: page.choose(currentIndex)
        delegate: ItemDelegate {
            required property var modelData
            required property int index
            width: assetList.width
            text: modelData.label
            font.pixelSize: tokens.bodySize
            implicitHeight: Math.max(48, contentItem.implicitHeight + tokens.spaceMd * 2)
            highlighted: index === adapter.selectedIndex
            Accessible.name: text + "，第 " + (index + 1) + " 项，共 " + assetList.count + " 项"
            // ListItem does not inherit Accessible.focusable from its keyboard focus.
            Accessible.focusable: enabled
            onClicked: page.choose(index)
            contentItem: Text {
                text: parent.text
                font: parent.font
                color: tokens.textPrimary
                wrapMode: Text.WrapAnywhere
            }
            background: Rectangle {
                color: parent.highlighted ? tokens.surfaceRaised : "transparent"
                border.color: tokens.focus
                border.width: parent.activeFocus || (assetList.activeFocus && assetList.currentIndex === index)
                    ? tokens.focusWidth : 0
            }
        }
    }
}
