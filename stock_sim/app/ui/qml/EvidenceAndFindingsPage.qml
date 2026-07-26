import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: page

    property var adapter
    property var tokens
    property bool hasEvidence: adapter !== null && adapter.hasReliableData
    property var lastFocusedItem: null
    readonly property bool hasMeaningfulFocus: (
        lastFocusedItem !== null
        && lastFocusedItem.activeFocus
        && lastFocusedItem.visible
        && lastFocusedItem.enabled
    )
    readonly property var firstCandidateControl: candidateRepeater.count > 0
        ? candidateRepeater.itemAt(0)
        : null
    readonly property var secondCandidateControl: candidateRepeater.count > 1
        ? candidateRepeater.itemAt(1)
        : null
    readonly property var firstFindingControl: findingRepeater.count > 0
        ? findingRepeater.itemAt(0)
        : null
    readonly property var secondFindingControl: findingRepeater.count > 1
        ? findingRepeater.itemAt(1)
        : null

    function ensureItemVisible(item) {
        if (item === null || !evidenceScroll.visible)
            return
        var point = item.mapToItem(evidenceScroll.contentItem, 0, 0)
        var top = point.y - tokens.spaceMd
        var bottom = point.y + item.height + tokens.spaceMd
        if (top < evidenceScroll.contentY)
            evidenceScroll.contentY = Math.max(0, top)
        else if (bottom > evidenceScroll.contentY + evidenceScroll.height)
            evidenceScroll.contentY = Math.min(
                evidenceScroll.contentHeight - evidenceScroll.height,
                bottom - evidenceScroll.height
            )
    }

    function rememberFocus(item) {
        lastFocusedItem = item
        ensureItemVisible(item)
    }

    function restoreFocus() {
        var target = lastFocusedItem
        if (target === null || !target.visible || !target.enabled)
            target = candidateRepeater.count > 0
                ? candidateRepeater.itemAt(0)
                : null
        if (target !== null) {
            target.forceActiveFocus()
            ensureItemVisible(target)
        }
    }

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
            if (page.lastFocusedItem !== null)
                page.ensureItemVisible(page.lastFocusedItem)
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
            width: Math.max(0, parent.width - tokens.spaceXl * 2)
            implicitWidth: width
            x: tokens.spaceXl
            y: tokens.spaceLg
            spacing: tokens.spaceLg

            RowLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.maximumWidth: researchSheet.width

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: tokens.spaceXs

                    Text {
                        text: "EVIDENCE & FINDINGS"
                        color: tokens.accent
                        font.pixelSize: tokens.labelSize
                        font.bold: true
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Compare evidence, inspect failure reasons, and trace every conclusion."
                        color: tokens.textMuted
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WrapAnywhere
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
                id: evidenceAccessibleStatus
                objectName: "evidenceAccessibleStatus"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.maximumWidth: researchSheet.width
                Layout.preferredHeight: Math.max(
                    132,
                    tokens.textScale >= 1.75
                        ? 430
                        : tokens.titleSize + tokens.labelSize * 7
                            + tokens.spaceLg * 2
                )
                radius: tokens.radiusMd
                color: tokens.surface
                border.color: tokens.border
                Accessible.role: Accessible.StatusBar
                Accessible.name: "Evidence and Findings "
                    + adapter.presentationState
                Accessible.description: adapter.statusText + ". "
                    + adapter.pinnedIdentitiesText

                GridLayout {
                    anchors.fill: parent
                    anchors.margins: tokens.spaceLg
                    columns: tokens.textScale >= 1.75 ? 1 : 3
                    columnSpacing: tokens.spaceXl
                    rowSpacing: tokens.spaceMd

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: tokens.textScale >= 1.75
                            ? -1
                            : 420
                        spacing: tokens.spaceXs

                        Text {
                            Layout.fillWidth: true
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
                            wrapMode: Text.WrapAnywhere
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
                        visible: tokens.textScale < 1.75
                        Layout.preferredWidth: 1
                        Layout.fillHeight: true
                        color: tokens.border
                    }

                    Text {
                        Layout.fillWidth: true
                        text: adapter.pinnedIdentitiesText
                        color: tokens.textMuted
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }

            ColumnLayout {
                visible: page.hasEvidence
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.maximumWidth: researchSheet.width
                spacing: tokens.spaceLg

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
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
                        wrapMode: Text.WrapAnywhere
                    }
                }

                GridLayout {
                    objectName: "evidenceCandidateControlsGrid"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
                    columns: tokens.textScale >= 1.75 ? 1 : 4
                    columnSpacing: tokens.spaceSm
                    rowSpacing: tokens.spaceXs

                    Text {
                        text: "CANDIDATES"
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                        font.bold: true
                    }

                    Repeater {
                        id: candidateRepeater
                        objectName: "evidenceCandidateRepeater"
                        model: adapter.candidateIdentities

                        delegate: ResearchChoice {
                            property string choiceValue: String(modelData)
                            objectName: "evidenceCandidate-" + choiceValue
                            tokens: page.tokens
                            text: choiceValue
                            selected: adapter.selectedCandidateIdentity === choiceValue
                            accessibleName: "Select candidate " + choiceValue
                            onFocusEntered: page.rememberFocus(item)
                            onInvoked: adapter.selectCandidate(choiceValue)
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: adapter.candidateSummaryText
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                        horizontalAlignment: tokens.textScale >= 1.75
                            ? Text.AlignLeft
                            : Text.AlignRight
                        wrapMode: Text.WrapAnywhere
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
                    spacing: tokens.spaceSm

                    GridLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: parent.width
                        columns: tokens.textScale >= 1.75 ? 1 : 5
                        columnSpacing: tokens.spaceSm
                        rowSpacing: tokens.spaceXs

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
                            onFocusEntered: page.rememberFocus(item)
                            onInvoked: adapter.setEvidenceFilter("risk")
                        }

                        ResearchChoice {
                            objectName: "evidenceSortCoverage"
                            tokens: page.tokens
                            text: "Sort · Coverage"
                            selected: adapter.sortOrder === "coverage"
                            accessibleName: "Sort evidence by coverage"
                            onFocusEntered: page.rememberFocus(item)
                            onInvoked: adapter.setSortOrder("coverage")
                        }

                        ResearchChoice {
                            objectName: "evidenceViewportCompound"
                            tokens: page.tokens
                            text: "Viewport · Compound"
                            selected: adapter.viewportIntent === "compound_stress"
                            accessibleName: "Focus compound stress evidence"
                            onFocusEntered: page.rememberFocus(item)
                            onInvoked: adapter.setViewportIntent("compound_stress")
                        }

                        Item {
                            visible: tokens.textScale < 1.75
                            Layout.fillWidth: true
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: parent.width
                        columns: tokens.textScale >= 1.75 ? 1 : 6
                        columnSpacing: tokens.spaceSm
                        rowSpacing: tokens.spaceXs

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
                                onFocusEntered: page.rememberFocus(item)
                                onInvoked: adapter.setActiveTab(choiceValue)
                            }
                        }

                        Item {
                            visible: tokens.textScale < 1.75
                            Layout.fillWidth: true
                        }
                    }
                }

                Rectangle {
                    id: comparisonSurface
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
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
                        wrapMode: Text.WrapAnywhere
                    }
                }

                Rectangle {
                    id: evidenceChartSurface
                    objectName: "evidenceChartSurface"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
                    Layout.preferredHeight: Math.max(
                        424,
                        tokens.textScale >= 1.75
                            ? 1000
                            : 300 + tokens.labelSize * 7
                    )
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
                                onFocusEntered: page.rememberFocus(item)
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
                            Layout.minimumWidth: 0
                            text: adapter.chartSourceIdentity
                                + " · " + adapter.chartSourcePointCount
                                + " source · " + adapter.chartVisiblePointCount
                                + " visible · " + adapter.chartOverlayCount
                                + " overlays · " + adapter.chartSamplingPolicy
                            color: tokens.textQuiet
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.maximumWidth: parent.width
                            columns: tokens.textScale >= 1.75 ? 1 : 5
                            columnSpacing: tokens.spaceSm
                            rowSpacing: tokens.spaceXs

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
                                    onFocusEntered: page.rememberFocus(item)
                                    onInvoked: adapter.selectChartOverlay(
                                        choiceValue
                                    )
                                }
                            }

                            Item {
                                visible: tokens.textScale < 1.75
                                Layout.fillWidth: true
                            }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.maximumWidth: parent.width
                            columns: tokens.textScale >= 1.75 ? 1 : 3
                            columnSpacing: tokens.spaceSm
                            rowSpacing: tokens.spaceXs

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
                                    onFocusEntered: page.rememberFocus(item)
                                    onInvoked: adapter.selectChartBreakpoint(
                                        choiceValue
                                    )
                                }
                            }

                            Item {
                                visible: tokens.textScale < 1.75
                                Layout.fillWidth: true
                            }
                        }
                    }
                }

                GridLayout {
                    id: evidenceGrid
                    objectName: "evidenceResearchGrid"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
                    columns: tokens.textScale >= 1.75 ? 1 : 2
                    columnSpacing: tokens.spaceXl
                    rowSpacing: tokens.spaceLg

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: parent.width
                        Layout.alignment: Qt.AlignTop
                        spacing: tokens.spaceXs

                        Text {
                            text: "MULTIDIMENSIONAL EVIDENCE"
                            color: tokens.accent
                            font.pixelSize: tokens.labelSize
                            font.bold: true
                        }
                        Text {
                            objectName: "evidenceChartAccessibleTable"
                            Layout.fillWidth: true
                            text: adapter.chartTableText
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                            Accessible.role: Accessible.StaticText
                            Accessible.name: text
                        }
                    }

                    ColumnLayout {
                        objectName: "evidenceFindingsPanel"
                        visible: adapter.activeTab === "findings"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: parent.width
                        Layout.alignment: Qt.AlignTop
                        spacing: tokens.spaceXs

                        Text {
                            text: "FINDING & FAILURE REASON"
                            color: tokens.accent
                            font.pixelSize: tokens.labelSize
                            font.bold: true
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.maximumWidth: parent.width
                            columns: tokens.textScale >= 1.75 ? 1 : 2
                            columnSpacing: tokens.spaceSm
                            rowSpacing: tokens.spaceXs

                            Repeater {
                                id: findingRepeater
                                objectName: "evidenceFindingRepeater"
                                model: adapter.findingIdentities

                                delegate: ResearchChoice {
                                    property string choiceValue: String(modelData)
                                    objectName: "evidenceFinding-" + choiceValue
                                    tokens: page.tokens
                                    text: choiceValue
                                    selected: adapter.selectedFindingIdentity === choiceValue
                                    accessibleName: "Select finding " + choiceValue
                                    onFocusEntered: page.rememberFocus(item)
                                    onInvoked: adapter.selectFinding(choiceValue)
                                }
                            }
                        }

                        Text {
                            objectName: "evidenceChartAccessibleNarrative"
                            Layout.fillWidth: true
                            text: adapter.chartNarrativeText
                            color: tokens.textPrimary
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                            Accessible.role: Accessible.StaticText
                            Accessible.name: text
                        }
                        Text {
                            Layout.fillWidth: true
                            text: adapter.breakpointsText
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
                    Layout.preferredHeight: 1
                    color: tokens.border
                }

                ColumnLayout {
                    id: detailTabs
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: parent.width
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
                            wrapMode: Text.WrapAnywhere
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
                            wrapMode: Text.WrapAnywhere
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
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.maximumWidth: researchSheet.width
                text: "This route is evidence-only: it has no experiment launch or manual trading controls."
                color: tokens.textQuiet
                font.pixelSize: tokens.labelSize
                horizontalAlignment: Text.AlignRight
                wrapMode: Text.WrapAnywhere
            }
        }
    }
}
