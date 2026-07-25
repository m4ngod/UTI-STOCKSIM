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
            : "No Strategy Run selected"
    property string detail: screenState === "loading"
        ? "Waiting for the first immutable Run Monitoring state."
        : screenState === "disconnected"
            ? "Runtime data is unavailable. No Strategy Run state is being inferred."
            : "Open an existing Formal Diagnostic Campaign or Strategy Run to monitor it here."

    DesignTokens {
        id: tokens
        objectName: "designTokens"
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
                    Layout.preferredHeight: 250
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
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                            }
                            Text {
                                text: "Source · " + runMonitoring.sourceIdentity
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
