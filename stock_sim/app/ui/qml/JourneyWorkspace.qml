import QtQuick 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: workspace
    objectName: "journeyWorkspace"
    color: tokens.background

    property bool strategyLibraryAvailable: strategyLibrary !== null
    property bool scenarioLabAvailable: scenarioLab !== null
    property bool diagnosticTasksAvailable: diagnosticTasks !== null
    property string activeRoute: "diagnostic_tasks"
    property string routeRecoveryReason: initialJourneyRecoveryReason
    property string routeRecoveryMessage: initialJourneyRecoveryMessage
    property string requestedFocusRoute: initialJourneyFocusRoute
    property string requestedFocusControl: initialJourneyFocusControl
    property string requestedFocusIdentity: initialJourneyFocusIdentity
    property bool focusReturnConsumed: false
    property string authoritativeFocusPendingRoute: ""
    property bool diagnosticTasksPageActivated: (
        initialJourneyRoute === "diagnostic_tasks"
    )
    property bool evidenceAvailable: evidenceAndFindings !== null
    property bool systemHealthAvailable: systemHealth !== null
    property string diagnosticTasksInventoryState: (
        diagnosticTasksAvailable
            ? diagnosticTasks.presentationState
            : "unavailable"
    )
    property var designSystem: tokens
    readonly property var evidenceInitialFocusItem: (
        evidencePageLoader.item === null
            ? null
            : evidencePageLoader.item.firstCandidateControl
    )
    readonly property var diagnosticTasksInitialFocusItem: (
        diagnosticTasksPageLoader.item === null
            ? null
            : diagnosticTasksPageLoader.item.firstActionControl
    )
    readonly property var strategyLibraryInitialFocusItem: (
        strategyLibraryPageLoader.item === null
            ? null
            : strategyLibraryPageLoader.item.firstActionControl
    )
    readonly property var scenarioLabInitialFocusItem: (
        scenarioLabPageLoader.item === null
            ? null
            : scenarioLabPageLoader.item.firstActionControl
    )
    readonly property var runMonitoringInitialFocusItem: runFocusFallback()
    readonly property var systemHealthInitialFocusItem: (
        systemHealthPageLoader.item === null
            ? null
            : systemHealthPageLoader.item.firstFocusControl
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
    property int installedAccessibilityCheckpointSequence: 0
    property string installedAccessibilityCheckpointState: ""
    property string installedAccessibilityCheckpointRoute: ""
    property string installedAccessibilityRunRevision: ""
    property string installedAccessibilityEvidenceRevision: ""
    property string installedAccessibilityStatusObjectName: ""
    property string installedAccessibilityStatusSemanticTerm: ""
    property int installedAccessibilityWindowScalePercent: 0
    readonly property string installedAccessibilityCheckpointText: (
        "Installed checkpoint sequence="
        + installedAccessibilityCheckpointSequence
        + " state=" + installedAccessibilityCheckpointState
        + " route=" + installedAccessibilityCheckpointRoute
        + " run_revision=" + installedAccessibilityRunRevision
        + " evidence_revision=" + installedAccessibilityEvidenceRevision
        + " target=" + installedAccessibilityStatusObjectName
        + " term=" + installedAccessibilityStatusSemanticTerm
        + " window_scale_percent="
        + installedAccessibilityWindowScalePercent
    )
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
    signal routeActivationRequested(string route)

    Rectangle {
        id: installedAccessibilityCheckpointMarker
        objectName: "installedAccessibilityCheckpointMarker"
        visible: workspace.installedAccessibilityCheckpointSequence > 0
        z: 1000
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: tokens.spaceSm
        width: Math.min(
            parent.width - tokens.spaceLg * 2,
            Math.max(520, installedCheckpointText.implicitWidth + tokens.spaceMd)
        )
        height: Math.max(
            tokens.controlHeight,
            installedCheckpointText.implicitHeight + tokens.spaceSm * 2
        )
        radius: tokens.radiusSm
        color: tokens.surfaceRaised
        border.color: tokens.border
        Accessible.role: Accessible.StatusBar
        Accessible.name: workspace.installedAccessibilityCheckpointText

        Text {
            id: installedCheckpointText
            anchors.fill: parent
            anchors.margins: tokens.spaceSm
            text: workspace.installedAccessibilityCheckpointText
            color: tokens.textPrimary
            font.pixelSize: tokens.labelSize
            wrapMode: Text.WrapAnywhere
            Accessible.ignored: true
        }
    }

    function rememberRunFocus(item) {
        lastRunFocus = item
        ensureRunItemVisible(item)
    }

    function ensureRailItemVisible(item) {
        if (item === null || !journeyRailFlickable.visible)
            return
        var point = item.mapToItem(journeyRailFlickable.contentItem, 0, 0)
        var top = point.y - tokens.spaceXs
        var bottom = point.y + item.height + tokens.spaceXs
        if (top < journeyRailFlickable.contentY)
            journeyRailFlickable.contentY = Math.max(0, top)
        else if (bottom > journeyRailFlickable.contentY
                + journeyRailFlickable.height)
            journeyRailFlickable.contentY = Math.min(
                journeyRailFlickable.contentHeight
                    - journeyRailFlickable.height,
                bottom - journeyRailFlickable.height
            )
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

    function runFocusFallback() {
        if (pauseDiagnosticTask.visible && pauseDiagnosticTask.enabled)
            return pauseDiagnosticTask
        if (resumeDiagnosticTask.visible && resumeDiagnosticTask.enabled)
            return resumeDiagnosticTask
        if (cancelDiagnosticTask.visible && cancelDiagnosticTask.enabled)
            return cancelDiagnosticTask
        return runMonitoringRouteNavigation
    }

    function restoreRunFocus() {
        var target = lastRunFocus
        if (target === null || !target.visible || !target.enabled)
            target = runFocusFallback()
        target.forceActiveFocus()
        ensureRunItemVisible(target)
    }

    function repairRunFocus() {
        if (strategyLibraryRouteNavigation.activeFocus
                || scenarioLabRouteNavigation.activeFocus
                || diagnosticTasksRouteNavigation.activeFocus
                || runMonitoringRouteNavigation.activeFocus
                || evidenceAndFindingsRouteNavigation.activeFocus
                || systemHealthRouteNavigation.activeFocus
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
        if (strategyLibraryRouteNavigation.activeFocus
                || scenarioLabRouteNavigation.activeFocus
                || diagnosticTasksRouteNavigation.activeFocus
                || runMonitoringRouteNavigation.activeFocus
                || evidenceAndFindingsRouteNavigation.activeFocus
                || systemHealthRouteNavigation.activeFocus
                || (evidencePageLoader.item !== null
                    && evidencePageLoader.item.hasMeaningfulFocus))
            return
        restoreActiveRouteFocus()
    }

    function repairDiagnosticTasksFocus() {
        if (strategyLibraryRouteNavigation.activeFocus
                || scenarioLabRouteNavigation.activeFocus
                || diagnosticTasksRouteNavigation.activeFocus
                || runMonitoringRouteNavigation.activeFocus
                || evidenceAndFindingsRouteNavigation.activeFocus
                || systemHealthRouteNavigation.activeFocus
                || (diagnosticTasksPageLoader.item !== null
                    && diagnosticTasksPageLoader.item.hasMeaningfulFocus))
            return
        restoreActiveRouteFocus()
    }

    function journeyRailHasFocus() {
        return strategyLibraryRouteNavigation.activeFocus
            || scenarioLabRouteNavigation.activeFocus
            || diagnosticTasksRouteNavigation.activeFocus
            || runMonitoringRouteNavigation.activeFocus
            || evidenceAndFindingsRouteNavigation.activeFocus
            || systemHealthRouteNavigation.activeFocus
    }

    function repairLoadedPageFocus(loader) {
        if (journeyRailHasFocus()
                || loader.item === null
                || loader.item.hasMeaningfulFocus)
            return
        restoreActiveRouteFocus()
    }

    function restoreActiveRouteFocus() {
        if (restoreFocusReturnToken()) {
            authoritativeFocusPendingRoute = ""
            return
        }
        if (activeRoute === "strategy_library") {
            if (strategyLibraryPageLoader.item === null
                    || !strategyLibraryPageLoader.item.restoreFocus())
                strategyLibraryRouteNavigation.forceActiveFocus()
        }
        else if (activeRoute === "scenario_lab") {
            if (scenarioLabPageLoader.item === null
                    || !scenarioLabPageLoader.item.restoreFocus())
                scenarioLabRouteNavigation.forceActiveFocus()
        }
        else if (activeRoute === "evidence_and_findings"
                && evidencePageLoader.item !== null)
            evidencePageLoader.item.restoreFocus()
        else if (activeRoute === "diagnostic_tasks") {
            if (diagnosticTasksPageLoader.item === null
                    || !diagnosticTasksPageLoader.item.restoreFocus())
                diagnosticTasksRouteNavigation.forceActiveFocus()
        }
        else if (activeRoute === "system_health") {
            if (systemHealthPageLoader.item === null
                    || !systemHealthPageLoader.item.restoreFocus())
                systemHealthRouteNavigation.forceActiveFocus()
        }
        else
            restoreRunFocus()
    }

    function findNamedItem(parentItem, objectName) {
        if (parentItem === null)
            return null
        if (parentItem.objectName === objectName)
            return parentItem
        var childItems = parentItem.children
        for (var index = 0; index < childItems.length; ++index) {
            var match = findNamedItem(childItems[index], objectName)
            if (match !== null)
                return match
        }
        return null
    }

    function restoreFocusReturnToken() {
        if (focusReturnConsumed
                || requestedFocusRoute !== activeRoute
                || requestedFocusControl.length === 0)
            return false
        var target = findNamedItem(workspace, requestedFocusControl)
        if (target === null || !target.visible || !target.enabled)
            return false
        if (requestedFocusIdentity.length > 0
                && target.objectName.indexOf(requestedFocusIdentity) < 0)
            return false
        target.forceActiveFocus()
        if (!target.activeFocus)
            return false
        focusReturnConsumed = true
        return true
    }

    function openRoute(route) {
        if (!routeAvailable(route))
            return
        if (activeRoute === route) {
            Qt.callLater(restoreActiveRouteFocus)
            return
        }
        routeActivationRequested(route)
    }

    function routeAvailable(route) {
        if (route === "strategy_library")
            return strategyLibraryAvailable
        if (route === "scenario_lab")
            return scenarioLabAvailable
        if (route === "diagnostic_tasks")
            return diagnosticTasksAvailable
        if (route === "run_monitoring")
            return true
        if (route === "evidence_and_findings")
            return evidenceAvailable
        if (route === "system_health")
            return systemHealthAvailable
        return false
    }

    onActiveRouteChanged: {
        if (activeRoute === "diagnostic_tasks")
            diagnosticTasksPageActivated = true
        authoritativeFocusPendingRoute = activeRoute
    }
    Component.onCompleted: {
        activeRoute = initialJourneyRoute
        Qt.callLater(function() {
            if (activeRoute === "system_health")
                systemHealthRouteNavigation.forceActiveFocus()
            else {
                restoreActiveRouteFocus()
                authoritativeFocusPendingRoute = ""
            }
        })
    }

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
        target: strategyLibrary
        enabled: workspace.strategyLibraryAvailable
        function onStateChanged() {
            if (workspace.activeRoute !== "strategy_library"
                    || strategyLibraryPageLoader.item === null)
                return
            if (workspace.authoritativeFocusPendingRoute
                    === "strategy_library"
                    || (!workspace.focusReturnConsumed
                        && workspace.requestedFocusRoute
                            === "strategy_library"
                        && workspace.requestedFocusControl.length > 0)) {
                workspace.authoritativeFocusPendingRoute = ""
                Qt.callLater(workspace.restoreActiveRouteFocus)
            }
            else
                Qt.callLater(function() {
                    workspace.repairLoadedPageFocus(
                        strategyLibraryPageLoader
                    )
                })
        }
    }

    Connections {
        target: scenarioLab
        enabled: workspace.scenarioLabAvailable
        function onStateChanged() {
            if (workspace.activeRoute !== "scenario_lab"
                    || scenarioLabPageLoader.item === null)
                return
            if (workspace.authoritativeFocusPendingRoute === "scenario_lab"
                    || (!workspace.focusReturnConsumed
                        && workspace.requestedFocusRoute === "scenario_lab"
                        && workspace.requestedFocusControl.length > 0)) {
                workspace.authoritativeFocusPendingRoute = ""
                Qt.callLater(workspace.restoreActiveRouteFocus)
            }
            else
                Qt.callLater(function() {
                    workspace.repairLoadedPageFocus(scenarioLabPageLoader)
                })
        }
    }

    Connections {
        target: diagnosticTasks
        enabled: workspace.diagnosticTasksAvailable
        function onStateChanged() {
            if (workspace.activeRoute !== "diagnostic_tasks")
                return
            if (workspace.authoritativeFocusPendingRoute
                    === "diagnostic_tasks"
                    || (!workspace.focusReturnConsumed
                        && workspace.requestedFocusRoute
                            === "diagnostic_tasks"
                        && workspace.requestedFocusControl.length > 0)) {
                workspace.authoritativeFocusPendingRoute = ""
                Qt.callLater(workspace.restoreActiveRouteFocus)
            }
            else
                Qt.callLater(workspace.repairDiagnosticTasksFocus)
        }
    }

    Connections {
        target: runMonitoring
        function onStateChanged() {
            if (workspace.activeRoute !== "run_monitoring")
                return
            if (workspace.authoritativeFocusPendingRoute
                    === "run_monitoring"
                    || (!workspace.focusReturnConsumed
                        && workspace.requestedFocusRoute === "run_monitoring"
                        && workspace.requestedFocusControl.length > 0)) {
                workspace.authoritativeFocusPendingRoute = ""
                Qt.callLater(workspace.restoreActiveRouteFocus)
            }
            else
                Qt.callLater(workspace.repairRunFocus)
        }
    }

    Connections {
        target: evidenceAndFindings
        enabled: workspace.evidenceAvailable
        function onStateChanged() {
            if (workspace.activeRoute !== "evidence_and_findings")
                return
            if (workspace.authoritativeFocusPendingRoute
                    === "evidence_and_findings"
                    || (!workspace.focusReturnConsumed
                        && workspace.requestedFocusRoute
                            === "evidence_and_findings"
                        && workspace.requestedFocusControl.length > 0)) {
                workspace.authoritativeFocusPendingRoute = ""
                Qt.callLater(workspace.restoreActiveRouteFocus)
            }
            else
                Qt.callLater(workspace.repairEvidenceFocus)
        }
    }

    Connections {
        target: systemHealth
        enabled: workspace.systemHealthAvailable
        function onStateChanged() {
            if (workspace.activeRoute === "system_health"
                    && (workspace.authoritativeFocusPendingRoute
                            === "system_health"
                        || (!workspace.focusReturnConsumed
                            && workspace.requestedFocusRoute
                                === "system_health"
                            && workspace.requestedFocusControl.length > 0))
                    && systemHealthPageLoader.item !== null)
            {
                workspace.authoritativeFocusPendingRoute = ""
                Qt.callLater(workspace.restoreActiveRouteFocus)
            }
            else if (workspace.activeRoute === "system_health")
                Qt.callLater(function() {
                    workspace.repairLoadedPageFocus(systemHealthPageLoader)
                })
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Flickable {
            id: journeyRailFlickable
            objectName: "journeyRailFlickable"
            Layout.preferredWidth: Math.max(
                220,
                tokens.bodySize * 10 + tokens.spaceLg * 2
            )
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: journeyRailContent.implicitHeight
                + tokens.spaceLg * 2
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Rectangle {
                anchors.fill: parent
                color: tokens.rail
                z: -1
            }

            ColumnLayout {
                id: journeyRailContent
                x: tokens.spaceLg
                y: tokens.spaceLg
                width: Math.max(
                    0,
                    journeyRailFlickable.width - tokens.spaceLg * 2
                )
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
                    id: strategyLibraryRouteNavigation
                    objectName: "strategyLibraryRouteNavigation"
                    property string accessibleName: "Open Strategy Library"
                    property string accessibleDescription: (
                        "Browse the backend-owned formal Strategy Under Test inventory"
                    )
                    readonly property bool focusVisible: activeFocus
                    activeFocusOnTab: true
                    visible: true
                    enabled: workspace.strategyLibraryAvailable
                    opacity: enabled ? 1.0 : 0.55
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
                    Layout.preferredHeight: Math.max(
                        44,
                        tokens.bodySize + tokens.spaceSm * 2
                    )
                    radius: tokens.radiusSm
                    color: workspace.activeRoute === "strategy_library"
                        ? tokens.surfaceRaised : "transparent"
                    border.color: workspace.activeRoute === "strategy_library"
                        ? tokens.accent : tokens.border
                    border.width: activeFocus ? tokens.focusWidth : 1
                    Accessible.name: accessibleName
                    Accessible.description: accessibleDescription
                    Accessible.role: Accessible.Button
                    Accessible.focusable: enabled
                    Accessible.focused: activeFocus
                    Accessible.selectable: true
                    Accessible.selected: workspace.activeRoute === "strategy_library"
                    Accessible.onPressAction: workspace.openRoute("strategy_library")
                    onActiveFocusChanged: {
                        if (activeFocus)
                            workspace.ensureRailItemVisible(this)
                    }
                    KeyNavigation.down: scenarioLabRouteNavigation
                    KeyNavigation.up: systemHealthRouteNavigation

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: tokens.spaceMd
                        anchors.rightMargin: tokens.spaceSm
                        verticalAlignment: Text.AlignVCenter
                        text: "Strategy Library"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                        wrapMode: Text.WordWrap
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: strategyLibraryRouteNavigation.enabled
                        cursorShape: Qt.PointingHandCursor
                        onClicked: workspace.openRoute("strategy_library")
                    }
                    Keys.onReturnPressed: function(event) {
                        workspace.openRoute("strategy_library")
                        event.accepted = true
                    }
                    Keys.onSpacePressed: function(event) {
                        workspace.openRoute("strategy_library")
                        event.accepted = true
                    }
                }

                Rectangle {
                    id: scenarioLabRouteNavigation
                    objectName: "scenarioLabRouteNavigation"
                    property string accessibleName: "Open Scenario Lab"
                    property string accessibleDescription: (
                        "Inspect admitted data, immutable Reference Market Paths, and Market Scenarios"
                    )
                    readonly property bool focusVisible: activeFocus
                    activeFocusOnTab: true
                    visible: true
                    enabled: workspace.scenarioLabAvailable
                    opacity: enabled ? 1.0 : 0.55
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
                    Layout.preferredHeight: Math.max(
                        44,
                        tokens.bodySize + tokens.spaceSm * 2
                    )
                    radius: tokens.radiusSm
                    color: workspace.activeRoute === "scenario_lab"
                        ? tokens.surfaceRaised : "transparent"
                    border.color: workspace.activeRoute === "scenario_lab"
                        ? tokens.accent : tokens.border
                    border.width: activeFocus ? tokens.focusWidth : 1
                    Accessible.name: accessibleName
                    Accessible.description: accessibleDescription
                    Accessible.role: Accessible.Button
                    Accessible.focusable: enabled
                    Accessible.focused: activeFocus
                    Accessible.selectable: true
                    Accessible.selected: workspace.activeRoute === "scenario_lab"
                    Accessible.onPressAction: workspace.openRoute("scenario_lab")
                    onActiveFocusChanged: {
                        if (activeFocus)
                            workspace.ensureRailItemVisible(this)
                    }
                    KeyNavigation.down: diagnosticTasksRouteNavigation
                    KeyNavigation.up: strategyLibraryRouteNavigation

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: tokens.spaceMd
                        anchors.rightMargin: tokens.spaceSm
                        verticalAlignment: Text.AlignVCenter
                        text: "Scenario Lab"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                        wrapMode: Text.WordWrap
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: scenarioLabRouteNavigation.enabled
                        cursorShape: Qt.PointingHandCursor
                        onClicked: workspace.openRoute("scenario_lab")
                    }
                    Keys.onReturnPressed: function(event) {
                        workspace.openRoute("scenario_lab")
                        event.accepted = true
                    }
                    Keys.onSpacePressed: function(event) {
                        workspace.openRoute("scenario_lab")
                        event.accepted = true
                    }
                }

                Rectangle {
                    id: diagnosticTasksRouteNavigation
                    objectName: "diagnosticTasksRouteNavigation"
                    property string accessibleName: (
                        "Open Diagnostic Tasks, inventory "
                        + workspace.diagnosticTasksInventoryState
                    )
                    property string accessibleDescription: (
                        "Navigate to authoritative Diagnostic Tasks inputs"
                        + ", inventory "
                        + workspace.diagnosticTasksInventoryState
                    )
                    readonly property bool focusVisible: activeFocus
                    activeFocusOnTab: true
                    visible: true
                    enabled: workspace.diagnosticTasksAvailable
                    opacity: enabled ? 1.0 : 0.55
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
                    Layout.preferredHeight: Math.max(
                        44,
                        tokens.bodySize + tokens.spaceSm * 2
                    )
                    radius: tokens.radiusSm
                    color: workspace.activeRoute === "diagnostic_tasks"
                        ? tokens.surfaceRaised : "transparent"
                    border.color: workspace.activeRoute === "diagnostic_tasks"
                        ? tokens.accent : tokens.border
                    border.width: activeFocus ? tokens.focusWidth : 1
                    Accessible.name: accessibleName
                    Accessible.description: accessibleDescription
                    Accessible.role: Accessible.Button
                    Accessible.focusable: enabled
                    Accessible.focused: activeFocus
                    Accessible.selectable: true
                    Accessible.selected: (
                        workspace.activeRoute === "diagnostic_tasks"
                    )
                    Accessible.onPressAction: (
                        workspace.openRoute("diagnostic_tasks")
                    )
                    onActiveFocusChanged: {
                        if (activeFocus)
                            workspace.ensureRailItemVisible(this)
                    }
                    KeyNavigation.down: runMonitoringRouteNavigation
                    KeyNavigation.up: scenarioLabRouteNavigation

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: tokens.spaceMd
                        anchors.rightMargin: tokens.spaceSm
                        verticalAlignment: Text.AlignVCenter
                        text: "Diagnostic Tasks · "
                            + workspace.diagnosticTasksInventoryState
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                        wrapMode: Text.WordWrap
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: diagnosticTasksRouteNavigation.enabled
                        cursorShape: Qt.PointingHandCursor
                        onClicked: workspace.openRoute("diagnostic_tasks")
                    }
                    Keys.onReturnPressed: function(event) {
                        workspace.openRoute("diagnostic_tasks")
                        event.accepted = true
                    }
                    Keys.onSpacePressed: function(event) {
                        workspace.openRoute("diagnostic_tasks")
                        event.accepted = true
                    }
                }

                Rectangle {
                    id: runMonitoringRouteNavigation
                    objectName: "runMonitoringRouteNavigation"
                    property string accessibleName: (
                        "Open Run Monitoring, current state "
                        + workspace.screenState
                    )
                    property string accessibleDescription: (
                        "Navigate to the read-only Run Monitoring route"
                        + ", current state " + workspace.screenState
                    )
                    readonly property bool focusVisible: activeFocus
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
                    Accessible.name: accessibleName
                    Accessible.description: accessibleDescription
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
                    onActiveFocusChanged: {
                        if (activeFocus)
                            workspace.ensureRailItemVisible(this)
                    }
                    KeyNavigation.down: evidenceAndFindingsRouteNavigation
                    KeyNavigation.up: diagnosticTasksRouteNavigation

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: tokens.spaceMd
                        anchors.rightMargin: tokens.spaceSm
                        verticalAlignment: Text.AlignVCenter
                        text: "Run Monitoring · " + workspace.screenState
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
                    property string accessibleName: (
                        "Open Evidence and Findings"
                    )
                    property string accessibleDescription: (
                        "Navigate to read-only evidence and failure reasons"
                    )
                    readonly property bool focusVisible: activeFocus
                    activeFocusOnTab: true
                    visible: true
                    enabled: workspace.evidenceAvailable
                    opacity: enabled ? 1.0 : 0.55
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
                    Layout.preferredHeight: Math.max(
                        44,
                        evidenceRouteNavigationLabel.contentHeight
                            + tokens.spaceSm * 2
                    )
                    radius: tokens.radiusSm
                    color: workspace.activeRoute === "evidence_and_findings"
                        ? tokens.surfaceRaised : "transparent"
                    border.color: workspace.activeRoute === "evidence_and_findings"
                        ? tokens.accent : tokens.border
                    border.width: activeFocus ? tokens.focusWidth : 1
                    Accessible.name: accessibleName
                    Accessible.description: accessibleDescription
                    Accessible.role: Accessible.Button
                    Accessible.focusable: enabled
                    Accessible.focused: activeFocus
                    Accessible.selectable: true
                    Accessible.selected: (
                        workspace.activeRoute === "evidence_and_findings"
                    )
                    Accessible.onPressAction: (
                        workspace.openRoute("evidence_and_findings")
                    )
                    onActiveFocusChanged: {
                        if (activeFocus)
                            workspace.ensureRailItemVisible(this)
                    }
                    KeyNavigation.down: systemHealthRouteNavigation
                    KeyNavigation.up: runMonitoringRouteNavigation

                    Text {
                        id: evidenceRouteNavigationLabel
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
                        enabled: evidenceAndFindingsRouteNavigation.enabled
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

                Rectangle {
                    id: evidenceRouteFreshnessStatus
                    objectName: "evidenceRouteFreshnessStatus"
                    visible: workspace.evidenceAvailable
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
                    Layout.preferredHeight: Math.max(
                        32,
                        tokens.labelSize + tokens.spaceSm * 2
                    )
                    radius: tokens.radiusSm
                    color: tokens.surface
                    border.color: (
                        workspace.evidenceAvailable
                        && evidenceAndFindings.freshness === "fresh"
                    )
                        ? tokens.accent
                        : tokens.focus
                    Accessible.role: Accessible.StatusBar
                    Accessible.name: "Evidence freshness "
                        + (workspace.evidenceAvailable
                            ? evidenceAndFindings.freshness
                            : "unavailable")
                    Accessible.description: workspace.evidenceAvailable
                        ? evidenceAndFindings.statusText
                        : "Evidence and Findings is unavailable"

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: tokens.spaceMd
                        anchors.rightMargin: tokens.spaceSm
                        verticalAlignment: Text.AlignVCenter
                        text: "Evidence · "
                            + (workspace.evidenceAvailable
                                ? evidenceAndFindings.freshness
                                : "unavailable")
                        color: (
                            workspace.evidenceAvailable
                            && evidenceAndFindings.freshness === "fresh"
                        )
                            ? tokens.accent
                            : tokens.textPrimary
                        font.pixelSize: tokens.labelSize
                        font.bold: true
                        wrapMode: Text.WrapAnywhere
                    }
                }

                Rectangle {
                    id: systemHealthRouteNavigation
                    objectName: "systemHealthRouteNavigation"
                    property string accessibleName: "Open System Health"
                    property string accessibleDescription: (
                        "Navigate to read-only diagnostics Runtime Health"
                    )
                    readonly property bool focusVisible: activeFocus
                    activeFocusOnTab: true
                    visible: true
                    enabled: workspace.systemHealthAvailable
                    opacity: enabled ? 1.0 : 0.55
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
                    Layout.preferredHeight: Math.max(
                        44,
                        tokens.bodySize + tokens.spaceSm * 2
                    )
                    radius: tokens.radiusSm
                    color: workspace.activeRoute === "system_health"
                        ? tokens.surfaceRaised : "transparent"
                    border.color: workspace.activeRoute === "system_health"
                        ? tokens.accent : tokens.border
                    border.width: activeFocus ? tokens.focusWidth : 1
                    Accessible.name: accessibleName
                    Accessible.description: accessibleDescription
                    Accessible.role: Accessible.Button
                    Accessible.focusable: enabled
                    Accessible.focused: activeFocus
                    Accessible.selectable: true
                    Accessible.selected: workspace.activeRoute === "system_health"
                    Accessible.onPressAction: workspace.openRoute("system_health")
                    onActiveFocusChanged: {
                        if (activeFocus)
                            workspace.ensureRailItemVisible(this)
                    }
                    KeyNavigation.down: strategyLibraryRouteNavigation
                    KeyNavigation.up: evidenceAndFindingsRouteNavigation

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: tokens.spaceMd
                        anchors.rightMargin: tokens.spaceSm
                        verticalAlignment: Text.AlignVCenter
                        text: "System Health"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                        wrapMode: Text.WordWrap
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: systemHealthRouteNavigation.enabled
                        cursorShape: Qt.PointingHandCursor
                        onClicked: workspace.openRoute("system_health")
                    }
                    Keys.onReturnPressed: function(event) {
                        workspace.openRoute("system_health")
                        event.accepted = true
                    }
                    Keys.onSpacePressed: function(event) {
                        workspace.openRoute("system_health")
                        event.accepted = true
                    }
                }

                Text {
                    objectName: "journeyRecoveryStatus"
                    visible: workspace.routeRecoveryReason !== "exact"
                    Layout.fillWidth: true
                    text: workspace.routeRecoveryMessage
                    color: tokens.focus
                    font.pixelSize: tokens.labelSize
                    wrapMode: Text.WordWrap
                    Accessible.role: Accessible.StatusBar
                    Accessible.name: "Journey recovery"
                    Accessible.description: text
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

            Loader {
                id: strategyLibraryPageLoader
                objectName: "strategyLibraryPageLoader"
                anchors.fill: parent
                active: workspace.strategyLibraryAvailable
                    && workspace.activeRoute === "strategy_library"
                visible: workspace.activeRoute === "strategy_library"
                function ensureLoaded() {
                    if (active && status === Loader.Null) {
                        setSource(
                            Qt.resolvedUrl("StrategyLibraryPage.qml"),
                            {
                                "adapter": strategyLibrary,
                                "tokens": workspace.designSystem
                            }
                        )
                    }
                }
                onActiveChanged: ensureLoaded()
                onLoaded: {
                    if (active && workspace.activeRoute === "strategy_library")
                        strategyLibrary.refresh()
                }
                Component.onCompleted: ensureLoaded()
            }

            Loader {
                id: scenarioLabPageLoader
                objectName: "scenarioLabPageLoader"
                anchors.fill: parent
                active: workspace.scenarioLabAvailable
                    && workspace.activeRoute === "scenario_lab"
                visible: workspace.activeRoute === "scenario_lab"
                function ensureLoaded() {
                    if (active && status === Loader.Null) {
                        setSource(
                            Qt.resolvedUrl("ScenarioLabPage.qml"),
                            {
                                "adapter": scenarioLab,
                                "tokens": workspace.designSystem
                            }
                        )
                    }
                }
                onActiveChanged: ensureLoaded()
                onLoaded: {
                    if (active && workspace.activeRoute === "scenario_lab")
                        scenarioLab.refresh()
                }
                Component.onCompleted: ensureLoaded()
            }

            Loader {
                id: diagnosticTasksPageLoader
                objectName: "diagnosticTasksPageLoader"
                anchors.fill: parent
                active: workspace.diagnosticTasksAvailable
                    && workspace.activeRoute === "diagnostic_tasks"
                visible: workspace.activeRoute === "diagnostic_tasks"
                function ensureLoaded() {
                    if (active && status === Loader.Null) {
                        setSource(
                            Qt.resolvedUrl("DiagnosticTasksPage.qml"),
                            {
                                "adapter": diagnosticTasks,
                                "tokens": workspace.designSystem
                            }
                        )
                    }
                }
                onActiveChanged: ensureLoaded()
                Component.onCompleted: ensureLoaded()
            }

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
                                objectName: "runMonitoringCampaignIdentity"
                                Layout.fillWidth: true
                                text: "Campaign · " + runMonitoring.campaignIdentity
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                objectName: "runMonitoringRunIdentity"
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
                    && workspace.activeRoute === "evidence_and_findings"
                visible: workspace.activeRoute === "evidence_and_findings"
                sourceComponent: Component {
                    EvidenceAndFindingsPage {
                        adapter: evidenceAndFindings
                        tokens: workspace.designSystem
                    }
                }
            }

            Loader {
                id: systemHealthPageLoader
                objectName: "systemHealthPageLoader"
                anchors.fill: parent
                active: workspace.systemHealthAvailable
                    && workspace.activeRoute === "system_health"
                visible: workspace.activeRoute === "system_health"
                sourceComponent: Component {
                    SystemHealthPage {
                        adapter: systemHealth
                        tokens: workspace.designSystem
                        leaveFocusTarget: systemHealthRouteNavigation
                    }
                }
            }
        }
    }
}
