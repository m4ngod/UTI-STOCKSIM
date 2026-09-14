import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: browser
    required property var tokens
    required property string title
    required property var entries
    required property string statusText
    required property string limitationText
    property var selectedEntry: null
    readonly property real listMinimumWidth: Math.max(300,
        metrics.advanceWidth("对象名称、精确版本与兼容状态") + tokens.spaceMd * 2)
    readonly property real detailMinimumWidth: Math.max(640,
        metrics.advanceWidth("精确身份、状态与限制原因始终可以读取") + tokens.spaceMd * 2)
    readonly property real evidenceMinimumWidth: Math.max(480,
        metrics.advanceWidth("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef") + tokens.spaceMd * 2)
    readonly property bool compact: width < listMinimumWidth + detailMinimumWidth + tokens.spaceMd
    readonly property string selectedEvidence: selectedEntry === null ? "" : (selectedEntry.evidence || "")
    readonly property bool wide: !compact && selectedEvidence.length > 0
        && width >= listMinimumWidth + detailMinimumWidth + evidenceMinimumWidth + tokens.spaceMd * 2
    readonly property bool selectionInCatalog: selectedEntry !== null && entries.some(
        function(entry) { return entry.key === selectedEntry.key })
    FontMetrics { id: metrics; font.pixelSize: tokens.bodySize }

    function choose(index) {
        if (index < 0 || index >= entries.length)
            return
        selectedEntry = entries[index]
        if (compact)
            listDrawer.close()
        details.forceActiveFocus()
    }
    function reflowList() {
        if (!catalog || !listDrawer)
            return
        const restoreList = catalog.activeFocus
        catalog.parent = compact ? listDrawer.contentItem : listContainer
        if (compact && restoreList) {
            listDrawer.open()
        } else if (!compact) {
            listDrawer.close()
            if (restoreList) {
                Qt.callLater(function() {
                    if (browser.visible && !browser.compact)
                        catalog.forceActiveFocus()
                })
            }
        }
    }
    function reflowEvidence() {
        if (!evidenceContainer || !evidence)
            return
        if (!wide && evidence.activeFocus)
            details.forceActiveFocus()
        evidenceContainer.visible = wide
    }
    onCompactChanged: reflowList()
    onWideChanged: reflowEvidence()
    Component.onCompleted: { reflowList(); reflowEvidence() }
    onVisibleChanged: { if (!visible) listDrawer.close() }
    onEntriesChanged: {
        if (selectedEntry === null)
            return
        const exact = entries.find(function(entry) { return entry.key === selectedEntry.key })
        if (exact !== undefined)
            selectedEntry = exact
    }

    Drawer {
        id: listDrawer
        objectName: browser.objectName + "Drawer"
        parent: Overlay.overlay
        width: Math.min(parent.width, Math.max(browser.listMinimumWidth, parent.width * 0.65))
        height: parent.height
        modal: true
        focus: true
        edge: Qt.LeftEdge
        enter: Transition {}
        exit: Transition {}
        Accessible.name: browser.title + "对象列表"
        onOpened: catalog.forceActiveFocus()
        onClosed: { if (listButton.visible) listButton.forceActiveFocus() }
        background: Rectangle { color: tokens.surface }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: tokens.spaceSm
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: browser.title
                color: tokens.textPrimary
                font.pixelSize: tokens.titleSize
                font.bold: true
                Accessible.role: Accessible.Heading
            }
            DiagnosticCommandButton {
                id: listButton
                objectName: browser.objectName + "ListButton"
                visible: browser.compact
                tokens: browser.tokens
                text: "对象列表"
                accessibleDescription: "查看精确资源，关闭后返回本按钮。不会启动计算。"
                onInvoked: listDrawer.open()
            }
        }
        Text {
            Layout.fillWidth: true
            text: browser.statusText
            color: tokens.textMuted
            wrapMode: Text.WrapAnywhere
            font.pixelSize: tokens.bodySize
            Accessible.role: Accessible.StatusBar
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: tokens.spaceMd
            Item {
                id: listContainer
                visible: catalog.parent === listContainer
                Layout.preferredWidth: browser.listMinimumWidth
                Layout.fillHeight: true
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                TextArea {
                    id: details
                    objectName: browser.objectName + "Details"
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.WrapAnywhere
                    color: tokens.textPrimary
                    font.pixelSize: tokens.bodySize
                    Accessible.name: browser.title + "精确资源详情和限制"
                    Accessible.readOnly: true
                    text: (browser.selectedEntry === null
                        ? (browser.entries.length ? "从对象列表选择精确资源。" : "当前没有可读取的资源。")
                        : (!browser.selectionInCatalog ? "当前对象不在可用目录中；保留最后读取的精确详情。\n\n" : "")
                            + browser.selectedEntry.details
                            + (!browser.wide && browser.selectedEvidence.length ? "\n\n精确来源\n" + browser.selectedEvidence : ""))
                        + "\n\n" + browser.limitationText
                    background: Rectangle {
                        color: tokens.background
                        border.width: details.activeFocus ? tokens.focusWidth : 0
                        border.color: tokens.focus
                    }
                }
            }
            ScrollView {
                id: evidenceContainer
                visible: false
                Layout.preferredWidth: browser.evidenceMinimumWidth
                Layout.fillHeight: true
                contentWidth: availableWidth
                TextArea {
                    id: evidence
                    objectName: browser.objectName + "Evidence"
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.WrapAnywhere
                    color: tokens.textPrimary
                    font.pixelSize: tokens.bodySize
                    Accessible.name: browser.title + "精确来源与依赖"
                    Accessible.readOnly: true
                    text: "精确来源\n\n" + browser.selectedEvidence
                    background: Rectangle {
                        color: tokens.surface
                        border.width: evidence.activeFocus ? tokens.focusWidth : 0
                        border.color: tokens.focus
                    }
                }
            }
        }
    }
    ListView {
        id: catalog
        objectName: browser.objectName + "List"
        parent: listContainer
        anchors.fill: parent
        anchors.margins: browser.compact ? tokens.spaceMd : 0
        model: browser.entries
        currentIndex: -1
        clip: true
        activeFocusOnTab: true
        boundsBehavior: Flickable.StopAtBounds
        Accessible.role: Accessible.List
        Accessible.name: browser.title + "对象列表，共 " + count + " 项"
        ScrollBar.vertical: ScrollBar {}
        Keys.onPressed: function(event) {
            if (event.key === Qt.Key_Home) {
                currentIndex = count > 0 ? 0 : -1
                if (currentIndex >= 0)
                    positionViewAtIndex(currentIndex, ListView.Beginning)
                event.accepted = true
            }
        }
        Keys.onReturnPressed: browser.choose(currentIndex)
        Keys.onEnterPressed: browser.choose(currentIndex)
        delegate: ItemDelegate {
            required property var modelData
            required property int index
            width: catalog.width
            text: modelData.label
            font.pixelSize: tokens.bodySize
            implicitHeight: Math.max(48, contentItem.implicitHeight + tokens.spaceMd * 2)
            highlighted: browser.selectedEntry !== null && browser.selectedEntry.key === modelData.key
            Accessible.name: text + "，第 " + (index + 1) + " 项，共 " + catalog.count + " 项"
            onClicked: browser.choose(index)
            contentItem: Text {
                text: parent.text
                font: parent.font
                color: tokens.textPrimary
                wrapMode: Text.WrapAnywhere
            }
            background: Rectangle {
                color: parent.highlighted ? tokens.surfaceRaised : "transparent"
                border.color: tokens.focus
                border.width: parent.activeFocus || (catalog.activeFocus && catalog.currentIndex === index)
                    ? tokens.focusWidth : 0
            }
        }
    }
}
