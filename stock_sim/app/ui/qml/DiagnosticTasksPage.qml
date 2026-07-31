import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: page
    objectName: "diagnosticTasksPage"

    required property var adapter
    required property var tokens
    readonly property string strategyCatalogText: adapter.strategyCatalogText
    readonly property string recipeCatalogText: adapter.recipeCatalogText
    readonly property string marketScenarioCatalogText: adapter.marketScenarioCatalogText
    readonly property string stateTitle: adapter.stateTitle
    readonly property string blockingReasonsText: adapter.blockingReasonsText
    readonly property string reproductionManifestStatus: adapter.reproductionManifestStatus
    readonly property string taskStatusText: adapter.taskStatusText
    readonly property string taskHandleText: adapter.taskHandleText
    readonly property string createStatusText: adapter.createStatusText
    readonly property string validationStatusText: adapter.validationStatusText
    readonly property string approvalStatusText: adapter.approvalStatusText
    readonly property string campaignHandoffText: adapter.campaignHandoffText
    readonly property string commandStatusText: adapter.commandStatusText
    property var lastFocusedItem: null
    readonly property bool hasMeaningfulFocus: (
        lastFocusedItem !== null
        && lastFocusedItem.activeFocus
        && lastFocusedItem.visible
        && lastFocusedItem.enabled
    )
    readonly property var firstActionControl: firstEnabledControl()

    function firstEnabledControl() {
        var candidates = [
            createButton,
            reviseButton,
            validateButton,
            approveButton,
            startCampaignButton,
            pauseTaskButton,
            resumeTaskButton,
            cancelTaskButton,
            pauseCampaignButton,
            resumeCampaignButton,
            cancelCampaignButton,
            pauseNodeButton,
            resumeNodeButton,
            cancelNodeButton,
            retryNodeButton
        ]
        for (var index = 0; index < candidates.length; ++index) {
            if (candidates[index].visible && candidates[index].enabled)
                return candidates[index]
        }
        return null
    }

    function ensureItemVisible(item) {
        if (item === null || !scroll.visible)
            return
        var point = item.mapToItem(scroll.contentItem, 0, 0)
        var top = point.y - tokens.spaceMd
        var bottom = point.y + item.height + tokens.spaceMd
        if (top < scroll.contentY)
            scroll.contentY = Math.max(0, top)
        else if (bottom > scroll.contentY + scroll.height)
            scroll.contentY = Math.max(
                0,
                Math.min(
                    scroll.contentHeight - scroll.height,
                    bottom - scroll.height
                )
            )
    }

    function rememberFocus(item) {
        lastFocusedItem = item
        ensureItemVisible(item)
    }

    function restoreFocus() {
        var target = lastFocusedItem
        if (target === null || !target.visible || !target.enabled)
            target = firstEnabledControl()
        if (target !== null) {
            target.forceActiveFocus()
            ensureItemVisible(target)
        }
        return target !== null
    }

    function focusFirstAvailable(candidates) {
        for (var index = 0; index < candidates.length; ++index) {
            var candidate = candidates[index]
            if (candidate.enabled && (!page.visible || candidate.visible)) {
                if (!page.visible) {
                    lastFocusedItem = candidate
                    return true
                }
                candidate.forceActiveFocus()
                rememberFocus(candidate)
                return true
            }
        }
        if (!page.visible)
            return false
        return restoreFocus()
    }

    Flickable {
        id: scroll
        objectName: "diagnosticTasksFlickable"
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: content.implicitHeight + tokens.spaceXl * 2

        ColumnLayout {
            id: content
            width: Math.max(0, parent.width - tokens.spaceXl * 2)
            x: tokens.spaceXl
            y: tokens.spaceXl
            spacing: tokens.spaceLg

            RowLayout {
                Layout.fillWidth: true

                ColumnLayout {
                    spacing: tokens.spaceXs

                    Text {
                        text: "DIAGNOSTIC TASKS"
                        color: tokens.accent
                        font.pixelSize: tokens.labelSize
                        font.bold: true
                    }
                    Text {
                        text: "Create a diagnostic plan from authoritative typed inputs."
                        color: tokens.textMuted
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WordWrap
                    }
                }

                Item { Layout.fillWidth: true }

                Text {
                    text: adapter.revisionText
                    color: tokens.textQuiet
                    font.pixelSize: tokens.labelSize
                }
            }

            Rectangle {
                objectName: "diagnosticTasksAccessibleStatus"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(
                    112,
                    tokens.titleSize + tokens.bodySize * 2 + tokens.spaceLg * 2
                )
                radius: tokens.radiusMd
                color: tokens.surface
                border.color: tokens.border
                Accessible.role: Accessible.StatusBar
                Accessible.name: "Diagnostic Tasks " + adapter.presentationState
                Accessible.description: adapter.statusText

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: tokens.spaceLg
                    spacing: tokens.spaceXs

                    Text {
                        text: adapter.stateTitle
                        color: tokens.textPrimary
                        font.pixelSize: tokens.titleSize
                        font.bold: true
                    }
                    Text {
                        Layout.fillWidth: true
                        text: adapter.statusText + " · " + adapter.sourceText
                        color: tokens.textMuted
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }

            Rectangle {
                objectName: "diagnosticTasksAccessibleSummary"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredHeight: Math.max(
                    138,
                    tokens.bodySize * 4 + tokens.spaceLg * 2
                )
                radius: tokens.radiusMd
                color: tokens.surfaceRaised
                border.color: tokens.border
                Accessible.role: Accessible.StatusBar
                Accessible.name: adapter.accessibilityAnnouncementText
                Accessible.description: adapter.accessibilitySummaryText

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: tokens.spaceLg
                    spacing: tokens.spaceXs

                    Text {
                        text: "TASK JOURNEY STATUS"
                        color: tokens.accent
                        font.pixelSize: tokens.labelSize
                        font.bold: true
                    }

                    Text {
                        id: diagnosticTasksAnnouncement
                        objectName: "diagnosticTasksAnnouncement"
                        Layout.fillWidth: true
                        text: adapter.accessibilityAnnouncementText
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WrapAnywhere
                        Accessible.role: Accessible.AlertMessage
                        Accessible.name: text
                    }

                    Text {
                        Layout.fillWidth: true
                        text: adapter.capabilitiesText
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WrapAnywhere
                        Accessible.role: Accessible.StaticText
                        Accessible.name: text
                    }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: tokens.textScale >= 1.75 ? 1 : 2
                columnSpacing: tokens.spaceMd
                rowSpacing: tokens.spaceMd

                Repeater {
                    model: [
                        {
                            heading: "STRATEGIES UNDER TEST",
                            detail: adapter.strategyCatalogText
                        },
                        {
                            heading: "APPROVED SCENARIO RECIPES",
                            detail: adapter.recipeCatalogText
                        },
                        {
                            heading: "MATERIALIZED MARKET SCENARIOS",
                            detail: adapter.marketScenarioCatalogText
                        },
                        {
                            heading: "INPUT AVAILABILITY",
                            detail: adapter.blockingReasonsText
                        },
                        {
                            heading: "REPRODUCTION MANIFEST",
                            detail: adapter.reproductionManifestStatus
                        }
                    ]

                    Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredHeight: Math.max(
                            126,
                            tokens.labelSize * 6 + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border
                        Accessible.role: Accessible.StaticText
                        Accessible.name: modelData.heading + " " + modelData.detail

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: modelData.heading
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.detail
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }
                }
            }

            Rectangle {
                objectName: "diagnosticTaskCreationPanel"
                Layout.fillWidth: true
                Layout.preferredHeight: creationContent.implicitHeight + tokens.spaceLg * 2
                radius: tokens.radiusMd
                color: tokens.surface
                border.color: tokens.border
                Accessible.role: Accessible.Grouping
                Accessible.name: "Durable Diagnostic Task configuration validation and approval"
                Accessible.description: adapter.taskStatusText + ". " + adapter.validationStatusText + ". " + adapter.approvalStatusText

                ColumnLayout {
                    id: creationContent
                    anchors.fill: parent
                    anchors.margins: tokens.spaceLg
                    spacing: tokens.spaceSm

                    Text {
                        text: "DURABLE DIAGNOSTIC TASK"
                        color: tokens.accent
                        font.pixelSize: tokens.labelSize
                        font.bold: true
                    }

                    Text {
                        Layout.fillWidth: true
                        text: adapter.taskStatusText
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WrapAnywhere
                    }

                    Text {
                        Layout.fillWidth: true
                        text: adapter.taskHandleText
                        color: tokens.textMuted
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WrapAnywhere
                    }

                    DiagnosticCommandButton {
                        id: createButton
                        objectName: "createDiagnosticTaskButton"
                        tokens: page.tokens
                        text: "Create Diagnostic Task"
                        enabled: adapter.canCreate
                        Layout.fillWidth: true
                        Layout.preferredHeight: tokens.controlHeight
                        accessibleDescription: "Create one durable task from the authoritative baseline and required strategies"
                        onFocusEntered: page.rememberFocus(item)
                        onClicked: {
                            adapter.createTask()
                            Qt.callLater(function() {
                                page.focusFirstAvailable([
                                    reviseButton,
                                    validateButton,
                                    createButton
                                ])
                            })
                        }
                    }

                    Text {
                        objectName: "diagnosticTaskCreationStatus"
                        Layout.fillWidth: true
                        text: adapter.createStatusText
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WordWrap
                        Accessible.role: Accessible.StatusBar
                        Accessible.name: text
                    }

                    Text {
                        objectName: "diagnosticTaskValidationStatus"
                        Layout.fillWidth: true
                        text: adapter.validationStatusText
                        color: tokens.textPrimary
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WrapAnywhere
                        Accessible.role: Accessible.StatusBar
                        Accessible.name: "Diagnostic Task validation " + text
                    }

                    Text {
                        objectName: "diagnosticTaskApprovalStatus"
                        Layout.fillWidth: true
                        text: adapter.approvalStatusText
                        color: tokens.textPrimary
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WrapAnywhere
                        Accessible.role: Accessible.StatusBar
                        Accessible.name: "Diagnostic Task approval " + text
                    }

                    GridLayout {
                        objectName: "diagnosticTaskConfigurationActionGrid"
                        Layout.fillWidth: true
                        columns: tokens.textScale >= 1.75 ? 1 : 2
                        columnSpacing: tokens.spaceSm
                        rowSpacing: tokens.spaceSm

                        DiagnosticCommandButton {
                            id: reviseButton
                            objectName: "reviseDiagnosticTaskButton"
                            tokens: page.tokens
                            text: "Correct Configuration"
                            enabled: adapter.canRevise
                            Layout.fillWidth: true
                            Layout.preferredHeight: tokens.controlHeight
                            accessibleDescription: "Replace the current task revision with all displayed authoritative typed inputs"
                            onFocusEntered: page.rememberFocus(item)
                            onClicked: {
                                adapter.reviseTask()
                                Qt.callLater(function() {
                                    page.focusFirstAvailable([
                                        validateButton,
                                        approvalActor,
                                        reviseButton
                                    ])
                                })
                            }
                        }

                        DiagnosticCommandButton {
                            id: validateButton
                            objectName: "validateDiagnosticTaskButton"
                            tokens: page.tokens
                            text: "Validate Configuration"
                            enabled: adapter.canValidate
                            Layout.fillWidth: true
                            Layout.preferredHeight: tokens.controlHeight
                            accessibleDescription: "Validate the exact durable task revision"
                            onFocusEntered: page.rememberFocus(item)
                            onClicked: {
                                adapter.validateTask()
                                Qt.callLater(function() {
                                    page.focusFirstAvailable([
                                        approvalActor,
                                        approveButton,
                                        validateButton
                                    ])
                                })
                            }
                        }
                    }

                    TextField {
                        id: approvalActor
                        objectName: "diagnosticTaskApprovalActorInput"
                        Layout.fillWidth: true
                        placeholderText: "Approval actor identity"
                        selectByMouse: true
                        focusPolicy: Qt.StrongFocus
                        font.pixelSize: tokens.labelSize
                        color: tokens.textPrimary
                        placeholderTextColor: tokens.textQuiet
                        selectionColor: tokens.accent
                        selectedTextColor: tokens.background
                        Layout.preferredHeight: tokens.controlHeight
                        Accessible.name: "Approval actor identity"
                        Accessible.description: "Identity recorded on the exact-revision Diagnostic Task approval"
                        Accessible.focusable: true
                        Accessible.focused: activeFocus
                        background: Rectangle {
                            radius: tokens.radiusSm
                            color: tokens.surfaceRaised
                            border.color: approvalActor.activeFocus
                                ? tokens.focus : tokens.border
                            border.width: approvalActor.activeFocus
                                ? tokens.focusWidth : 1
                        }
                        onActiveFocusChanged: {
                            if (activeFocus)
                                page.rememberFocus(approvalActor)
                        }
                    }

                    DiagnosticCommandButton {
                        id: approveButton
                        objectName: "approveDiagnosticTaskButton"
                        tokens: page.tokens
                        text: "Approve Configuration"
                        enabled: adapter.canApprove && approvalActor.text.trim().length > 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: tokens.controlHeight
                        accessibleDescription: "Approve only the exact successfully validated task revision"
                        onFocusEntered: page.rememberFocus(item)
                        onClicked: {
                            adapter.approveTask(approvalActor.text)
                            Qt.callLater(function() {
                                page.focusFirstAvailable([
                                    startCampaignButton,
                                    validateButton,
                                    approveButton
                                ])
                            })
                        }
                    }

                    DiagnosticCommandButton {
                        id: startCampaignButton
                        objectName: "startDiagnosticCampaignButton"
                        tokens: page.tokens
                        text: "Start Formal Diagnostic Campaign"
                        enabled: adapter.canStartCampaign
                        Layout.fillWidth: true
                        Layout.preferredHeight: tokens.controlHeight
                        accessibleDescription: "Start the exact approved task revision and hand its real Campaign and Run identities to Run Monitoring"
                        onFocusEntered: page.rememberFocus(item)
                        onClicked: adapter.startCampaign()
                    }

                    Text {
                        objectName: "diagnosticCampaignHandoffStatus"
                        Layout.fillWidth: true
                        text: adapter.campaignHandoffText
                        color: tokens.textMuted
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WrapAnywhere
                        Accessible.role: Accessible.StatusBar
                        Accessible.name: text
                    }

                    Text {
                        objectName: "diagnosticTaskCommandStatus"
                        Layout.fillWidth: true
                        text: adapter.commandStatusText
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WordWrap
                        Accessible.role: Accessible.StatusBar
                        Accessible.name: text
                    }
                }
            }

            Rectangle {
                objectName: "diagnosticLifecyclePanel"
                Layout.fillWidth: true
                Layout.preferredHeight: lifecycleContent.implicitHeight + tokens.spaceLg * 2
                radius: tokens.radiusMd
                color: tokens.surface
                border.color: tokens.border
                Accessible.role: Accessible.Grouping
                Accessible.name: "Diagnostic lifecycle management"
                Accessible.description: adapter.taskStatusText + ". " + adapter.campaignLifecycleText + ". " + adapter.campaignNodeLifecycleText

                ColumnLayout {
                    id: lifecycleContent
                    anchors.fill: parent
                    anchors.margins: tokens.spaceLg
                    spacing: tokens.spaceMd

                    Text {
                        text: "LIFECYCLE MANAGEMENT"
                        color: tokens.accent
                        font.pixelSize: tokens.labelSize
                        font.bold: true
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: tokens.textScale >= 1.75 ? 1 : 3
                        columnSpacing: tokens.spaceMd
                        rowSpacing: tokens.spaceMd

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: tokens.spaceSm

                            Text {
                                Layout.fillWidth: true
                                text: "DIAGNOSTIC TASK\n" + adapter.taskStatusText
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            GridLayout {
                                objectName: "diagnosticTaskLifecycleActionGrid"
                                columns: tokens.textScale >= 1.75 ? 1 : 3
                                columnSpacing: tokens.spaceXs
                                rowSpacing: tokens.spaceXs

                                DiagnosticCommandButton {
                                    id: pauseTaskButton
                                    objectName: "pauseDiagnosticTaskTargetButton"
                                    tokens: page.tokens
                                    text: "Pause Task"
                                    enabled: adapter.canPauseTask
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: tokens.controlHeight
                                    accessibleName: "Pause Diagnostic Task lifecycle"
                                    onFocusEntered: page.rememberFocus(item)
                                    onClicked: {
                                        adapter.pauseDiagnosticTaskTarget()
                                        Qt.callLater(function() {
                                            page.focusFirstAvailable([
                                                resumeTaskButton,
                                                cancelTaskButton,
                                                pauseTaskButton
                                            ])
                                        })
                                    }
                                }
                                DiagnosticCommandButton {
                                    id: resumeTaskButton
                                    objectName: "resumeDiagnosticTaskTargetButton"
                                    tokens: page.tokens
                                    text: "Resume Task"
                                    enabled: adapter.canResumeTask
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: tokens.controlHeight
                                    accessibleName: "Resume Diagnostic Task lifecycle"
                                    onFocusEntered: page.rememberFocus(item)
                                    onClicked: {
                                        adapter.resumeDiagnosticTaskTarget()
                                        Qt.callLater(function() {
                                            page.focusFirstAvailable([
                                                pauseTaskButton,
                                                cancelTaskButton,
                                                resumeTaskButton
                                            ])
                                        })
                                    }
                                }
                                DiagnosticCommandButton {
                                    id: cancelTaskButton
                                    objectName: "cancelDiagnosticTaskTargetButton"
                                    tokens: page.tokens
                                    text: "Cancel Task"
                                    enabled: adapter.canCancelTask
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: tokens.controlHeight
                                    accessibleName: "Cancel Diagnostic Task lifecycle"
                                    accessibleDescription: "Cancel only the typed non-transactional Diagnostic Task lifecycle target"
                                    onFocusEntered: page.rememberFocus(item)
                                    onClicked: {
                                        adapter.cancelDiagnosticTaskTarget()
                                        Qt.callLater(function() {
                                            page.focusFirstAvailable([
                                                retryNodeButton,
                                                createButton
                                            ])
                                        })
                                    }
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: tokens.spaceSm

                            Text {
                                Layout.fillWidth: true
                                text: "FORMAL CAMPAIGN\n" + adapter.campaignLifecycleText
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            GridLayout {
                                objectName: "formalCampaignLifecycleActionGrid"
                                columns: tokens.textScale >= 1.75 ? 1 : 3
                                columnSpacing: tokens.spaceXs
                                rowSpacing: tokens.spaceXs

                                DiagnosticCommandButton {
                                    id: pauseCampaignButton
                                    objectName: "pauseFormalDiagnosticCampaignTargetButton"
                                    tokens: page.tokens
                                    text: "Pause Campaign"
                                    enabled: adapter.canPauseCampaign
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: tokens.controlHeight
                                    accessibleName: "Pause Formal Diagnostic Campaign lifecycle"
                                    onFocusEntered: page.rememberFocus(item)
                                    onClicked: {
                                        adapter.pauseFormalDiagnosticCampaignTarget()
                                        Qt.callLater(function() {
                                            page.focusFirstAvailable([
                                                resumeCampaignButton,
                                                cancelCampaignButton,
                                                pauseCampaignButton
                                            ])
                                        })
                                    }
                                }
                                DiagnosticCommandButton {
                                    id: resumeCampaignButton
                                    objectName: "resumeFormalDiagnosticCampaignTargetButton"
                                    tokens: page.tokens
                                    text: "Resume Campaign"
                                    enabled: adapter.canResumeCampaign
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: tokens.controlHeight
                                    accessibleName: "Resume Formal Diagnostic Campaign lifecycle"
                                    onFocusEntered: page.rememberFocus(item)
                                    onClicked: {
                                        adapter.resumeFormalDiagnosticCampaignTarget()
                                        Qt.callLater(function() {
                                            page.focusFirstAvailable([
                                                pauseCampaignButton,
                                                cancelCampaignButton,
                                                resumeCampaignButton
                                            ])
                                        })
                                    }
                                }
                                DiagnosticCommandButton {
                                    id: cancelCampaignButton
                                    objectName: "cancelFormalDiagnosticCampaignTargetButton"
                                    tokens: page.tokens
                                    text: "Cancel Campaign"
                                    enabled: adapter.canCancelCampaign
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: tokens.controlHeight
                                    accessibleName: "Cancel Formal Diagnostic Campaign lifecycle"
                                    accessibleDescription: "Cancel only the typed non-transactional Formal Diagnostic Campaign lifecycle target"
                                    onFocusEntered: page.rememberFocus(item)
                                    onClicked: {
                                        adapter.cancelFormalDiagnosticCampaignTarget()
                                        Qt.callLater(function() {
                                            page.focusFirstAvailable([
                                                retryNodeButton,
                                                createButton
                                            ])
                                        })
                                    }
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: tokens.spaceSm

                            Text {
                                Layout.fillWidth: true
                                text: "CAMPAIGN NODE\n" + adapter.campaignNodeLifecycleText
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            GridLayout {
                                objectName: "campaignNodeLifecycleActionGrid"
                                columns: tokens.textScale >= 1.75 ? 1 : 3
                                columnSpacing: tokens.spaceXs
                                rowSpacing: tokens.spaceXs

                                DiagnosticCommandButton {
                                    id: pauseNodeButton
                                    objectName: "pauseCampaignNodeTargetButton"
                                    tokens: page.tokens
                                    text: "Pause Node"
                                    enabled: adapter.canPauseCampaignNode
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: tokens.controlHeight
                                    accessibleName: "Pause Campaign node lifecycle"
                                    onFocusEntered: page.rememberFocus(item)
                                    onClicked: {
                                        adapter.pauseCampaignNodeTarget()
                                        Qt.callLater(function() {
                                            page.focusFirstAvailable([
                                                resumeNodeButton,
                                                cancelNodeButton,
                                                pauseNodeButton
                                            ])
                                        })
                                    }
                                }
                                DiagnosticCommandButton {
                                    id: resumeNodeButton
                                    objectName: "resumeCampaignNodeTargetButton"
                                    tokens: page.tokens
                                    text: "Resume Node"
                                    enabled: adapter.canResumeCampaignNode
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: tokens.controlHeight
                                    accessibleName: "Resume Campaign node lifecycle"
                                    onFocusEntered: page.rememberFocus(item)
                                    onClicked: {
                                        adapter.resumeCampaignNodeTarget()
                                        Qt.callLater(function() {
                                            page.focusFirstAvailable([
                                                pauseNodeButton,
                                                cancelNodeButton,
                                                resumeNodeButton
                                            ])
                                        })
                                    }
                                }
                                DiagnosticCommandButton {
                                    id: cancelNodeButton
                                    objectName: "cancelCampaignNodeTargetButton"
                                    tokens: page.tokens
                                    text: "Cancel Node"
                                    enabled: adapter.canCancelCampaignNode
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: tokens.controlHeight
                                    accessibleName: "Cancel Campaign node lifecycle"
                                    accessibleDescription: "Cancel only the typed non-transactional Campaign node lifecycle target"
                                    onFocusEntered: page.rememberFocus(item)
                                    onClicked: {
                                        adapter.cancelCampaignNodeTarget()
                                        Qt.callLater(function() {
                                            page.focusFirstAvailable([
                                                retryNodeButton,
                                                createButton
                                            ])
                                        })
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        objectName: "failedCampaignNodeAttemptHistory"
                        Layout.fillWidth: true
                        text: adapter.failedNodeRetryText
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WrapAnywhere
                        Accessible.role: Accessible.StaticText
                        Accessible.name: "Failed Campaign node attempt history"
                        Accessible.description: text
                    }

                    DiagnosticCommandButton {
                        id: retryNodeButton
                        objectName: "retryFailedCampaignNodeButton"
                        tokens: page.tokens
                        text: "Retry Failed Node"
                        enabled: adapter.canRetryFailedCampaignNode
                        Layout.fillWidth: true
                        Layout.preferredHeight: tokens.controlHeight
                        accessibleName: "Retry failed Campaign node attempt"
                        accessibleDescription: "Create a new typed Campaign attempt linked to the immutable failed predecessor and a persistent TaskHandle"
                        onFocusEntered: page.rememberFocus(item)
                        onClicked: {
                            adapter.retryFailedCampaignNode()
                            Qt.callLater(function() {
                                Qt.callLater(function() {
                                    page.focusFirstAvailable([
                                        pauseTaskButton,
                                        pauseCampaignButton,
                                        pauseNodeButton,
                                        retryNodeButton
                                    ])
                                })
                            })
                        }
                    }
                }
            }
        }
    }
}
