import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: page

    property var adapter
    property var tokens
    property bool hasEvidence: adapter !== null && adapter.hasReliableData

    function focusViewport() {
        if (adapter.viewportIntent === "overview") {
            evidenceScroll.contentY = 0
            return
        }
        var targetY = comparisonSurface.y
        if (adapter.viewportIntent === "sensitivity")
            targetY = evidenceGrid.y
        else if (adapter.viewportIntent === "compound_stress")
            targetY = detailTabs.y
        var maximum = Math.max(
            0,
            evidenceScroll.contentHeight - evidenceScroll.height
        )
        evidenceScroll.contentY = Math.max(0, Math.min(targetY, maximum))
    }

    Connections {
        target: adapter
        function onLocalStateChanged() {
            page.focusViewport()
        }
    }

    Flickable {
        id: evidenceScroll
        objectName: "evidenceResearchFlickable"
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: researchSheet.implicitHeight + tokens.spaceXl * 2

        ColumnLayout {
            id: researchSheet
            width: parent.width - tokens.spaceXl * 2
            x: tokens.spaceXl
            y: tokens.spaceLg
            spacing: tokens.spaceLg

            RowLayout {
                Layout.fillWidth: true

                ColumnLayout {
                    spacing: tokens.spaceXs

                    Text {
                        text: "EVIDENCE & FINDINGS"
                        color: tokens.accent
                        font.pixelSize: tokens.labelSize
                        font.bold: true
                    }
                    Text {
                        text: "Compare evidence, inspect failure reasons, and trace every conclusion."
                        color: tokens.textMuted
                        font.pixelSize: tokens.bodySize
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
                Layout.fillWidth: true
                Layout.preferredHeight: 132
                radius: tokens.radiusMd
                color: tokens.surface
                border.color: tokens.border

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: tokens.spaceLg
                    spacing: tokens.spaceXl

                    ColumnLayout {
                        Layout.preferredWidth: 420
                        spacing: tokens.spaceXs

                        Text {
                            text: adapter.presentationState === "loading"
                                ? "Preparing evidence"
                                : adapter.presentationState === "empty"
                                    ? "No research run selected"
                                    : adapter.presentationState === "disconnected"
                                        ? "Evidence source disconnected"
                                        : adapter.presentationState === "failed"
                                            ? "Evidence processing failed"
                                            : "Research evidence available"
                            color: tokens.textPrimary
                            font.pixelSize: tokens.titleSize
                            font.bold: true
                        }
                        Text {
                            Layout.fillWidth: true
                            text: adapter.statusText
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WordWrap
                        }
                    }

                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.fillHeight: true
                        color: tokens.border
                    }

                    Text {
                        Layout.fillWidth: true
                        text: adapter.pinnedIdentitiesText
                        color: tokens.textMuted
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WordWrap
                    }
                }
            }

            ColumnLayout {
                visible: page.hasEvidence
                Layout.fillWidth: true
                spacing: tokens.spaceLg

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: tokens.spaceXs

                    Text {
                        text: "FORMAL COVERAGE"
                        color: tokens.accent
                        font.pixelSize: tokens.labelSize
                        font.bold: true
                    }
                    Text {
                        Layout.fillWidth: true
                        text: adapter.coverageText
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WordWrap
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: tokens.spaceSm

                    Text {
                        text: "CANDIDATES"
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                        font.bold: true
                    }

                    Repeater {
                        objectName: "evidenceCandidateRepeater"
                        model: adapter.candidateIdentities

                        delegate: ResearchChoice {
                            property string choiceValue: String(modelData)
                            objectName: "evidenceCandidate-" + choiceValue
                            tokens: page.tokens
                            text: choiceValue
                            selected: adapter.selectedCandidateIdentity === choiceValue
                            accessibleName: "Select candidate " + choiceValue
                            onInvoked: adapter.selectCandidate(choiceValue)
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: adapter.candidateSummaryText
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                        horizontalAlignment: Text.AlignRight
                        wrapMode: Text.WordWrap
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: tokens.spaceSm

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: tokens.spaceSm

                        Text {
                            text: "LOCAL VIEW"
                            color: tokens.textQuiet
                            font.pixelSize: tokens.labelSize
                            font.bold: true
                        }

                        ResearchChoice {
                            objectName: "evidenceFilterRisk"
                            tokens: page.tokens
                            text: "Filter · Risk"
                            selected: adapter.evidenceFilter === "risk"
                            accessibleName: "Filter evidence by risk"
                            onInvoked: adapter.setEvidenceFilter("risk")
                        }

                        ResearchChoice {
                            objectName: "evidenceSortCoverage"
                            tokens: page.tokens
                            text: "Sort · Coverage"
                            selected: adapter.sortOrder === "coverage"
                            accessibleName: "Sort evidence by coverage"
                            onInvoked: adapter.setSortOrder("coverage")
                        }

                        ResearchChoice {
                            objectName: "evidenceViewportCompound"
                            tokens: page.tokens
                            text: "Viewport · Compound"
                            selected: adapter.viewportIntent === "compound_stress"
                            accessibleName: "Focus compound stress evidence"
                            onInvoked: adapter.setViewportIntent("compound_stress")
                        }

                        Item { Layout.fillWidth: true }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: tokens.spaceSm

                        Text {
                            text: "DETAIL"
                            color: tokens.textQuiet
                            font.pixelSize: tokens.labelSize
                            font.bold: true
                        }

                        Repeater {
                            objectName: "evidenceTabRepeater"
                            model: [
                                "findings",
                                "assumptions",
                                "provenance",
                                "context"
                            ]

                            delegate: ResearchChoice {
                                property string choiceValue: String(modelData)
                                objectName: "evidenceTab"
                                    + choiceValue.charAt(0).toUpperCase()
                                    + choiceValue.slice(1)
                                tokens: page.tokens
                                text: "Tab · " + choiceValue
                                selected: adapter.activeTab === choiceValue
                                accessibleName: "Show " + choiceValue + " tab"
                                onInvoked: adapter.setActiveTab(choiceValue)
                            }
                        }

                        Item { Layout.fillWidth: true }
                    }
                }

                Rectangle {
                    id: comparisonSurface
                    Layout.fillWidth: true
                    Layout.preferredHeight: comparisonText.implicitHeight
                        + tokens.spaceLg * 2
                    radius: tokens.radiusMd
                    color: tokens.surfaceRaised
                    border.color: tokens.border

                    Text {
                        id: comparisonText
                        anchors.fill: parent
                        anchors.margins: tokens.spaceLg
                        text: adapter.comparisonText
                        color: tokens.textPrimary
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WordWrap
                    }
                }

                Rectangle {
                    id: evidenceChartSurface
                    objectName: "evidenceChartSurface"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 424
                    radius: tokens.radiusMd
                    color: tokens.surfaceRaised
                    border.color: tokens.border

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: tokens.spaceLg
                        spacing: tokens.spaceSm

                        RowLayout {
                            Layout.fillWidth: true

                            Text {
                                text: "DIAGNOSTIC EVIDENCE PATH"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }

                            Item { Layout.fillWidth: true }

                            Text {
                                text: adapter.chartAcceptedRevisionText
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                            }
                        }

                        Item {
                            id: evidenceChartMount
                            objectName: "evidenceChartMount"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true

                            Rectangle {
                                anchors.fill: parent
                                radius: tokens.radiusSm
                                color: tokens.surface
                                border.color: tokens.border
                            }

                            EvidenceChart {
                                id: productionEvidenceChart
                                anchors.fill: parent
                                anchors.margins: 8
                                normalizedPoints: adapter.chartNormalizedPoints
                                overlayModels: adapter.chartOverlayModels
                                selectedPointX: adapter.selectedChartPointX
                                selectedPointY: adapter.selectedChartPointY
                                acceptedRevision: adapter.chartAcceptedRevision
                                samplePointCount: adapter.chartVisiblePointCount
                                overlayCount: adapter.chartOverlayCount
                                selectedPointSourceIndex: (
                                    adapter.selectedChartPointIndex
                                )
                                selectedOverlayIdentity: (
                                    adapter.selectedChartOverlayIdentity
                                )
                                selectedFindingIdentity: (
                                    adapter.selectedChartFindingIdentity
                                )
                                selectedBreakpointIdentity: (
                                    adapter.selectedChartBreakpointIdentity
                                )
                                frameSequence: adapter.chartFrameSequence
                                interactionEnabled: (
                                    adapter.chartInteractionEnabled
                                )
                                seriesColor: tokens.focus
                                overlayColor: tokens.textQuiet
                                selectedColor: tokens.accent
                                pointColor: tokens.textPrimary
                                pointBorderColor: tokens.surface
                                focusColor: tokens.focus
                                labelPixelSize: tokens.labelSize
                                accessibleDescription: adapter.chartAccessibleText
                                onPointSelected: function(ratio) {
                                    adapter.selectChartPointAtRatio(ratio)
                                }
                                onPointStepRequested: function(direction) {
                                    adapter.stepChartPoint(direction)
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: adapter.chartSourceIdentity
                                + " · " + adapter.chartSourcePointCount
                                + " source · " + adapter.chartVisiblePointCount
                                + " visible · " + adapter.chartOverlayCount
                                + " overlays · " + adapter.chartSamplingPolicy
                            color: tokens.textQuiet
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WordWrap
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: tokens.spaceSm

                            Text {
                                text: "OVERLAYS"
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }

                            Repeater {
                                objectName: "evidenceChartOverlayRepeater"
                                model: adapter.chartOverlayIdentities

                                delegate: ResearchChoice {
                                    property string choiceValue: String(modelData)
                                    tokens: page.tokens
                                    enabled: adapter.chartInteractionEnabled
                                    text: choiceValue
                                    selected: adapter.selectedChartOverlayIdentity
                                        === choiceValue
                                    accessibleName: "Select chart overlay "
                                        + choiceValue
                                    onInvoked: adapter.selectChartOverlay(
                                        choiceValue
                                    )
                                }
                            }

                            Item { Layout.fillWidth: true }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: tokens.spaceSm

                            Text {
                                text: "SENSITIVITY BREAKPOINTS"
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }

                            Repeater {
                                objectName: "evidenceChartBreakpointRepeater"
                                model: adapter.chartBreakpointIdentities

                                delegate: ResearchChoice {
                                    property string choiceValue: String(modelData)
                                    tokens: page.tokens
                                    enabled: adapter.chartInteractionEnabled
                                    text: choiceValue
                                    selected: (
                                        adapter.selectedChartBreakpointIdentity
                                        === choiceValue
                                    )
                                    accessibleName: (
                                        "Select Sensitivity Breakpoint "
                                        + choiceValue
                                    )
                                    onInvoked: adapter.selectChartBreakpoint(
                                        choiceValue
                                    )
                                }
                            }

                            Item { Layout.fillWidth: true }
                        }
                    }
                }

                GridLayout {
                    id: evidenceGrid
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: tokens.spaceXl
                    rowSpacing: tokens.spaceLg

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        spacing: tokens.spaceXs

                        Text {
                            text: "MULTIDIMENSIONAL EVIDENCE"
                            color: tokens.accent
                            font.pixelSize: tokens.labelSize
                            font.bold: true
                        }
                        Text {
                            Layout.fillWidth: true
                            text: adapter.chartTableText
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WordWrap
                        }
                    }

                    ColumnLayout {
                        objectName: "evidenceFindingsPanel"
                        visible: adapter.activeTab === "findings"
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        spacing: tokens.spaceXs

                        Text {
                            text: "FINDING & FAILURE REASON"
                            color: tokens.accent
                            font.pixelSize: tokens.labelSize
                            font.bold: true
                        }

                        RowLayout {
                            spacing: tokens.spaceSm

                            Repeater {
                                objectName: "evidenceFindingRepeater"
                                model: adapter.findingIdentities

                                delegate: ResearchChoice {
                                    property string choiceValue: String(modelData)
                                    objectName: "evidenceFinding-" + choiceValue
                                    tokens: page.tokens
                                    text: choiceValue
                                    selected: adapter.selectedFindingIdentity === choiceValue
                                    accessibleName: "Select finding " + choiceValue
                                    onInvoked: adapter.selectFinding(choiceValue)
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: adapter.chartNarrativeText
                            color: tokens.textPrimary
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            Layout.fillWidth: true
                            text: adapter.breakpointsText
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: tokens.border
                }

                ColumnLayout {
                    id: detailTabs
                    Layout.fillWidth: true
                    spacing: tokens.spaceSm

                    ColumnLayout {
                        objectName: "evidenceAssumptionsPanel"
                        visible: adapter.activeTab === "assumptions"
                        Layout.fillWidth: true

                        Text {
                            text: "REQUESTED / EFFECTIVE ASSUMPTIONS"
                            color: tokens.accent
                            font.pixelSize: tokens.labelSize
                            font.bold: true
                        }
                        Text {
                            Layout.fillWidth: true
                            text: adapter.assumptionsText
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WordWrap
                        }
                    }

                    ColumnLayout {
                        objectName: "evidenceProvenancePanel"
                        visible: adapter.activeTab === "provenance"
                        Layout.fillWidth: true

                        Text {
                            text: "REPRODUCTION PROVENANCE"
                            color: tokens.accent
                            font.pixelSize: tokens.labelSize
                            font.bold: true
                        }
                        Text {
                            Layout.fillWidth: true
                            text: adapter.provenanceText
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WordWrap
                        }
                    }

                    ColumnLayout {
                        objectName: "evidenceContextPanel"
                        visible: adapter.activeTab === "context"
                        Layout.fillWidth: true

                        Text {
                            text: "READ-ONLY DIAGNOSTIC CONTEXT"
                            color: tokens.accent
                            font.pixelSize: tokens.labelSize
                            font.bold: true
                        }
                        Text {
                            Layout.fillWidth: true
                            text: adapter.readOnlyContextText
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "This route is evidence-only: it has no experiment launch or manual trading controls."
                color: tokens.textQuiet
                font.pixelSize: tokens.labelSize
                horizontalAlignment: Text.AlignRight
            }
        }
    }
}
