import QtQuick 2.15
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

            Text {
                Layout.fillWidth: true
                text: "Create, validate, approve, launch, lifecycle, and retry commands are explicitly unavailable in this baseline."
                color: tokens.textQuiet
                font.pixelSize: tokens.labelSize
                horizontalAlignment: Text.AlignRight
                wrapMode: Text.WordWrap
            }
        }
    }
}
