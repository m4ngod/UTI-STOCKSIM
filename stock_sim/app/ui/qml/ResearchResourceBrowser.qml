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
    property var parentKeys: []
    property string navigationError: ""
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
    FontMetrics { id: metrics; font.pixelSize: tokens.bodySize }

    function choose(index) {
        if (index < 0 || index >= entries.length)
            return
        parentKeys = []
        navigationError = ""
        selectedEntry = entries[index]
        if (compact)
            listDrawer.close()
        details.forceActiveFocus()
    }
    function openRelated(key, label) {
        if (selectedEntry !== null)
            parentKeys = parentKeys.concat([selectedEntry.key])
        resolveRelated(key, label)
    }
    function resolveRelated(key, label) {
        const exact = entries.find(function(entry) { return entry.key === key })
        selectedEntry = exact === undefined ? null : exact
        navigationError = exact === undefined ? "关联资源不可用：" + label + "。未选择其他对象。" : ""
        detailScroll.contentItem.contentY = 0
        details.forceActiveFocus()
    }
    function returnToParent() {
        if (!parentKeys.length)
            return
        const key = parentKeys[parentKeys.length - 1]
        parentKeys = parentKeys.slice(0, -1)
        resolveRelated(key, "原上级引用")
    }
    function revealControl(control) {
        const top = control.mapToItem(detailContent, 0, 0).y
        const current = detailScroll.contentItem.contentY
        const bottom = top + control.height
        if (top < current)
            detailScroll.contentItem.contentY = top
        else if (bottom > current + detailScroll.availableHeight)
            detailScroll.contentItem.contentY = Math.max(0, bottom - detailScroll.availableHeight)
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
        let relatedHadFocus = false
        for (let index = 0; index < relatedLinks.count; ++index) {
            const link = relatedLinks.itemAt(index)
            relatedHadFocus = relatedHadFocus || (link !== null && link.activeFocus)
        }
        const exact = entries.find(function(entry) { return entry.key === selectedEntry.key })
        // The typed Feature owns last-reliable retention during transient loss.
        // Do not keep a second copy after that authoritative projection clears it.
        selectedEntry = exact === undefined ? null : exact
        if (selectedEntry === null && relatedHadFocus) {
            if (compact)
                listButton.forceActiveFocus()
            else
                catalog.forceActiveFocus()
        }
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
            DiagnosticCommandButton {
                objectName: browser.objectName + "Back"
                visible: browser.parentKeys.length > 0
                tokens: browser.tokens
                text: "返回上级"
                accessibleDescription: "返回下钻前的精确对象；不启动或修改实验。"
                onInvoked: browser.returnToParent()
            }
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
                id: detailScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                contentHeight: detailContent.implicitHeight
                Column {
                    id: detailContent
                    width: detailScroll.availableWidth
                    spacing: tokens.spaceSm
                    TextArea {
                        id: details
                        width: parent.width
                        objectName: browser.objectName + "Details"
                        readOnly: true
                        selectByMouse: true
                        wrapMode: TextEdit.WrapAnywhere
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        Accessible.name: browser.title + "精确资源详情和限制"
                        Accessible.readOnly: true
                        text: (browser.navigationError.length ? browser.navigationError : browser.selectedEntry === null
                            ? (browser.entries.length ? "从对象列表选择精确资源。" : "当前没有可读取的资源。")
                            : browser.selectedEntry.details
                                + (!browser.wide && browser.selectedEvidence.length ? "\n\n精确来源\n" + browser.selectedEvidence : ""))
                            + "\n\n" + browser.limitationText
                        background: Rectangle {
                            color: tokens.background
                            border.width: details.activeFocus ? tokens.focusWidth : 0
                            border.color: tokens.focus
                        }
                    }
                    Repeater {
                        id: relatedLinks
                        model: browser.selectedEntry === null ? [] : (browser.selectedEntry.links || [])
                        Button {
                            id: linkControl
                            required property var modelData
                            required property int index
                            objectName: browser.objectName + "Link" + index
                            width: detailContent.width
                            text: modelData.label
                            font.pixelSize: tokens.bodySize
                            implicitHeight: Math.max(tokens.controlHeight, contentItem.implicitHeight + tokens.spaceMd)
                            activeFocusOnTab: true
                            Accessible.name: text
                            Accessible.description: "读取同一精确来源中的关联对象，可返回上级；不会启动计算。"
                            Keys.onReturnPressed: clicked()
                            Keys.onEnterPressed: clicked()
                            onClicked: browser.openRelated(modelData.key, modelData.label)
                            onActiveFocusChanged: { if (activeFocus) browser.revealControl(linkControl) }
                            onYChanged: { if (activeFocus) browser.revealControl(linkControl) }
                            onHeightChanged: { if (activeFocus) browser.revealControl(linkControl) }
                            contentItem: Text {
                                text: parent.text
                                font: parent.font
                                wrapMode: Text.WrapAnywhere
                                color: tokens.textPrimary
                            }
                            background: Rectangle {
                                color: tokens.surfaceRaised
                                border.color: parent.activeFocus ? tokens.focus : tokens.border
                                border.width: parent.activeFocus ? tokens.focusWidth : 1
                            }
                        }
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
