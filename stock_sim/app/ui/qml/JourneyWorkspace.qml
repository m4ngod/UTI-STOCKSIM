import QtQuick 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: workspace
    objectName: "journeyWorkspace"
    color: tokens.background

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

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: 220
            Layout.fillHeight: true
            color: tokens.rail

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: tokens.spaceLg
                spacing: tokens.spaceLg

                ColumnLayout {
                    spacing: tokens.spaceXs

                    Text {
                        text: "UTI"
                        color: tokens.accent
                        font.pixelSize: 18
                        font.bold: true
                    }
                    Text {
                        text: "Strategy Diagnostics"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                    }
                    Text {
                        text: "Research workspace"
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    radius: tokens.radiusSm
                    color: tokens.surfaceRaised
                    border.color: tokens.accent

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: tokens.spaceMd
                        verticalAlignment: Text.AlignVCenter
                        text: "Run Monitoring"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
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

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: tokens.spaceXl
                spacing: tokens.spaceLg

                RowLayout {
                    Layout.fillWidth: true

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
                            text: "Observe a Strategy Run without entering a trading workspace."
                            color: tokens.textMuted
                            font.pixelSize: tokens.bodySize
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
                    Layout.fillWidth: true
                    Layout.preferredHeight: 214
                    radius: tokens.radiusMd
                    color: tokens.surface
                    border.color: tokens.border

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: tokens.spaceXl
                        spacing: tokens.spaceMd

                        Rectangle {
                            Layout.preferredWidth: 92
                            Layout.preferredHeight: 28
                            radius: tokens.radiusSm
                            color: tokens.surfaceRaised
                            border.color: tokens.border

                            Text {
                                anchors.centerIn: parent
                                text: workspace.screenState.toUpperCase()
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                        }

                        Text {
                            objectName: "runMonitoringHeadline"
                            text: workspace.headline
                            color: tokens.textPrimary
                            font.pixelSize: tokens.titleSize
                            font.bold: true
                        }

                        Text {
                            objectName: "runMonitoringDetail"
                            Layout.fillWidth: true
                            text: workspace.detail
                            color: tokens.textMuted
                            font.pixelSize: tokens.bodySize
                            wrapMode: Text.WordWrap
                        }

                        Item {
                            Layout.fillHeight: true
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: tokens.spaceLg

                            Text {
                                text: "Freshness · " + runMonitoring.freshness
                                    + " · age " + runMonitoring.ageText
                                    + " / " + runMonitoring.freshnessThresholdText
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                            }
                            Text {
                                text: "Source · " + runMonitoring.sourceIdentity
                                    + " · " + runMonitoring.sourceGenerationText
                                    + " · " + runMonitoring.mountGenerationText
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Observed · " + runMonitoring.observedAtText
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                horizontalAlignment: Text.AlignRight
                            }
                        }
                    }
                }

                GridLayout {
                    visible: workspace.screenState === "active"
                        || workspace.screenState === "terminal"
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: tokens.spaceMd
                    rowSpacing: tokens.spaceMd

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 150
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
                                text: "Campaign · " + runMonitoring.campaignIdentity
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                            }
                            Text {
                                text: "Run · " + runMonitoring.runIdentity
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                            }
                            Text {
                                text: "Strategy Under Test · " + runMonitoring.strategyIdentity
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                            }
                            Text {
                                text: "Market Scenario · " + runMonitoring.marketScenarioIdentity
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                            }
                            Text {
                                text: "Scenario-set · " + runMonitoring.scenarioSetIdentity
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                            }
                            Text {
                                text: "Reproduction Manifest · " + runMonitoring.reproductionManifestIdentity
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 150
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border

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
                                text: "Lifecycle · " + runMonitoring.lifecycle
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                            }
                            Text {
                                text: "Current node · " + runMonitoring.currentNodeText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                            }
                            Text {
                                text: "Progress · " + runMonitoring.progressText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                            }
                            Text {
                                text: "Simulation Time · " + runMonitoring.simulationTimeText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                            }
                            Text {
                                text: "Wall Time · " + runMonitoring.wallTimeText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 132
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
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: runMonitoring.alertsText
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 132
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
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }

                ColumnLayout {
                    visible: workspace.screenState === "active"
                        || workspace.screenState === "terminal"
                    Layout.fillWidth: true
                    spacing: tokens.spaceXs

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: tokens.spaceSm

                        DiagnosticCommandButton {
                            id: pauseDiagnosticTask
                            objectName: "pauseDiagnosticTask"
                            text: "Pause diagnostic task"
                            Layout.preferredWidth: 154
                            Layout.preferredHeight: 38
                            enabled: runMonitoring.canPause
                            radius: tokens.radiusSm
                            color: tokens.surfaceRaised
                            enabledTextColor: tokens.textPrimary
                            disabledTextColor: tokens.textQuiet
                            standardBorderColor: tokens.border
                            focusColor: tokens.focus
                            focusBorderWidth: tokens.focusWidth
                            labelSize: tokens.labelSize
                            pressDuration: tokens.durationForMotion
                            onInvoked: runMonitoring.pauseDiagnosticTask()
                        }

                        DiagnosticCommandButton {
                            id: resumeDiagnosticTask
                            objectName: "resumeDiagnosticTask"
                            text: "Resume diagnostic task"
                            Layout.preferredWidth: 164
                            Layout.preferredHeight: 38
                            enabled: runMonitoring.canResume
                            radius: tokens.radiusSm
                            color: tokens.surfaceRaised
                            enabledTextColor: tokens.textPrimary
                            disabledTextColor: tokens.textQuiet
                            standardBorderColor: tokens.border
                            focusColor: tokens.focus
                            focusBorderWidth: tokens.focusWidth
                            labelSize: tokens.labelSize
                            pressDuration: tokens.durationForMotion
                            onInvoked: runMonitoring.resumeDiagnosticTask()
                        }

                        DiagnosticCommandButton {
                            id: cancelDiagnosticTask
                            objectName: "cancelDiagnosticTask"
                            text: "Cancel diagnostic task"
                            Layout.preferredWidth: 164
                            Layout.preferredHeight: 38
                            enabled: runMonitoring.canCancel
                            radius: tokens.radiusSm
                            color: tokens.surfaceRaised
                            enabledTextColor: tokens.textPrimary
                            disabledTextColor: tokens.textQuiet
                            standardBorderColor: tokens.border
                            focusColor: tokens.focus
                            focusBorderWidth: tokens.focusWidth
                            labelSize: tokens.labelSize
                            pressDuration: tokens.durationForMotion
                            onInvoked: runMonitoring.cancelDiagnosticTask()
                        }

                    }

                    Text {
                        objectName: "diagnosticCommandFeedback"
                        Layout.fillWidth: true
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
                        wrapMode: Text.WordWrap
                        Accessible.name: text
                    }
                }

                Item {
                    Layout.fillHeight: true
                }

                Text {
                    Layout.fillWidth: true
                    text: "No experiment launch or discretionary trading controls are available in this workspace."
                    color: tokens.textQuiet
                    font.pixelSize: tokens.labelSize
                    horizontalAlignment: Text.AlignRight
                }
            }
        }
    }
}
