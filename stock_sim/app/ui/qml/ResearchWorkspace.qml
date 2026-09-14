import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: workspace
    objectName: "researchWorkspace"
    color: tokens.background
    property string activeRoute: initialJourneyRoute
    property string routeRecoveryReason: initialJourneyRecoveryReason
    property string routeRecoveryMessage: initialJourneyRecoveryMessage
    property string requestedFocusRoute: initialJourneyFocusRoute
    property string requestedFocusControl: initialJourneyFocusControl
    property string requestedFocusIdentity: initialJourneyFocusIdentity
    property bool focusReturnConsumed: false
    property string authoritativeFocusPendingRoute: ""
    readonly property var designSystem: tokens
    readonly property var strategyLibraryInitialFocusItem: combinationNavigation
    readonly property var scenarioLabInitialFocusItem: scenarioNavigation
    readonly property var diagnosticTasksInitialFocusItem: labNavigation
    readonly property var runMonitoringInitialFocusItem: labNavigation
    readonly property var evidenceInitialFocusItem: archiveNavigation
    readonly property var systemHealthInitialFocusItem: healthButton
    signal routeActivationRequested(string route)
    signal healthOverlayRequested()
    onHealthOverlayRequested: healthPopup.open()

    DesignTokens { id: tokens; objectName: "designTokens" }

    ResearchHealthPopup {
        id: healthPopup
        tokens: workspace.designSystem
        adapter: systemHealth
        returnFocusItem: healthButton
    }

    component NavigationButton: Button {
        property string route
        property bool primaryDestination: true
        property bool selected: workspace.activeRoute === route
        Layout.fillWidth: true
        implicitHeight: Math.max(44, contentItem.implicitHeight + tokens.spaceSm * 2)
        font.pixelSize: tokens.bodySize
        Accessible.name: text
        Accessible.role: Accessible.PageTab
        Accessible.selected: selected
        onClicked: workspace.routeActivationRequested(route)
        contentItem: Text {
            text: parent.text
            color: parent.selected ? tokens.accent : tokens.textPrimary
            font: parent.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            color: parent.down ? tokens.surfaceRaised : "transparent"
            border.width: parent.activeFocus ? tokens.focusWidth : 0
            border.color: tokens.focus
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width; height: 2
                color: tokens.accent
                visible: parent.parent.selected
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: tokens.spaceMd
        spacing: tokens.spaceSm
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "UTI / STOCKSIM"
                color: tokens.textPrimary
                font.pixelSize: tokens.bodySize
                font.bold: true
            }
            Item { Layout.fillWidth: true }
            DiagnosticCommandButton {
                id: healthButton
                objectName: "researchHealthButton"
                tokens: workspace.designSystem
                text: "系统状态 · " + (systemHealth === null ? "未知" : systemHealth.overallClassification)
                Accessible.name: "只读系统状态。" + (systemHealth === null
                    ? "尚无系统状态观察" : systemHealth.statusText)
                accessibleDescription: "打开只读系统详情，不暂停实验或改变当前观察对象。"
                onInvoked: healthPopup.open()
            }
        }
        RowLayout {
            objectName: "researchPrimaryNavigation"
            Layout.fillWidth: true
            spacing: tokens.spaceSm
            NavigationButton {
                id: combinationNavigation
                objectName: "strategyLibraryRouteNavigation"
                text: "组合库"; route: "strategy_library"
                KeyNavigation.right: scenarioNavigation
            }
            NavigationButton {
                id: scenarioNavigation
                objectName: "scenarioLabRouteNavigation"
                text: "场景库"; route: "scenario_lab"
                KeyNavigation.left: combinationNavigation
                KeyNavigation.right: labNavigation
            }
            NavigationButton {
                id: labNavigation
                objectName: "diagnosticTasksRouteNavigation"
                text: "实验室"; route: "diagnostic_tasks"
                selected: workspace.activeRoute === "diagnostic_tasks" || workspace.activeRoute === "run_monitoring"
                KeyNavigation.left: scenarioNavigation
                KeyNavigation.right: archiveNavigation
            }
            NavigationButton {
                id: archiveNavigation
                objectName: "evidenceAndFindingsRouteNavigation"
                text: "实验档案"; route: "evidence_and_findings"
                KeyNavigation.left: labNavigation
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: tokens.border }
        Text {
            Layout.fillWidth: true
            visible: workspace.routeRecoveryReason !== "exact"
            text: workspace.routeRecoveryMessage
            wrapMode: Text.WrapAnywhere
            color: tokens.textPrimary
            font.pixelSize: tokens.bodySize
            Accessible.role: Accessible.StatusBar
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: workspace.activeRoute === "run_monitoring"
            contentWidth: availableWidth
            TextArea {
                objectName: "researchExistingResourceSummary"
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.WrapAnywhere
                color: tokens.textPrimary
                font.pixelSize: tokens.bodySize
                Accessible.name: "当前兼容资源状态"
                text: workspace.activeRoute === "strategy_library"
                    ? (strategyLibrary === null ? "组合库资源不可用" : strategyLibrary.statusMessage)
                    : workspace.activeRoute === "scenario_lab"
                    ? (scenarioLab === null ? "场景库资源不可用" : scenarioLab.statusMessage)
                    : workspace.activeRoute === "evidence_and_findings"
                    ? (evidenceAndFindings === null ? "实验档案资源不可用" : evidenceAndFindings.statusText)
                    : workspace.activeRoute === "run_monitoring"
                    ? (runMonitoring === null ? "运行详情资源不可用"
                        : "运行详情 · 旧运行兼容视图\n"
                        + "Campaign: " + runMonitoring.campaignIdentity
                        + "\nRun: " + (runMonitoring.runIdentity || "未选择运行")
                        + "\n" + runMonitoring.statusText
                        + "\n生命周期: " + runMonitoring.lifecycle
                        + "\n进度: " + runMonitoring.progressText)
                    : (diagnosticTasks === null ? "实验室资源不可用" : diagnosticTasks.statusText)
                background: Rectangle { color: tokens.background }
            }
        }
        ResearchAssetPage {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: workspace.activeRoute === "strategy_library"
            adapter: strategyAssetQueries
            tokens: workspace.designSystem
        }
        ResearchScenarioPage {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: workspace.activeRoute === "scenario_lab"
            adapter: scenarioLab
            tokens: workspace.designSystem
        }
        ResearchLabPage {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: workspace.activeRoute === "diagnostic_tasks"
            adapter: diagnosticTasks
            tokens: workspace.designSystem
        }
        ResearchArchivePage {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: workspace.activeRoute === "evidence_and_findings"
            adapter: evidenceAndFindings
            tokens: workspace.designSystem
        }
    }
}
