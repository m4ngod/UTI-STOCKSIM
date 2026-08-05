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

    function renderExecutionTargets(values) {
        if (values.length === 0)
            return "none"
        var rendered = []
        for (var index = 0; index < values.length; ++index) {
            var target = values[index]
            var conditions = []
            for (var conditionIndex = 0;
                    conditionIndex < target.conditions.length;
                    ++conditionIndex) {
                var condition = target.conditions[conditionIndex]
                conditions.push(
                    condition.name + " requested " + condition.requestedValue
                    + " effective " + condition.effectiveValue
                    + (condition.overrideReason === ""
                        ? "" : " because " + condition.overrideReason)
                )
            }
            rendered.push(
                target.strategyId + "@" + target.strategyVersion
                + " / " + target.campaignCaseId
                + " · " + target.state
                + " · Decision Time " + target.decisionTime
                + " · after-Decision-Time " + target.afterDecisionTime
                + " · activation " + target.activationTime
                + " · grid " + target.decisionGrid
                + " · activation policy " + target.activationPolicy
                + " · execution policy " + target.executionPolicyVersion
                + " · Guardrail " + target.guardrailProfileId
                + "@" + target.guardrailProfileVersion
                + " · conditions " + conditions.join("; ")
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

            Rectangle {
                objectName: "scenarioLabFormalScenarioSetPanel"
                Layout.fillWidth: true
                Layout.preferredHeight: scenarioSetColumn.implicitHeight + tokens.spaceMd * 2
                radius: tokens.radiusMd
                color: tokens.surfaceRaised
                border.color: tokens.border
                Accessible.role: Accessible.Pane
                Accessible.name: "Formal Campaign Scenario Sets and execution assumptions"

                ColumnLayout {
                    id: scenarioSetColumn
                    anchors.fill: parent
                    anchors.margins: tokens.spaceMd
                    spacing: tokens.spaceSm

                    Text {
                        Layout.fillWidth: true
                        text: "FORMAL CAMPAIGN SCENARIO SETS"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                        Accessible.role: Accessible.Heading
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Compose the visible baseline, bounded isolated sensitivity, and compound cases. Selective coverage is labeled Quick Experiment and cannot be handed off. Requested and effective execution assumptions are resolved by the same backend production-run policy."
                        color: tokens.textMuted
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: tokens.spaceSm

                        Button {
                            objectName: "scenarioLabComposeVisibleScenarioSetButton"
                            text: "Compose visible cases"
                            enabled: adapter.canComposeScenarioSet
                            activeFocusOnTab: true
                            property string accessibleName: "Compose visible Campaign Cases into a Scenario Set"
                            Accessible.name: "Compose visible Campaign Cases into a Scenario Set"
                            Accessible.description: "Incomplete or filtered case coverage becomes a typed Quick Experiment"
                            onClicked: adapter.composeVisibleScenarioSet()
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }

                        Button {
                            objectName: "scenarioLabResolveExecutionAssumptionsButton"
                            text: "Resolve assumptions"
                            enabled: adapter.canResolveExecutionAssumptions
                            activeFocusOnTab: true
                            property string accessibleName: "Resolve requested and effective execution assumptions"
                            Accessible.name: "Resolve requested and effective execution assumptions"
                            Accessible.description: "Requires the exact selected formal Strategy set and uses after-Decision-Time activation"
                            onClicked: adapter.resolveLatestScenarioSet()
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }

                        Button {
                            objectName: "scenarioLabSelectFormalScenarioSetButton"
                            text: "Select formal context"
                            enabled: adapter.canSelectFormalScenarioSet
                            activeFocusOnTab: true
                            property string accessibleName: "Select immutable Formal Scenario Set context"
                            Accessible.name: "Select immutable Formal Scenario Set context"
                            Accessible.description: "Quick Experiments and unresolved assumptions remain ineligible"
                            onClicked: adapter.selectLatestFormalScenarioSet()
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }
                    }

                    Text {
                        objectName: "scenarioLabScenarioCommandStatus"
                        Layout.fillWidth: true
                        text: adapter.scenarioCommandMessage
                        color: tokens.textMuted
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WordWrap
                        Accessible.role: Accessible.StatusBar
                        Accessible.name: text
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Scenario Sets (" + adapter.scenarioSetCount + ")"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                    }

                    Repeater {
                        objectName: "scenarioLabFormalScenarioSetRepeater"
                        model: adapter.scenarioSets

                        Text {
                            required property var modelData
                            objectName: "scenarioLabFormalScenarioSet-" + modelData.scenarioSetId
                            Layout.fillWidth: true
                            text: modelData.scenarioSetId
                                + " · " + modelData.eligibility
                                + " · formal handoff " + modelData.formalHandoffEligible
                                + "\nBaseline " + modelData.baselineCaseId
                                + " · isolated " + modelData.isolatedCaseIds.length
                                + " · compound " + modelData.compoundCaseIds.length
                                + " · comparisons " + modelData.comparisonRelationships.length
                                + "\nMissing requirements "
                                + (modelData.missingRequirements.length === 0
                                    ? "none" : modelData.missingRequirements.join(", "))
                            color: tokens.textPrimary
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                            Accessible.role: Accessible.ListItem
                            Accessible.name: text
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Execution resolutions (" + adapter.executionResolutionCount + ")"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                    }

                    Repeater {
                        objectName: "scenarioLabExecutionResolutionRepeater"
                        model: adapter.executionResolutions

                        Text {
                            required property var modelData
                            objectName: "scenarioLabExecutionResolution-" + modelData.resolutionId
                            Layout.fillWidth: true
                            text: modelData.resolutionId
                                + " · Scenario Set " + modelData.scenarioSetId
                                + " · formal handoff " + modelData.formalHandoffEligible
                                + "\n" + page.renderExecutionTargets(modelData.targets)
                            color: tokens.textPrimary
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                            Accessible.role: Accessible.ListItem
                            Accessible.name: text
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Selection contexts (" + adapter.selectionContextCount + ")"
                        color: tokens.textPrimary
                        font.pixelSize: tokens.bodySize
                        font.bold: true
                    }

                    Repeater {
                        objectName: "scenarioLabSelectionContextRepeater"
                        model: adapter.selectionContexts

                        Text {
                            required property var modelData
                            objectName: "scenarioLabSelectionContext-" + modelData.selectionContextId
                            Layout.fillWidth: true
                            text: modelData.selectionContextId
                                + " · " + modelData.status
                                + " · selection revision " + modelData.selectionRevision
                                + " · view revision " + modelData.originatingViewRevision
                                + " · source " + modelData.sourceRevision
                                + " / generation " + modelData.sourceGeneration
                                + "\nScenario Set " + modelData.scenarioSetId
                                + "@projection-" + modelData.scenarioSetProjectionRevision
                                + " · execution resolution " + modelData.executionResolutionId
                                + "@projection-" + modelData.executionResolutionProjectionRevision
                                + " · exact cases " + modelData.caseIds.join(", ")
                                + "\nExact Recipes " + modelData.exactRecipeBindings.join(", ")
                                + "\nExact Paths " + modelData.exactPathBindings.join(", ")
                                + "\nExact Strategies / manifests / Guardrails / policies "
                                + modelData.exactStrategyBindings.join(", ")
                            color: tokens.textPrimary
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                            Accessible.role: Accessible.ListItem
                            Accessible.name: text
                        }
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
                    Layout.preferredHeight: validationColumn.implicitHeight + tokens.spaceMd * 2
                    radius: tokens.radiusMd
                    color: tokens.surface
                    border.color: modelData.valid ? tokens.accent : tokens.focus
                    Accessible.role: Accessible.ListItem
                    Accessible.name: "Recipe validation " + modelData.validationId
                        + ", valid " + modelData.valid

                    ColumnLayout {
                        id: validationColumn
                        anchors.fill: parent
                        anchors.margins: tokens.spaceMd
                        spacing: tokens.spaceXs

                        Text {
                            id: validationText
                            Layout.fillWidth: true
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
                                + "\nTransformation implementations "
                                + JSON.stringify(modelData.dependencies.transformationImplementations)
                                + " · data policy " + modelData.dependencies.dataPolicy
                                + "\nCausality rules "
                                + JSON.stringify(modelData.dependencies.causalityRules)
                                + " · compatibility "
                                + JSON.stringify(modelData.dependencies.compatibilityObservations)
                                + "\nFindings " + JSON.stringify(modelData.findings)
                            color: tokens.textPrimary
                            font.pixelSize: tokens.bodySize
                            wrapMode: Text.WrapAnywhere
                        }

                        Button {
                            property string accessibleName: "Approve exact Recipe validation " + modelData.validationId
                            objectName: "scenarioLabApproveRecipe-" + modelData.validationId
                            text: "Approve exact validated revision"
                            enabled: adapter.canApproveRecipe && modelData.valid
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            Accessible.description: "Approval binds this exact Draft revision, payload hash, validation, and dependency identities"
                            onClicked: adapter.approveRecipeValidation(
                                modelData.validationId
                            )
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "IMMUTABLE APPROVED RECIPE VERSION HISTORY (" + adapter.approvedRecipeVersionCount + ")"
                color: tokens.textPrimary
                font.pixelSize: tokens.bodySize
                font.bold: true
                Accessible.role: Accessible.Heading
            }

            Repeater {
                id: scenarioLabApprovedRecipeRepeater
                objectName: "scenarioLabApprovedRecipeRepeater"
                model: adapter.approvedRecipeVersions

                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: approvedVersionColumn.implicitHeight + tokens.spaceMd * 2
                    radius: tokens.radiusMd
                    color: tokens.surface
                    border.color: modelData.authorityState === "current"
                        ? tokens.accent : tokens.focus
                    Accessible.role: Accessible.ListItem
                    Accessible.name: "Approved Scenario Recipe "
                        + modelData.recipeVersionId + ", authority "
                        + modelData.authorityState
                    Accessible.description: "Immutable approval "
                        + modelData.approvalId + " bound to validation "
                        + modelData.validationId

                    ColumnLayout {
                        id: approvedVersionColumn
                        anchors.fill: parent
                        anchors.margins: tokens.spaceMd
                        spacing: tokens.spaceXs

                        Text {
                            Layout.fillWidth: true
                            text: modelData.name + " · Recipe " + modelData.recipeId
                                + " version " + modelData.versionNumber
                                + " · " + modelData.recipeVersionId
                                + "\nContent " + modelData.contentHash
                                + " · based on "
                                + (modelData.basedOnRecipeVersionId === ""
                                    ? "none" : modelData.basedOnRecipeVersionId)
                                + " · author " + modelData.authorId
                                + "\nApproval " + modelData.approvalId
                                + " · actor " + modelData.actorId
                                + " · at " + modelData.approvedAt
                                + "\nDraft " + modelData.draftId
                                + " revision " + modelData.draftRevision
                                + " · payload " + modelData.payloadHash
                                + " · validation " + modelData.validationId
                                + "\nExact dependency binding "
                                + (modelData.dependencyBindingAvailable
                                    ? "available" : "legacy unavailable")
                                + "\nSegment " + modelData.historicalSegmentId
                                + " / " + modelData.historicalSegmentContentHash
                                + " · source " + modelData.sourceSnapshotId
                                + " / " + modelData.sourceSnapshotContentHash
                                + "\nSchema " + modelData.recipeSchemaIdentity
                                + " / " + modelData.recipeSchemaHash
                                + " · catalog " + modelData.transformationCatalogVersion
                                + " / " + modelData.transformationCatalogHash
                                + " · Market Rule " + modelData.marketRuleProfileVersion
                                + " / " + modelData.marketRuleProfileHash
                                + "\nTransformations "
                                + page.renderTransformations(modelData.transformations)
                                + " · implementations "
                                + JSON.stringify(modelData.transformationImplementations)
                                + " · materialization seed " + modelData.materializationSeed
                                + "\nData policy " + modelData.dataPolicy
                                + " · causality rules "
                                + JSON.stringify(modelData.causalityRules)
                                + " · compatibility "
                                + JSON.stringify(modelData.compatibilityObservations)
                                + "\nAuthority " + modelData.authorityState
                                + " · eligible for later materialization "
                                + modelData.canMaterialize
                                + " · reasons "
                                + page.renderReasons(modelData.authorityReasons)
                            color: tokens.textPrimary
                            font.pixelSize: tokens.bodySize
                            wrapMode: Text.WrapAnywhere
                        }

                        Button {
                            property string accessibleName: "Select Approved Recipe " + modelData.recipeVersionId + " for immutable successor Draft"
                            objectName: "scenarioLabSelectApprovedRecipe-" + modelData.recipeVersionId
                            text: "Select for successor Draft"
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            Accessible.description: "Creates no mutation until the explicit successor Draft action"
                            onClicked: adapter.selectApprovedRecipeVersion(
                                modelData.recipeVersionId
                            )
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }

                        Button {
                            property string accessibleName: "Materialize exact Approved Recipe " + modelData.recipeVersionId
                            objectName: "scenarioLabMaterializeApprovedRecipe-" + modelData.recipeVersionId
                            text: "Materialize Reference Market Path"
                            enabled: adapter.canMaterializeApprovedRecipe
                                && modelData.canMaterialize
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            Accessible.description: "Durably accept the exact immutable Recipe version and dependency binding before materialization"
                            onClicked: adapter.materializeApprovedRecipeVersion(
                                modelData.recipeVersionId
                            )
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "PERSISTENT MATERIALIZATION TASK HISTORY (" + adapter.taskHandleCount + ")"
                color: tokens.textPrimary
                font.pixelSize: tokens.bodySize
                font.bold: true
                Accessible.role: Accessible.Heading
            }

            Repeater {
                id: scenarioLabTaskHandleRepeater
                objectName: "scenarioLabTaskHandleRepeater"
                model: adapter.taskHandles

                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: taskHandleColumn.implicitHeight + tokens.spaceMd * 2
                    radius: tokens.radiusMd
                    color: tokens.surface
                    border.color: modelData.phase === "completed"
                        ? tokens.accent : tokens.focus
                    Accessible.role: Accessible.ListItem
                    Accessible.name: "Scenario materialization TaskHandle "
                        + modelData.taskHandleId + ", " + modelData.phase
                    Accessible.description: "Immutable attempt "
                        + modelData.attemptId + ", progress "
                        + modelData.progressPercent + " percent"

                    ColumnLayout {
                        id: taskHandleColumn
                        anchors.fill: parent
                        anchors.margins: tokens.spaceMd
                        spacing: tokens.spaceXs

                        Text {
                            Layout.fillWidth: true
                            text: "TaskHandle " + modelData.taskHandleId
                                + "\nAttempt " + modelData.attemptId
                                + " · operation " + modelData.operation
                                + " · target " + modelData.targetKind
                                + " / " + modelData.targetIdentity
                                + "\nPhase " + modelData.phase
                                + " · progress " + modelData.progressPercent + "%"
                                + " · terminal " + modelData.terminal
                                + " · retryable " + modelData.retryable
                                + "\nResult "
                                + (modelData.resultIdentity === ""
                                    ? "none" : modelData.resultKind + " / "
                                        + modelData.resultIdentity)
                                + "\nError "
                                + (modelData.errorCode === ""
                                    ? "none" : modelData.errorCode + ": "
                                        + modelData.errorMessage)
                                + "\nPredecessor TaskHandle "
                                + (modelData.predecessorTaskHandleId === ""
                                    ? "none" : modelData.predecessorTaskHandleId)
                            color: tokens.textPrimary
                            font.pixelSize: tokens.bodySize
                            wrapMode: Text.WrapAnywhere
                        }

                        Button {
                            property string accessibleName: "Retry failed materialization attempt " + modelData.attemptId
                            objectName: "scenarioLabRetryMaterialization-" + modelData.attemptId
                            text: "Retry failed materialization"
                            visible: modelData.phase === "failed"
                            enabled: visible && modelData.retryable
                                && adapter.canRetryMaterialization
                            activeFocusOnTab: visible
                            Accessible.name: accessibleName
                            Accessible.description: "Create a new linked attempt and persistent TaskHandle without mutating this failed attempt"
                            onClicked: adapter.retryMaterialization(
                                modelData.attemptId,
                                modelData.taskHandleId
                            )
                            onActiveFocusChanged: if (activeFocus) page.rememberFocus(this)
                        }
                    }
                }
            }
        }
    }
}
