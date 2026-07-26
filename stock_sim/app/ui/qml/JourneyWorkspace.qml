import QtQuick 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: workspace
    objectName: "journeyWorkspace"
    color: tokens.background

    property string activeRoute: "run_monitoring"
    property bool evidenceAvailable: evidenceAndFindings !== null
    property var designSystem: tokens
    readonly property var evidenceInitialFocusItem: (
        evidencePageLoader.item === null
            ? null
            : evidencePageLoader.item.firstCandidateControl
    )
    readonly property var evidenceSecondCandidateFocusItem: (
        evidencePageLoader.item === null
            ? null
            : evidencePageLoader.item.secondCandidateControl
    )
    readonly property var evidenceFindingFocusItem: (
        evidencePageLoader.item === null
            ? null
            : evidencePageLoader.item.firstFindingControl
    )
    readonly property var evidenceAlternateFindingFocusItem: (
        evidencePageLoader.item === null
            ? null
            : evidencePageLoader.item.secondFindingControl
    )
    property string evidenceScreenState: evidenceAvailable
        ? evidenceAndFindings.presentationState
        : "unavailable"
    property string screenState: runMonitoring.presentationState
    property string headline: screenState === "loading"
        ? "Preparing Run Monitoring"
        : screenState === "disconnected"
            ? "Run Monitoring is disconnected"
            : screenState === "active"
                ? "Strategy Run is active"
                : screenState === "terminal"
                    ? "Strategy Run reached a terminal state"
                    : "No Strategy Run selected"
    property string detail: screenState === "loading"
        ? "Waiting for the first immutable Run Monitoring state."
        : screenState === "disconnected"
            ? "Runtime data is unavailable. No Strategy Run state is being inferred."
            : screenState === "active" || screenState === "terminal"
                ? "Observe pinned diagnostic identities, progress, timing, execution assumptions, and read-only runtime context."
                : "Open an existing Formal Diagnostic Campaign or Strategy Run to monitor it here."
    property var lastRunFocus: null

    function rememberRunFocus(item) {
        lastRunFocus = item
        ensureRunItemVisible(item)
    }

    function ensureRunItemVisible(item) {
        if (item === null || !runMonitoringScroll.visible)
            return
        var point = item.mapToItem(
            runMonitoringScroll.contentItem,
            0,
            0
        )
        var top = point.y - tokens.spaceMd
        var bottom = point.y + item.height + tokens.spaceMd
        if (top < runMonitoringScroll.contentY)
            runMonitoringScroll.contentY = Math.max(0, top)
        else if (bottom > runMonitoringScroll.contentY
                + runMonitoringScroll.height)
            runMonitoringScroll.contentY = Math.min(
                runMonitoringScroll.contentHeight
                    - runMonitoringScroll.height,
                bottom - runMonitoringScroll.height
            )
    }

    function restoreRunFocus() {
        var target = lastRunFocus
        if (target === null || !target.visible || !target.enabled) {
            if (pauseDiagnosticTask.visible && pauseDiagnosticTask.enabled)
                target = pauseDiagnosticTask
            else if (resumeDiagnosticTask.visible
                    && resumeDiagnosticTask.enabled)
                target = resumeDiagnosticTask
            else if (cancelDiagnosticTask.visible
                    && cancelDiagnosticTask.enabled)
                target = cancelDiagnosticTask
            else
                target = runMonitoringRouteNavigation
        }
        target.forceActiveFocus()
        ensureRunItemVisible(target)
    }

    function repairRunFocus() {
        if (runMonitoringRouteNavigation.activeFocus
                || evidenceAndFindingsRouteNavigation.activeFocus
                || (pauseDiagnosticTask.activeFocus
                    && pauseDiagnosticTask.enabled)
                || (resumeDiagnosticTask.activeFocus
                    && resumeDiagnosticTask.enabled)
                || (cancelDiagnosticTask.activeFocus
                    && cancelDiagnosticTask.enabled))
            return
        restoreRunFocus()
    }

    function repairEvidenceFocus() {
        if (runMonitoringRouteNavigation.activeFocus
                || evidenceAndFindingsRouteNavigation.activeFocus
                || (evidencePageLoader.item !== null
                    && evidencePageLoader.item.hasMeaningfulFocus))
            return
        restoreActiveRouteFocus()
    }

    function restoreActiveRouteFocus() {
        if (activeRoute === "evidence_and_findings"
                && evidencePageLoader.item !== null)
            evidencePageLoader.item.restoreFocus()
        else
            restoreRunFocus()
    }

    function openRoute(route) {
        activeRoute = route
        Qt.callLater(restoreActiveRouteFocus)
    }

    onActiveRouteChanged: Qt.callLater(restoreActiveRouteFocus)
    Component.onCompleted: Qt.callLater(restoreActiveRouteFocus)

    DesignTokens {
        id: tokens
        objectName: "designTokens"
    }

    Timer {
        interval: 1000
        repeat: true
        running: workspace.screenState === "active"
        onTriggered: runMonitoring.refresh()
    }

    Connections {
        target: runMonitoring
        function onStateChanged() {
            if (workspace.activeRoute === "run_monitoring")
                Qt.callLater(workspace.repairRunFocus)
        }
    }

    Connections {
        target: evidenceAndFindings
        enabled: workspace.evidenceAvailable
        function onStateChanged() {
            if (workspace.activeRoute === "evidence_and_findings")
                Qt.callLater(workspace.repairEvidenceFocus)
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: Math.max(
                220,
                tokens.bodySize * 10 + tokens.spaceLg * 2
            )
            Layout.fillHeight: true
            color: tokens.rail

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: tokens.spaceLg
                spacing: tokens.spaceLg

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: tokens.spaceXs

                    Text {
                        text: "UTI"
                        color: tokens.accent
                        font.pixelSize: 18
                        font.bold: true
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Strategy Diagnostics"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Research workspace"
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                    }
                }

                Rectangle {
                    id: runMonitoringRouteNavigation
                    objectName: "runMonitoringRouteNavigation"
                    activeFocusOnTab: true
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
                    Layout.preferredHeight: Math.max(
                        44,
                        tokens.bodySize + tokens.spaceSm * 2
                    )
                    radius: tokens.radiusSm
                    color: workspace.activeRoute === "run_monitoring"
                        ? tokens.surfaceRaised : "transparent"
                    border.color: workspace.activeRoute === "run_monitoring"
                        ? tokens.accent : tokens.border
                    border.width: activeFocus ? tokens.focusWidth : 1
                    Accessible.name: "Open Run Monitoring"
                    Accessible.description: (
                        "Navigate to the read-only Run Monitoring route"
                    )
                    Accessible.role: Accessible.Button
                    Accessible.focusable: true
                    Accessible.focused: activeFocus
                    Accessible.selectable: true
                    Accessible.selected: (
                        workspace.activeRoute === "run_monitoring"
                    )
                    Accessible.onPressAction: (
                        workspace.openRoute("run_monitoring")
                    )

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: tokens.spaceMd
                        anchors.rightMargin: tokens.spaceSm
                        verticalAlignment: Text.AlignVCenter
                        text: "Run Monitoring"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                        wrapMode: Text.WordWrap
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: workspace.openRoute("run_monitoring")
                    }
                    Keys.onReturnPressed: function(event) {
                        workspace.openRoute("run_monitoring")
                        event.accepted = true
                    }
                    Keys.onSpacePressed: function(event) {
                        workspace.openRoute("run_monitoring")
                        event.accepted = true
                    }
                }

                Rectangle {
                    id: evidenceAndFindingsRouteNavigation
                    objectName: "evidenceAndFindingsRouteNavigation"
                    activeFocusOnTab: true
                    visible: workspace.evidenceAvailable
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
                    Layout.preferredHeight: Math.max(
                        44,
                        tokens.bodySize + tokens.spaceSm * 2
                    )
                    radius: tokens.radiusSm
                    color: workspace.activeRoute === "evidence_and_findings"
                        ? tokens.surfaceRaised : "transparent"
                    border.color: workspace.activeRoute === "evidence_and_findings"
                        ? tokens.accent : tokens.border
                    border.width: activeFocus ? tokens.focusWidth : 1
                    Accessible.name: "Open Evidence and Findings"
                    Accessible.description: (
                        "Navigate to read-only evidence and failure reasons"
                    )
                    Accessible.role: Accessible.Button
                    Accessible.focusable: true
                    Accessible.focused: activeFocus
                    Accessible.selectable: true
                    Accessible.selected: (
                        workspace.activeRoute === "evidence_and_findings"
                    )
                    Accessible.onPressAction: (
                        workspace.openRoute("evidence_and_findings")
                    )

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: tokens.spaceMd
                        anchors.rightMargin: tokens.spaceSm
                        verticalAlignment: Text.AlignVCenter
                        text: "Evidence & Findings"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                        wrapMode: Text.WordWrap
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: (
                            workspace.openRoute("evidence_and_findings")
                        )
                    }
                    Keys.onReturnPressed: function(event) {
                        workspace.openRoute("evidence_and_findings")
                        event.accepted = true
                    }
                    Keys.onSpacePressed: function(event) {
                        workspace.openRoute("evidence_and_findings")
                        event.accepted = true
                    }
                }

                Item {
                    Layout.fillHeight: true
                }

                Text {
                    Layout.fillWidth: true
                    text: "Read-only diagnostics workspace"
                    color: tokens.textQuiet
                    font.pixelSize: tokens.labelSize
                    wrapMode: Text.WordWrap
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Flickable {
                id: runMonitoringScroll
                objectName: "runMonitoringFlickable"
                visible: workspace.activeRoute === "run_monitoring"
                anchors.fill: parent
                clip: true
                contentWidth: width
                contentHeight: runMonitoringPage.implicitHeight
                    + tokens.spaceXl * 2

                ColumnLayout {
                    id: runMonitoringPage
                    width: Math.max(0, parent.width - tokens.spaceXl * 2)
                    implicitWidth: width
                    x: tokens.spaceXl
                    y: tokens.spaceXl
                    spacing: tokens.spaceLg

                RowLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: runMonitoringPage.width

                    ColumnLayout {
                        spacing: tokens.spaceXs

                        Text {
                            text: "RUN MONITORING"
                            color: tokens.accent
                            font.pixelSize: tokens.labelSize
                            font.bold: true
                        }
                        Text {
                            objectName: "runMonitoringSubtitle"
                            Layout.fillWidth: true
                            text: "Observe a Strategy Run without entering a trading workspace."
                            color: tokens.textMuted
                            font.pixelSize: tokens.bodySize
                            wrapMode: Text.WrapAnywhere
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                    }

                    Text {
                        text: runMonitoring.revisionText
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                    }
                }

                Rectangle {
                    id: runMonitoringAccessibleStatus
                    objectName: "runMonitoringAccessibleStatus"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: runMonitoringPage.width
                    Layout.preferredHeight: Math.max(
                        214,
                        tokens.spaceXl * 2
                            + Math.round(28 * tokens.textScale)
                            + Math.round(tokens.titleSize * 1.25)
                            + tokens.bodySize * 3
                            + tokens.labelSize * (
                                tokens.textScale >= 1.75 ? 4 : 2
                            )
                            + tokens.spaceMd * 4
                    )
                    radius: tokens.radiusMd
                    color: tokens.surface
                    border.color: tokens.border
                    Accessible.role: Accessible.StatusBar
                    Accessible.name: "Run Monitoring "
                        + workspace.screenState + ", phase "
                        + runMonitoring.phase + ", completeness "
                        + runMonitoring.completeness
                    Accessible.description: workspace.detail
                        + " Status " + runMonitoring.statusText
                        + ". Freshness " + runMonitoring.freshness
                        + ", age " + runMonitoring.ageText
                        + ", source " + runMonitoring.sourceIdentity
                        + ", observed " + runMonitoring.observedAtText

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: tokens.spaceXl
                        spacing: tokens.spaceMd

                        Rectangle {
                            Layout.preferredWidth: Math.max(
                                92,
                                statusPillText.implicitWidth + tokens.spaceMd
                            )
                            Layout.preferredHeight: Math.max(
                                28,
                                statusPillText.implicitHeight + tokens.spaceXs
                            )
                            radius: tokens.radiusSm
                            color: tokens.surfaceRaised
                            border.color: tokens.border

                            Text {
                                id: statusPillText
                                anchors.centerIn: parent
                                text: workspace.screenState.toUpperCase()
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                        }

                        Text {
                            objectName: "runMonitoringHeadline"
                            Layout.fillWidth: true
                            text: workspace.headline
                            color: tokens.textPrimary
                            font.pixelSize: tokens.titleSize
                            font.bold: true
                            wrapMode: Text.WrapAnywhere
                        }

                        Text {
                            objectName: "runMonitoringDetail"
                            Layout.fillWidth: true
                            text: workspace.detail
                            color: tokens.textMuted
                            font.pixelSize: tokens.bodySize
                            wrapMode: Text.WrapAnywhere
                        }

                        Item {
                            Layout.fillHeight: true
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: tokens.textScale >= 1.75 ? 1 : 3
                            columnSpacing: tokens.spaceLg
                            rowSpacing: tokens.spaceXs

                            Text {
                                Layout.fillWidth: true
                                text: "Freshness · " + runMonitoring.freshness
                                    + " · age " + runMonitoring.ageText
                                    + " / " + runMonitoring.freshnessThresholdText
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Source · " + runMonitoring.sourceIdentity
                                    + " · " + runMonitoring.sourceGenerationText
                                    + " · " + runMonitoring.mountGenerationText
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Observed · " + runMonitoring.observedAtText
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                horizontalAlignment: tokens.textScale >= 1.75
                                    ? Text.AlignLeft
                                    : Text.AlignRight
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }

                GridLayout {
                    objectName: "runMonitoringResearchGrid"
                    visible: workspace.screenState === "active"
                        || workspace.screenState === "terminal"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: runMonitoringPage.width
                    columns: tokens.textScale >= 1.75 ? 1 : 2
                    columnSpacing: tokens.spaceMd
                    rowSpacing: tokens.spaceMd

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: parent.width
                        Layout.preferredHeight: Math.max(
                            150,
                            tokens.labelSize * 9 + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: "PINNED IDENTITIES"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Campaign · " + runMonitoring.campaignIdentity
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Run · " + runMonitoring.runIdentity
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Strategy Under Test · " + runMonitoring.strategyIdentity
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Market Scenario · " + runMonitoring.marketScenarioIdentity
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Scenario-set · " + runMonitoring.scenarioSetIdentity
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Reproduction Manifest · " + runMonitoring.reproductionManifestIdentity
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }

                    Rectangle {
                        id: runMonitoringAccessibleProgress
                        objectName: "runMonitoringAccessibleProgress"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: parent.width
                        Layout.preferredHeight: Math.max(
                            150,
                            tokens.labelSize * 9 + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border
                        Accessible.role: Accessible.StaticText
                        Accessible.name: "Diagnostic run progress "
                            + runMonitoring.progressText
                        Accessible.description: "Lifecycle "
                            + runMonitoring.lifecycle + ", current node "
                            + runMonitoring.currentNodeText + ", progress "
                            + runMonitoring.progressText

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: "RUN PROGRESS"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Lifecycle · " + runMonitoring.lifecycle
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Current node · " + runMonitoring.currentNodeText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Progress · " + runMonitoring.progressText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Simulation Time · " + runMonitoring.simulationTimeText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Wall Time · " + runMonitoring.wallTimeText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: parent.width
                        Layout.preferredHeight: Math.max(
                            132,
                            tokens.labelSize * 7 + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: "EXECUTION ASSUMPTIONS"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: runMonitoring.executionAssumptionsText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: runMonitoring.alertsText
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: parent.width
                        Layout.preferredHeight: Math.max(
                            132,
                            tokens.labelSize * 9 + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: "READ-ONLY DIAGNOSTIC CONTEXT"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: runMonitoring.diagnosticContextText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }
                }

                ColumnLayout {
                    visible: workspace.screenState === "active"
                        || workspace.screenState === "terminal"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: runMonitoringPage.width
                    spacing: tokens.spaceXs

                    GridLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: parent.width
                        columns: tokens.textScale >= 1.75 ? 1 : 3
                        columnSpacing: tokens.spaceSm
                        rowSpacing: tokens.spaceXs

                        DiagnosticCommandButton {
                            id: pauseDiagnosticTask
                            objectName: "pauseDiagnosticTask"
                            text: "Pause diagnostic task"
                            Layout.preferredWidth: implicitWidth
                            Layout.fillWidth: tokens.textScale >= 1.75
                            Layout.preferredHeight: tokens.controlHeight
                            enabled: runMonitoring.canPause
                            radius: tokens.radiusSm
                            color: tokens.surfaceRaised
                            enabledTextColor: tokens.textPrimary
                            disabledTextColor: tokens.textQuiet
                            standardBorderColor: tokens.border
                            focusColor: tokens.focus
                            focusBorderWidth: tokens.focusWidth
                            labelSize: tokens.labelSize
                            onFocusEntered: workspace.rememberRunFocus(item)
                            onInvoked: runMonitoring.pauseDiagnosticTask()
                        }

                        DiagnosticCommandButton {
                            id: resumeDiagnosticTask
                            objectName: "resumeDiagnosticTask"
                            text: "Resume diagnostic task"
                            Layout.preferredWidth: implicitWidth
                            Layout.fillWidth: tokens.textScale >= 1.75
                            Layout.preferredHeight: tokens.controlHeight
                            enabled: runMonitoring.canResume
                            radius: tokens.radiusSm
                            color: tokens.surfaceRaised
                            enabledTextColor: tokens.textPrimary
                            disabledTextColor: tokens.textQuiet
                            standardBorderColor: tokens.border
                            focusColor: tokens.focus
                            focusBorderWidth: tokens.focusWidth
                            labelSize: tokens.labelSize
                            onFocusEntered: workspace.rememberRunFocus(item)
                            onInvoked: runMonitoring.resumeDiagnosticTask()
                        }

                        DiagnosticCommandButton {
                            id: cancelDiagnosticTask
                            objectName: "cancelDiagnosticTask"
                            text: "Cancel diagnostic task"
                            Layout.preferredWidth: implicitWidth
                            Layout.fillWidth: tokens.textScale >= 1.75
                            Layout.preferredHeight: tokens.controlHeight
                            enabled: runMonitoring.canCancel
                            radius: tokens.radiusSm
                            color: tokens.surfaceRaised
                            enabledTextColor: tokens.textPrimary
                            disabledTextColor: tokens.textQuiet
                            standardBorderColor: tokens.border
                            focusColor: tokens.focus
                            focusBorderWidth: tokens.focusWidth
                            labelSize: tokens.labelSize
                            onFocusEntered: workspace.rememberRunFocus(item)
                            onInvoked: runMonitoring.cancelDiagnosticTask()
                        }

                    }

                    Text {
                        objectName: "diagnosticCommandFeedback"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: parent.width
                        text: {
                            var lines = []
                            if (runMonitoring.commandMessage)
                                lines.push(runMonitoring.commandMessage)
                            if (runMonitoring.activeTaskText)
                                lines.push(runMonitoring.activeTaskText)
                            return lines.join("\n")
                        }
                        color: tokens.textMuted
                        font.pixelSize: tokens.labelSize
                        horizontalAlignment: Text.AlignRight
                        wrapMode: Text.WrapAnywhere
                        Accessible.name: text
                        Accessible.role: Accessible.AlertMessage
                    }
                }

                Item {
                    Layout.fillHeight: true
                }

                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: runMonitoringPage.width
                    text: "No experiment launch or discretionary trading controls are available in this workspace."
                    color: tokens.textQuiet
                    font.pixelSize: tokens.labelSize
                    horizontalAlignment: Text.AlignRight
                    wrapMode: Text.WrapAnywhere
                }
                }
            }

            Loader {
                id: evidencePageLoader
                objectName: "evidenceAndFindingsPageLoader"
                anchors.fill: parent
                active: workspace.evidenceAvailable
                visible: workspace.activeRoute === "evidence_and_findings"
                sourceComponent: Component {
                    EvidenceAndFindingsPage {
                        adapter: evidenceAndFindings
                        tokens: workspace.designSystem
                    }
                }
            }
        }
    }
}
