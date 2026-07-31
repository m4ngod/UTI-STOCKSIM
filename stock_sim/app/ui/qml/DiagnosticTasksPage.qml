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

                    Button {
                        id: createButton
                        objectName: "createDiagnosticTaskButton"
                        text: "Create Diagnostic Task"
                        enabled: adapter.canCreate
                        focusPolicy: Qt.StrongFocus
                        Accessible.name: text
                        Accessible.description: "Create one durable task from the authoritative baseline and required strategies"
                        onClicked: adapter.createTask()
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

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: tokens.spaceSm

                        Button {
                            id: reviseButton
                            objectName: "reviseDiagnosticTaskButton"
                            text: "Correct Configuration"
                            enabled: adapter.canRevise
                            focusPolicy: Qt.StrongFocus
                            Accessible.name: text
                            Accessible.description: "Replace the current task revision with all displayed authoritative typed inputs"
                            onClicked: adapter.reviseTask()
                        }

                        Button {
                            id: validateButton
                            objectName: "validateDiagnosticTaskButton"
                            text: "Validate Configuration"
                            enabled: adapter.canValidate
                            focusPolicy: Qt.StrongFocus
                            Accessible.name: text
                            Accessible.description: "Validate the exact durable task revision"
                            onClicked: adapter.validateTask()
                        }
                    }

                    TextField {
                        id: approvalActor
                        objectName: "diagnosticTaskApprovalActorInput"
                        Layout.fillWidth: true
                        placeholderText: "Approval actor identity"
                        selectByMouse: true
                        focusPolicy: Qt.StrongFocus
                        Accessible.name: "Approval actor identity"
                        Accessible.description: "Identity recorded on the exact-revision Diagnostic Task approval"
                    }

                    Button {
                        id: approveButton
                        objectName: "approveDiagnosticTaskButton"
                        text: "Approve Configuration"
                        enabled: adapter.canApprove && approvalActor.text.trim().length > 0
                        focusPolicy: Qt.StrongFocus
                        Accessible.name: text
                        Accessible.description: "Approve only the exact successfully validated task revision"
                        onClicked: adapter.approveTask(approvalActor.text)
                    }

                    Button {
                        id: startCampaignButton
                        objectName: "startDiagnosticCampaignButton"
                        text: "Start Formal Diagnostic Campaign"
                        enabled: adapter.canStartCampaign
                        focusPolicy: Qt.StrongFocus
                        Accessible.name: text
                        Accessible.description: "Start the exact approved task revision and hand its real Campaign and Run identities to Run Monitoring"
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

            Text {
                Layout.fillWidth: true
                text: "Campaign lifecycle and failed-node retry commands remain explicitly unavailable."
                color: tokens.textQuiet
                font.pixelSize: tokens.labelSize
                horizontalAlignment: Text.AlignRight
                wrapMode: Text.WordWrap
            }
        }
    }
}
