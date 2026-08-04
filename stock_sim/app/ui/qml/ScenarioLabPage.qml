import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: page
    objectName: "scenarioLabPage"

    required property var adapter
    required property var tokens
    property var lastFocusedItem: null
    readonly property var firstActionControl: searchInput
    readonly property bool hasMeaningfulFocus: (
        lastFocusedItem !== null && lastFocusedItem.activeFocus
    )

    function rememberFocus(item) {
        lastFocusedItem = item
    }

    function restoreFocus() {
        var target = lastFocusedItem
        if (target === null || !target.visible || !target.enabled)
            target = searchInput
        target.forceActiveFocus()
        return true
    }

    function renderReasons(values) {
        if (values.length === 0)
            return "none"
        var rendered = []
        for (var index = 0; index < values.length; ++index) {
            var reason = values[index]
            rendered.push(
                reason.code + ": " + reason.summary
                + " Guidance: " + reason.correctiveGuidance
            )
        }
        return rendered.join("; ")
    }

    function renderParameterSchemas(values) {
        if (values.length === 0)
            return "none"
        var rendered = []
        for (var index = 0; index < values.length; ++index) {
            var parameter = values[index]
            var bounds = parameter.minimum === "" && parameter.maximum === ""
                ? "unbounded"
                : "min " + (parameter.minimum === "" ? "none" : parameter.minimum)
                    + " / max " + (parameter.maximum === "" ? "none" : parameter.maximum)
            var choices = parameter.choices.length === 0
                ? "none" : parameter.choices.join("|")
            rendered.push(
                parameter.name + " type " + parameter.valueType
                + " required " + parameter.required
                + " bounds " + bounds
                + " choices " + choices
            )
        }
        return rendered.join("; ")
    }

    function renderTransformations(values) {
        if (values.length === 0)
            return "none"
        var rendered = []
        for (var index = 0; index < values.length; ++index) {
            var item = values[index]
            var parameters = []
            for (var parameterIndex = 0;
                    parameterIndex < item.parameters.length;
                    ++parameterIndex) {
                var parameter = item.parameters[parameterIndex]
                parameters.push(parameter.name + "=" + parameter.value)
            }
            rendered.push(
                item.transformationId + "@" + item.implementationVersion
                + (parameters.length === 0
                    ? "" : " (" + parameters.join(", ") + ")")
            )
        }
        return rendered.join("; ")
    }

    function renderPreviewNodes(values) {
        if (values.length === 0)
            return "none"
        var rendered = []
        for (var index = 0; index < values.length; ++index) {
            var node = values[index]
            rendered.push(
                node.instrument + " @ " + node.simulationTime
                + " O/H/L/C " + node.open + "/" + node.high
                + "/" + node.low + "/" + node.close
                + " volume " + node.volume + " amount " + node.amount
                + " reconstructed " + node.reconstructed
            )
        }
        return rendered.join("\n")
    }

    Flickable {
        id: scroll
        objectName: "scenarioLabFlickable"
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: content.implicitHeight + tokens.spaceXl * 2

        ColumnLayout {
            id: content
            width: Math.max(0, scroll.width - tokens.spaceXl * 2)
            x: tokens.spaceXl
            y: tokens.spaceXl
            spacing: tokens.spaceLg

            Text {
                Layout.fillWidth: true
                text: "SCENARIO LAB"
                color: tokens.accent
                font.pixelSize: tokens.labelSize
                font.bold: true
                Accessible.role: Accessible.Heading
            }

            Text {
                Layout.fillWidth: true
                text: "Inspect admitted historical data, immutable Reference Market Paths, and backend-owned Market Scenario projections."
                color: tokens.textMuted
                font.pixelSize: tokens.bodySize
                wrapMode: Text.WordWrap
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: statusColumn.implicitHeight + tokens.spaceMd * 2
                radius: tokens.radiusMd
                color: tokens.surfaceRaised
                border.color: adapter.freshness === "fresh"
                    ? tokens.accent : tokens.focus
                Accessible.role: Accessible.StatusBar
                Accessible.name: adapter.statusMessage

                ColumnLayout {
                    id: statusColumn
                    anchors.fill: parent
                    anchors.margins: tokens.spaceMd
                    spacing: tokens.spaceXs

                    Text {
                        Layout.fillWidth: true
                        text: adapter.statusMessage
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Source revision " + adapter.sourceRevision
                            + " · generation " + adapter.sourceGeneration
                            + " · catalog " + adapter.catalogVersion
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }

            TextField {
                id: searchInput
                objectName: "scenarioLabSearchInput"
                Layout.fillWidth: true
                activeFocusOnTab: true
                placeholderText: "Search segment, path, scenario, provenance, or transformation"
                text: adapter.searchText
                Accessible.name: "Search Scenario Lab inventory"
                Accessible.description: "Search only the immutable typed Scenario Lab ViewState"
                onTextEdited: adapter.setSearchText(text)
                onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: tokens.spaceSm

                ComboBox {
                    id: marketFilter
                    objectName: "scenarioLabMarketFilter"
                    Layout.fillWidth: true
                    activeFocusOnTab: true
                    model: ["All markets"].concat(adapter.availableMarkets)
                    currentIndex: adapter.marketFilter === ""
                        ? 0 : Math.max(0, model.indexOf(adapter.marketFilter))
                    Accessible.name: "Filter Scenario Lab by market"
                    Accessible.description: "Filter typed Historical Segment market identities"
                    onActivated: adapter.setMarketFilter(
                        currentIndex === 0 ? "" : currentText
                    )
                    onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                }

                ComboBox {
                    id: sourceFilter
                    objectName: "scenarioLabSourceFilter"
                    Layout.fillWidth: true
                    activeFocusOnTab: true
                    model: ["All source snapshots"].concat(adapter.availableSources)
                    currentIndex: adapter.sourceFilter === ""
                        ? 0 : Math.max(0, model.indexOf(adapter.sourceFilter))
                    Accessible.name: "Filter Scenario Lab by source snapshot"
                    Accessible.description: "Filter exact admitted source snapshot identities"
                    onActivated: adapter.setSourceFilter(
                        currentIndex === 0 ? "" : currentText
                    )
                    onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                }

                ComboBox {
                    id: recipeVersionFilter
                    objectName: "scenarioLabRecipeVersionFilter"
                    Layout.fillWidth: true
                    activeFocusOnTab: true
                    model: ["All Recipe versions"].concat(
                        adapter.availableRecipeVersions
                    )
                    currentIndex: adapter.recipeVersionFilter === ""
                        ? 0 : Math.max(
                            0, model.indexOf(adapter.recipeVersionFilter)
                        )
                    Accessible.name: "Filter Market Scenarios by Recipe version"
                    Accessible.description: "Filter immutable Approved Scenario Recipe version identities"
                    onActivated: adapter.setRecipeVersionFilter(
                        currentIndex === 0 ? "" : currentText
                    )
                    onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                }

                ComboBox {
                    id: layerFilter
                    objectName: "scenarioLabLayerFilter"
                    Layout.fillWidth: true
                    activeFocusOnTab: true
                    model: ["All scenario layers"].concat(adapter.availableLayers)
                    currentIndex: adapter.layerFilter === ""
                        ? 0 : Math.max(0, model.indexOf(adapter.layerFilter))
                    Accessible.name: "Filter Market Scenarios by layer"
                    Accessible.description: "Filter typed Campaign Case layer projections"
                    onActivated: adapter.setLayerFilter(
                        currentIndex === 0 ? "" : currentText
                    )
                    onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: tokens.spaceSm

                ComboBox {
                    id: transformationFamilyFilter
                    objectName: "scenarioLabTransformationFamilyFilter"
                    Layout.fillWidth: true
                    activeFocusOnTab: true
                    model: ["All transformation families"].concat(
                        adapter.availableTransformationFamilies
                    )
                    currentIndex: adapter.transformationFamilyFilter === ""
                        ? 0 : Math.max(
                            0,
                            model.indexOf(adapter.transformationFamilyFilter)
                        )
                    Accessible.name: "Filter Scenario Lab by transformation family"
                    Accessible.description: "Filter reviewed transformation family identities"
                    onActivated: adapter.setTransformationFamilyFilter(
                        currentIndex === 0 ? "" : currentText
                    )
                    onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                }

                ComboBox {
                    id: compatibilityFilter
                    objectName: "scenarioLabCompatibilityFilter"
                    Layout.fillWidth: true
                    activeFocusOnTab: true
                    model: ["All compatibility states"].concat(
                        adapter.availableCompatibilities
                    )
                    currentIndex: adapter.compatibilityFilter === ""
                        ? 0 : Math.max(
                            0, model.indexOf(adapter.compatibilityFilter)
                        )
                    Accessible.name: "Filter Scenario Lab by compatibility"
                    Accessible.description: "Filter backend-owned compatibility assessments"
                    onActivated: adapter.setCompatibilityFilter(
                        currentIndex === 0 ? "" : currentText
                    )
                    onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                }

                ComboBox {
                    id: reproducibilityFilter
                    objectName: "scenarioLabReproducibilityFilter"
                    Layout.fillWidth: true
                    activeFocusOnTab: true
                    model: ["All reproducibility states"].concat(
                        adapter.availableReproducibilities
                    )
                    currentIndex: adapter.reproducibilityFilter === ""
                        ? 0 : Math.max(
                            0, model.indexOf(adapter.reproducibilityFilter)
                        )
                    Accessible.name: "Filter Scenario Lab by reproducibility"
                    Accessible.description: "Filter backend-owned reproducibility assessments"
                    onActivated: adapter.setReproducibilityFilter(
                        currentIndex === 0 ? "" : currentText
                    )
                    onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                }

                ComboBox {
                    id: reconstructionFilter
                    objectName: "scenarioLabReconstructionFilter"
                    Layout.fillWidth: true
                    activeFocusOnTab: true
                    model: [
                        "All path origins",
                        "Reconstructed paths",
                        "Recorded paths"
                    ]
                    currentIndex: adapter.reconstructionFilter === "reconstructed"
                        ? 1 : adapter.reconstructionFilter === "recorded" ? 2 : 0
                    Accessible.name: "Filter Reference Paths by reconstruction state"
                    Accessible.description: "Distinguish reconstructed paths from recorded data"
                    onActivated: adapter.setReconstructionFilter(
                        currentIndex === 1
                            ? "reconstructed"
                            : currentIndex === 2 ? "recorded" : "all"
                    )
                    onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                }
            }

            Text {
                Layout.fillWidth: true
                text: "ADMITTED HISTORICAL MARKET SEGMENTS (" + adapter.historicalSegmentCount + ")"
                color: tokens.textPrimary
                font.pixelSize: tokens.bodySize
                font.bold: true
                Accessible.role: Accessible.Heading
            }

            Repeater {
                id: scenarioLabSegmentRepeater
                objectName: "scenarioLabSegmentRepeater"
                model: adapter.historicalSegments

                Rectangle {
                    required property var modelData
                    objectName: "scenarioLabSegment-" + modelData.segmentId
                    Layout.fillWidth: true
                    Layout.preferredHeight: segmentText.implicitHeight + tokens.spaceMd * 2
                    radius: tokens.radiusMd
                    color: tokens.surface
                    border.color: tokens.border
                    Accessible.role: Accessible.ListItem
                    Accessible.name: modelData.label + ", admitted " + modelData.market
                    Accessible.description: "Source " + modelData.sourceSnapshotId
                        + ", quality " + modelData.qualityState

                    Text {
                        id: segmentText
                        anchors.fill: parent
                        anchors.margins: tokens.spaceMd
                        text: modelData.label + "\n"
                            + modelData.segmentId + " · " + modelData.market
                            + " · " + modelData.startDate + " to " + modelData.endDate
                            + "\nSegment content " + modelData.contentHash
                            + " · source snapshot " + modelData.sourceSnapshotId
                            + " / " + modelData.sourceSnapshotContentHash
                            + "\nProvenance " + modelData.provider + " / "
                            + modelData.dataset + " / " + modelData.sourceVersion
                            + " · admission " + modelData.admissionState
                            + " · quality " + modelData.qualityState
                            + "\nCoverage instruments " + modelData.eligibleInstrumentCount
                            + " · trading days " + modelData.tradingDayCount
                            + " · bars " + modelData.barCount
                            + " · tags " + modelData.recommendationTags.join(", ")
                            + "\nUnavailable reasons "
                            + page.renderReasons(modelData.unavailabilityReasons)
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "IMMUTABLE REFERENCE MARKET PATHS (" + adapter.referencePathCount + ")"
                color: tokens.textPrimary
                font.pixelSize: tokens.bodySize
                font.bold: true
                Accessible.role: Accessible.Heading
            }

            Repeater {
                id: scenarioLabPathRepeater
                objectName: "scenarioLabPathRepeater"
                model: adapter.referencePaths

                Rectangle {
                    required property var modelData
                    objectName: "scenarioLabPath-" + modelData.pathId
                    Layout.fillWidth: true
                    Layout.preferredHeight: pathText.implicitHeight + tokens.spaceMd * 2
                    radius: tokens.radiusMd
                    color: tokens.surface
                    border.color: modelData.integrity === "verified"
                        ? tokens.accent : tokens.focus
                    Accessible.role: Accessible.ListItem
                    Accessible.name: "Reference Market Path " + modelData.pathId
                    Accessible.description: modelData.reconstructionNotice

                    Text {
                        id: pathText
                        anchors.fill: parent
                        anchors.margins: tokens.spaceMd
                        text: modelData.pathId + "\n"
                            + "Segment " + modelData.segmentId + " / "
                            + modelData.segmentContentHash
                            + " · source snapshot " + modelData.sourceSnapshotId
                            + "\n"
                            + modelData.sourceResolution + " → " + modelData.runtimeResolution
                            + " · expander " + modelData.expanderVersion
                            + " · seed " + modelData.seed
                            + " · integrity " + modelData.integrity
                            + " · compatibility " + modelData.compatibility
                            + " · reproducibility " + modelData.reproducibility
                            + "\n" + modelData.reconstructionNotice
                            + "\nTolerance " + modelData.numericTolerance
                            + " · normalization " + modelData.normalizationProvenance
                            + " · Market Rule Profile " + modelData.marketRuleProfileVersion
                            + " · transformation catalog "
                            + modelData.transformationCatalogVersion
                            + "\nTime range " + modelData.startTime
                            + " to " + modelData.endTime
                            + " · transformations "
                            + page.renderTransformations(modelData.appliedTransformations)
                            + " · bounded preview " + modelData.previewNodeCount
                            + "/" + modelData.boundedNodeLimit + " nodes"
                            + " @ " + modelData.previewAtTime
                            + "\nEligible universe "
                            + modelData.eligibleUniverse.join(", ")
                            + "\nPreview nodes\n"
                            + page.renderPreviewNodes(modelData.previewNodes)
                            + "\nUnavailable reasons "
                            + page.renderReasons(modelData.unavailabilityReasons)
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "MARKET SCENARIO PROJECTIONS (" + adapter.marketScenarioCount + ")"
                color: tokens.textPrimary
                font.pixelSize: tokens.bodySize
                font.bold: true
                Accessible.role: Accessible.Heading
            }

            Repeater {
                id: scenarioLabScenarioRepeater
                objectName: "scenarioLabScenarioRepeater"
                model: adapter.marketScenarios

                Rectangle {
                    required property var modelData
                    objectName: "scenarioLabScenario-" + modelData.scenarioId
                    Layout.fillWidth: true
                    Layout.preferredHeight: scenarioText.implicitHeight + tokens.spaceMd * 2
                    radius: tokens.radiusMd
                    color: tokens.surface
                    border.color: tokens.border
                    Accessible.role: Accessible.ListItem
                    Accessible.name: "Market Scenario " + modelData.scenarioId
                    Accessible.description: "Campaign Case identity, " + modelData.layer

                    Text {
                        id: scenarioText
                        anchors.fill: parent
                        anchors.margins: tokens.spaceMd
                        text: modelData.scenarioId + "\n"
                            + modelData.layer + " · " + modelData.comparisonRole
                            + " · baseline "
                            + (modelData.baselineScenarioId === ""
                                ? "not applicable" : modelData.baselineScenarioId)
                            + " · Recipe " + modelData.recipeVersionId
                            + " / " + modelData.recipeContentHash
                            + "\nReference Path " + modelData.pathId
                            + " · segment " + modelData.segmentId
                            + " / " + modelData.segmentContentHash
                            + " · source snapshot " + modelData.sourceSnapshotId
                            + "\nSeed " + modelData.seed
                            + " · transformation catalog "
                            + modelData.transformationCatalogVersion
                            + " · Market Rule Profile "
                            + modelData.marketRuleProfileVersion
                            + " · decision cadence "
                            + modelData.decisionCadenceMinutes + " minutes"
                            + "\nTransformations "
                            + page.renderTransformations(modelData.transformations)
                            + "\nRequested execution commission "
                            + modelData.requestedExecutionAssumptions.commissionBps
                            + " bps · slippage "
                            + modelData.requestedExecutionAssumptions.slippageBps
                            + " bps · max fill fraction "
                            + modelData.requestedExecutionAssumptions.maxFillFraction
                            + " · latency nodes "
                            + modelData.requestedExecutionAssumptions.latencyNodes
                            + " · partial fills "
                            + modelData.requestedExecutionAssumptions.allowPartialFills
                            + "\nCompatibility " + modelData.compatibility
                            + " · reproducibility " + modelData.reproducibility
                            + " · execution " + modelData.executionResolution
                            + "\nUnavailable reasons "
                            + page.renderReasons(modelData.unavailabilityReasons)
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "REGISTERED TRANSFORMATION CATALOG"
                color: tokens.textPrimary
                font.pixelSize: tokens.bodySize
                font.bold: true
                Accessible.role: Accessible.Heading
            }

            Repeater {
                id: scenarioLabTransformationRepeater
                objectName: "scenarioLabTransformationRepeater"
                model: adapter.transformations

                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: transformationText.implicitHeight + tokens.spaceMd * 2
                    radius: tokens.radiusMd
                    color: tokens.surface
                    border.color: tokens.border
                    Accessible.role: Accessible.ListItem
                    Accessible.name: "Transformation " + modelData.transformationId

                    Text {
                        id: transformationText
                        anchors.fill: parent
                        anchors.margins: tokens.spaceMd
                        text: modelData.transformationId + " · family " + modelData.family
                            + " · implementation " + modelData.implementationVersion
                            + "\nParameter schema: "
                            + page.renderParameterSchemas(modelData.parameters)
                            + "\nCompatibility: " + modelData.compatibilityRules.join(", ")
                            + "\nCausality: " + modelData.causalityConstraints.join(", ")
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }

            Rectangle {
                objectName: "scenarioLabRecipeAuthoringPanel"
                Layout.fillWidth: true
                Layout.preferredHeight: recipeAuthoringColumn.implicitHeight + tokens.spaceMd * 2
                radius: tokens.radiusMd
                color: tokens.surfaceRaised
                border.color: tokens.border
                Accessible.role: Accessible.Pane
                Accessible.name: "Exact Scenario Recipe Draft authoring"

                ColumnLayout {
                    id: recipeAuthoringColumn
                    anchors.fill: parent
                    anchors.margins: tokens.spaceMd
                    spacing: tokens.spaceSm

                    Text {
                        Layout.fillWidth: true
                        text: "EXACT SCENARIO RECIPE DRAFT AUTHORING"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                        Accessible.role: Accessible.Heading
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Manual authoring is always available for admitted data. A selected registered transformation uses its closed catalog schema; the optional hint overrides the first parameter and remaining parameters use visible catalog defaults. " + adapter.aiAuthoringStatus
                        color: tokens.textMuted
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: tokens.spaceSm

                        TextField {
                            id: aiRecipeIntentInput
                            property string accessibleName: "Audited AI Scenario Recipe intent"
                            objectName: "scenarioLabAiRecipeIntentInput"
                            Layout.fillWidth: true
                            placeholderText: "Describe the diagnostic condition; output remains an untrusted Draft"
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            Accessible.description: adapter.aiAuthoringStatus
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }

                        Button {
                            id: createAiRecipeDraftButton
                            property string accessibleName: "Create audited AI-assisted Scenario Recipe Draft"
                            objectName: "scenarioLabCreateAiRecipeDraftButton"
                            text: "Create audited AI Draft"
                            enabled: adapter.canCreateAiAssistedRecipeDraft
                                && aiRecipeIntentInput.text.trim().length > 0
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            Accessible.description: adapter.aiAuthoringStatus
                            onClicked: adapter.createAiAssistedRecipeDraft(
                                aiRecipeIntentInput.text
                            )
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: tokens.spaceSm
                        rowSpacing: tokens.spaceSm

                        Label { text: "Draft name" }
                        TextField {
                            id: recipeNameInput
                            property string accessibleName: "Scenario Recipe Draft name"
                            objectName: "scenarioLabRecipeNameInput"
                            Layout.fillWidth: true
                            text: "Baseline diagnostic recipe"
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }

                        Label { text: "Admitted segment" }
                        ComboBox {
                            id: recipeSegmentInput
                            property string accessibleName: "Select admitted Historical Market Segment"
                            objectName: "scenarioLabRecipeSegmentInput"
                            Layout.fillWidth: true
                            model: adapter.historicalSegments
                            textRole: "label"
                            valueRole: "segmentId"
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }

                        Label { text: "Registered transformation" }
                        ComboBox {
                            id: recipeTransformationInput
                            property string accessibleName: "Select registered Scenario transformation"
                            objectName: "scenarioLabRecipeTransformationInput"
                            Layout.fillWidth: true
                            model: [{"label": "No transformation", "transformationId": ""}].concat(adapter.transformations)
                            textRole: "label"
                            valueRole: "transformationId"
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            Accessible.description: "No arbitrary transformation or strategy code can be entered"
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }

                        Label { text: "First parameter hint" }
                        TextField {
                            id: recipeTransformationParameterInput
                            property string accessibleName: "Closed transformation first parameter value"
                            objectName: "scenarioLabRecipeTransformationParameterInput"
                            Layout.fillWidth: true
                            placeholderText: "Blank uses the catalog minimum or first choice"
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }

                        Label { text: "Commission bps" }
                        TextField {
                            id: recipeCommissionInput
                            property string accessibleName: "Requested commission basis points"
                            objectName: "scenarioLabRecipeCommissionInput"
                            Layout.fillWidth: true
                            text: "3"
                            inputMethodHints: Qt.ImhFormattedNumbersOnly
                            Accessible.name: accessibleName
                        }

                        Label { text: "Slippage bps" }
                        TextField {
                            id: recipeSlippageInput
                            property string accessibleName: "Requested slippage basis points"
                            objectName: "scenarioLabRecipeSlippageInput"
                            Layout.fillWidth: true
                            text: "0"
                            inputMethodHints: Qt.ImhFormattedNumbersOnly
                            Accessible.name: accessibleName
                        }

                        Label { text: "Maximum fill fraction" }
                        TextField {
                            id: recipeMaxFillInput
                            property string accessibleName: "Requested maximum fill fraction"
                            objectName: "scenarioLabRecipeMaxFillInput"
                            Layout.fillWidth: true
                            text: "1"
                            inputMethodHints: Qt.ImhFormattedNumbersOnly
                            Accessible.name: accessibleName
                        }

                        Label { text: "Latency nodes" }
                        SpinBox {
                            id: recipeLatencyInput
                            property string accessibleName: "Requested execution latency nodes"
                            objectName: "scenarioLabRecipeLatencyInput"
                            from: 0
                            to: 1000
                            value: 0
                            editable: true
                            Accessible.name: accessibleName
                        }

                        Label { text: "Decision cadence minutes" }
                        SpinBox {
                            id: recipeCadenceInput
                            property string accessibleName: "Scenario decision cadence minutes"
                            objectName: "scenarioLabRecipeCadenceInput"
                            from: 1
                            to: 1440
                            value: 30
                            editable: true
                            Accessible.name: accessibleName
                        }

                        Label { text: "Materialization seed" }
                        SpinBox {
                            id: recipeSeedInput
                            property string accessibleName: "Scenario materialization seed"
                            objectName: "scenarioLabRecipeSeedInput"
                            from: 0
                            to: 2147483647
                            value: 17
                            editable: true
                            Accessible.name: accessibleName
                        }

                        Label { text: "Market Rule Profile" }
                        TextField {
                            id: recipeMarketRuleInput
                            property string accessibleName: "Market Rule Profile version identity"
                            objectName: "scenarioLabRecipeMarketRuleInput"
                            Layout.fillWidth: true
                            text: "a-share-cash-equity.v1"
                            Accessible.name: accessibleName
                        }

                        Label { text: "Partial fills" }
                        CheckBox {
                            id: recipePartialFillsInput
                            property string accessibleName: "Allow requested partial fills"
                            objectName: "scenarioLabRecipePartialFillsInput"
                            checked: true
                            text: "Allow partial fills"
                            Accessible.name: accessibleName
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: tokens.spaceSm

                        Button {
                            id: createRecipeDraftButton
                            property string accessibleName: "Create exact immutable Scenario Recipe Draft"
                            objectName: "scenarioLabCreateRecipeDraftButton"
                            text: "Create immutable Draft"
                            enabled: adapter.canCreateRecipeDraft
                                && recipeSegmentInput.currentIndex >= 0
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            onClicked: adapter.createRecipeDraft(
                                recipeNameInput.text,
                                recipeSegmentInput.currentValue || "",
                                recipeTransformationInput.currentValue || "",
                                recipeCommissionInput.text,
                                recipeSlippageInput.text,
                                recipeMaxFillInput.text,
                                recipeTransformationParameterInput.text,
                                recipeLatencyInput.value,
                                recipeCadenceInput.value,
                                recipeSeedInput.value,
                                recipePartialFillsInput.checked,
                                recipeMarketRuleInput.text
                            )
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }

                        Button {
                            id: reviseRecipeDraftButton
                            property string accessibleName: "Create immutable successor Recipe Draft revision"
                            objectName: "scenarioLabReviseRecipeDraftButton"
                            text: "Create successor revision"
                            enabled: adapter.canReviseRecipeDraft
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            onClicked: adapter.reviseSelectedRecipeDraft(
                                recipeNameInput.text,
                                recipeTransformationInput.currentValue || "",
                                recipeCommissionInput.text,
                                recipeSlippageInput.text,
                                recipeMaxFillInput.text,
                                recipeTransformationParameterInput.text,
                                recipeLatencyInput.value,
                                recipeCadenceInput.value,
                                recipeSeedInput.value,
                                recipePartialFillsInput.checked,
                                recipeMarketRuleInput.text
                            )
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }
                    }

                    Text {
                        objectName: "scenarioLabRecipeCommandStatus"
                        Layout.fillWidth: true
                        text: adapter.recipeCapabilityMessage
                        color: tokens.textMuted
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WordWrap
                        Accessible.role: Accessible.StatusBar
                        Accessible.name: text
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "IMMUTABLE RECIPE DRAFT REVISIONS (" + adapter.recipeDraftCount + ")"
                color: tokens.textPrimary
                font.pixelSize: tokens.bodySize
                font.bold: true
                Accessible.role: Accessible.Heading
            }

            Repeater {
                id: scenarioLabRecipeDraftRepeater
                objectName: "scenarioLabRecipeDraftRepeater"
                model: adapter.recipeDrafts

                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: draftColumn.implicitHeight + tokens.spaceMd * 2
                    radius: tokens.radiusMd
                    color: tokens.surface
                    border.color: adapter.selectedRecipeDraftId === modelData.draftId
                        ? tokens.accent : tokens.border
                    Accessible.role: Accessible.ListItem
                    Accessible.name: modelData.name + ", Recipe Draft revision " + modelData.revision

                    ColumnLayout {
                        id: draftColumn
                        anchors.fill: parent
                        anchors.margins: tokens.spaceMd
                        spacing: tokens.spaceXs

                        Text {
                            Layout.fillWidth: true
                            text: modelData.name + " · revision " + modelData.revision
                                + " · " + modelData.draftId
                                + "\nRecipe " + modelData.recipeId
                                + " · predecessor "
                                + (modelData.predecessorDraftId === "" ? "none" : modelData.predecessorDraftId)
                                + " · payload " + modelData.payloadHash
                                + "\nSegment " + modelData.historicalSegmentId
                                + " · data policy " + modelData.dataPolicy
                                + " · Market Rule Profile " + modelData.marketRuleProfileVersion
                                + " · cadence " + modelData.decisionCadenceMinutes
                                + " · seed " + modelData.materializationSeed
                                + "\nTransformations " + page.renderTransformations(modelData.transformations)
                                + " · author " + modelData.authorId
                                + " · mode " + modelData.authoringMode
                            color: tokens.textPrimary
                            font.pixelSize: tokens.bodySize
                            wrapMode: Text.WrapAnywhere
                        }

                        RowLayout {
                            Button {
                                property string accessibleName: "Select Recipe Draft " + modelData.draftId + " for successor revision"
                                objectName: "scenarioLabSelectRecipeDraft-" + modelData.draftId
                                text: "Select for successor"
                                activeFocusOnTab: true
                                Accessible.name: accessibleName
                                onClicked: adapter.selectRecipeDraft(modelData.draftId)
                                onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                            }
                            Button {
                                property string accessibleName: "Validate exact Recipe Draft revision " + modelData.revision
                                objectName: "scenarioLabValidateRecipeDraft-" + modelData.draftId
                                text: "Validate exact revision"
                                enabled: adapter.canValidateRecipeDraft
                                activeFocusOnTab: true
                                Accessible.name: accessibleName
                                onClicked: adapter.validateRecipeDraft(modelData.draftId)
                                onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                            }
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "RECIPE VALIDATION HISTORY (" + adapter.recipeValidationCount + ")"
                color: tokens.textPrimary
                font.pixelSize: tokens.bodySize
                font.bold: true
                Accessible.role: Accessible.Heading
            }

            Repeater {
                id: scenarioLabRecipeValidationRepeater
                objectName: "scenarioLabRecipeValidationRepeater"
                model: adapter.recipeValidations

                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: validationText.implicitHeight + tokens.spaceMd * 2
                    radius: tokens.radiusMd
                    color: tokens.surface
                    border.color: modelData.valid ? tokens.accent : tokens.focus
                    Accessible.role: Accessible.ListItem
                    Accessible.name: "Recipe validation " + modelData.validationId
                        + ", valid " + modelData.valid

                    Text {
                        id: validationText
                        anchors.fill: parent
                        anchors.margins: tokens.spaceMd
                        text: modelData.validationId
                            + " · Draft " + modelData.draftId
                            + " revision " + modelData.draftRevision
                            + " · valid " + modelData.valid
                            + "\nPayload " + modelData.payloadHash
                            + " · Recipe content "
                            + (modelData.recipeContentHash === "" ? "not issued" : modelData.recipeContentHash)
                            + "\nDependency segment " + modelData.dependencies.historicalSegmentId
                            + " / " + modelData.dependencies.historicalSegmentContentHash
                            + " · source " + modelData.dependencies.sourceSnapshotId
                            + " / " + modelData.dependencies.sourceSnapshotContentHash
                            + "\nSchema " + modelData.dependencies.recipeSchemaIdentity
                            + " / " + modelData.dependencies.recipeSchemaHash
                            + " · catalog " + modelData.dependencies.transformationCatalogVersion
                            + " / " + modelData.dependencies.transformationCatalogHash
                            + " · Market Rule " + modelData.dependencies.marketRuleProfileVersion
                            + " / " + modelData.dependencies.marketRuleProfileHash
                            + "\nFindings " + JSON.stringify(modelData.findings)
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }
        }
    }
}
