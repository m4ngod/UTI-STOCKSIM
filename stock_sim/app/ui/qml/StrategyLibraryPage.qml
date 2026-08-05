import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: page
    objectName: "strategyLibraryPage"

    required property var adapter
    required property var tokens
    property var lastFocusedItem: null
    readonly property bool hasMeaningfulFocus: (
        lastFocusedItem !== null
        && lastFocusedItem.activeFocus
        && lastFocusedItem.visible
        && lastFocusedItem.enabled
    )
    readonly property var firstActionControl: searchInput

    function renderComparisonNarrative(values) {
        if (values.length === 0)
            return "No comparison has been accepted for this revision."
        var rendered = []
        for (var index = 0; index < values.length; ++index) {
            var item = values[index]
            var thresholds = []
            for (var thresholdIndex = 0;
                    thresholdIndex < item.guardrailThresholds.length;
                    ++thresholdIndex) {
                var threshold = item.guardrailThresholds[thresholdIndex]
                thresholds.push(
                    threshold.metric + " " + threshold.operator + " "
                    + threshold.value
                )
            }
            var dependencies = []
            for (var dependencyIndex = 0;
                    dependencyIndex < item.dependencies.length;
                    ++dependencyIndex) {
                var dependency = item.dependencies[dependencyIndex]
                dependencies.push(
                    dependency.kind + " · " + dependency.identity + " @ "
                    + dependency.version + " · SHA-256 "
                    + dependency.contentHash + " · availability "
                    + (dependency.available ? "available" : "unavailable")
                    + " · compatibility "
                    + (dependency.compatible ? "compatible" : "incompatible")
                    + (dependency.available && dependency.compatible
                        ? " · ready" : " · blocked")
                )
            }
            rendered.push(
                "Identity and version · " + item.strategyId + " @ "
                + item.strategyVersion
                + " · Source lineage · " + item.lineage.join(" → ")
                + " · Source identity · " + item.sourceModule + " · "
                + item.sourcePath + " · SHA-256 " + item.sourceHash
                + " · Compatibility · " + item.surfaceVersion
                + " · manifest " + item.manifestHash
                + " · Declared capabilities · "
                + (item.capabilities.length > 0
                    ? item.capabilities.join(", ") : "none")
                + " · Candidate data policy · " + item.candidateDataPolicy
                + " · Guardrail profile · " + item.guardrailProfileId + " @ "
                + item.guardrailProfileVersion
                + " · Guardrail thresholds · "
                + (thresholds.length > 0 ? thresholds.join(", ") : "none")
                + " · Dependency provenance · "
                + (dependencies.length > 0 ? dependencies.join(", ") : "none")
                + " · Diagnostic applicability · "
                + (item.formalCampaignEligible
                    ? "Formal Campaign ready" : "Unavailable")
            )
        }
        return rendered.join("; ")
    }

    function rememberFocus(item) {
        lastFocusedItem = item
        ensureItemVisible(item)
    }

    function ensureItemVisible(item) {
        if (item === null || !scroll.visible)
            return
        var point = item.mapToItem(scroll.contentItem, 0, 0)
        var top = point.y - tokens.spaceMd
        var bottom = point.y + item.height + tokens.spaceMd
        if (top < scroll.contentY)
            scroll.contentY = Math.max(0, top)
        else if (bottom > scroll.contentY + scroll.height)
            scroll.contentY = Math.max(
                0,
                Math.min(
                    scroll.contentHeight - scroll.height,
                    bottom - scroll.height
                )
            )
    }

    function restoreFocus() {
        var target = lastFocusedItem
        if (target === null || !target.visible || !target.enabled) {
            if (adapter.focusRestorationTarget === "select_formal_set")
                target = selectFormalSetButton
            else if (adapter.focusRestorationTarget === "compare_formal_set")
                target = compareFormalSetButton
        }
        if ((target === null || !target.visible || !target.enabled)
                && adapter.focusRestorationTarget === "strategy_details"
                && adapter.focusRestorationId.length > 0) {
            for (var index = 0; index < strategyEntryRepeater.count; ++index) {
                var card = strategyEntryRepeater.itemAt(index)
                if (card !== null
                        && card.modelData.strategyId === adapter.focusRestorationId) {
                    target = card.primaryFocusControl
                    break
                }
            }
        }
        if (target === null || !target.visible || !target.enabled)
            target = searchInput
        target.forceActiveFocus()
        ensureItemVisible(target)
        return true
    }

    Flickable {
        id: scroll
        objectName: "strategyLibraryFlickable"
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
                text: "STRATEGY LIBRARY"
                color: tokens.accent
                font.pixelSize: tokens.labelSize
                font.bold: true
                Accessible.role: Accessible.Heading
            }

            Text {
                Layout.fillWidth: true
                text: "Browse authoritative Strategies Under Test without entering a trading workspace."
                color: tokens.textMuted
                font.pixelSize: tokens.bodySize
                wrapMode: Text.WordWrap
            }

            Rectangle {
                objectName: "strategyLibraryAccessibleStatus"
                Layout.fillWidth: true
                Layout.preferredHeight: statusColumn.implicitHeight + tokens.spaceMd * 2
                radius: tokens.radiusMd
                color: tokens.surfaceRaised
                border.color: adapter.freshness === "fresh"
                    ? tokens.accent : tokens.focus
                Accessible.role: Accessible.StatusBar
                Accessible.name: adapter.statusMessage
                Accessible.description: "Source revision "
                    + adapter.sourceRevision + ", generation "
                    + adapter.sourceGeneration + ", selection "
                    + adapter.selectionStatus + ", selection identity "
                    + (adapter.selectionContextId.length === 0
                        ? "unavailable" : adapter.selectionContextId)

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
                        text: "Source generation " + adapter.sourceGeneration
                            + " · revision " + adapter.sourceRevision
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: tokens.spaceMd

                TextField {
                    id: searchInput
                    objectName: "strategyLibrarySearchInput"
                    property bool focusVisible: activeFocus
                    property string accessibleName: (
                        "Search authoritative Strategy inventory"
                    )
                    Layout.fillWidth: true
                    placeholderText: (
                        "Search identity, version, lineage, name, or capability"
                    )
                    text: adapter.searchText
                    activeFocusOnTab: true
                    Accessible.name: accessibleName
                    Accessible.description: (
                        "Filters the already-read typed inventory; it does not discover files or modules"
                    )
                    background: Rectangle {
                        color: tokens.surface
                        radius: tokens.radiusSm
                        border.color: searchInput.activeFocus
                            ? tokens.focus : tokens.border
                        border.width: searchInput.activeFocus
                            ? tokens.focusWidth : 1
                    }
                    onTextEdited: adapter.setSearchText(text)
                    onActiveFocusChanged: {
                        if (activeFocus)
                            page.rememberFocus(searchInput)
                    }
                }

                ComboBox {
                    id: availabilityFilter
                    objectName: "strategyLibraryAvailabilityFilter"
                    property string accessibleName: "Filter Strategy availability"
                    Layout.preferredWidth: Math.max(220, tokens.bodySize * 14)
                    activeFocusOnTab: true
                    model: [
                        { label: "All availability", value: "all" },
                        { label: "Formal Campaign ready", value: "formal_campaign_ready" },
                        { label: "Unavailable", value: "unavailable" },
                        { label: "Outdated", value: "outdated" },
                        { label: "Incompatible", value: "incompatible" },
                        { label: "Missing dependency", value: "missing_dependency" }
                    ]
                    textRole: "label"
                    valueRole: "value"
                    Accessible.name: accessibleName
                    onActivated: adapter.setAvailabilityFilter(currentValue)
                    onActiveFocusChanged: {
                        if (activeFocus)
                            page.rememberFocus(availabilityFilter)
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: adapter.presentationState === "loading"
                    || adapter.presentationState === "failed"
                    || adapter.presentationState === "disconnected"
                    || adapter.entryCount === 0
                text: adapter.presentationState === "loading"
                    ? "Loading authoritative Strategy inventory…"
                    : adapter.presentationState === "failed"
                        ? "Strategy inventory read failed. No empty success is being shown."
                        : adapter.presentationState === "disconnected"
                            ? "Disconnected. Last reliable entries remain visible when available."
                            : "No Strategy entries match the current typed filters."
                color: tokens.textMuted
                font.pixelSize: tokens.bodySize
                wrapMode: Text.WordWrap
            }

            Text {
                objectName: "strategyLibraryInventorySummary"
                Layout.fillWidth: true
                visible: adapter.entryCount > 0
                text: adapter.entryCount + " authoritative Strategies Under Test"
                    + " · Formal Campaign ready status"
                    + " · PTrade surface and Guardrail profile details available"
                color: tokens.textQuiet
                font.pixelSize: tokens.labelSize
                wrapMode: Text.WordWrap
            }

            Rectangle {
                objectName: "strategyLibraryFormalSetPanel"
                Layout.fillWidth: true
                Layout.preferredHeight: formalSetColumn.implicitHeight
                    + tokens.spaceLg * 2
                radius: tokens.radiusMd
                color: tokens.surfaceRaised
                border.color: adapter.selectionStatus === "current"
                    ? tokens.accent : tokens.focus

                ColumnLayout {
                    id: formalSetColumn
                    anchors.fill: parent
                    anchors.margins: tokens.spaceLg
                    spacing: tokens.spaceSm

                    Text {
                        Layout.fillWidth: true
                        text: "FORMAL STRATEGY SET"
                        color: tokens.accent
                        font.pixelSize: tokens.labelSize
                        font.bold: true
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Compare exact backend-declared dimensions; every fact stays explicit and no opaque ranking or recommendation is produced."
                        color: tokens.textMuted
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WordWrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: tokens.spaceMd
                        Button {
                            id: compareFormalSetButton
                            objectName: "strategyLibraryCompareFormalSet"
                            property string accessibleName: text
                            text: "Compare formal set"
                            enabled: adapter.canCompare
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            onClicked: adapter.compareFormalSet()
                            onActiveFocusChanged: {
                                if (activeFocus)
                                    page.rememberFocus(this)
                            }
                        }
                        Button {
                            id: selectFormalSetButton
                            objectName: "strategyLibrarySelectFormalSet"
                            property string accessibleName: text
                            text: "Select exact formal set"
                            enabled: adapter.canSelectFormalSet
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            onClicked: adapter.selectFormalSet()
                            onActiveFocusChanged: {
                                if (activeFocus)
                                    page.rememberFocus(this)
                            }
                        }
                    }
                    Text {
                        objectName: "strategyLibrarySelectionStatus"
                        Layout.fillWidth: true
                        text: "Selection " + adapter.selectionStatus
                            + " · " + adapter.selectionMessage
                        color: adapter.selectionStatus === "current"
                            ? tokens.accent : tokens.textMuted
                        font.pixelSize: tokens.bodySize
                        wrapMode: Text.WordWrap
                        Accessible.role: Accessible.StatusBar
                        Accessible.name: text
                    }
                    Text {
                        Layout.fillWidth: true
                        text: adapter.commandMessage
                        color: tokens.textQuiet
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        objectName: "strategyLibraryComparisonNarrative"
                        Layout.fillWidth: true
                        text: "Accepted comparison revision "
                            + adapter.sourceRevision + " · source generation "
                            + adapter.sourceGeneration + ". "
                            + page.renderComparisonNarrative(
                                adapter.comparisonEntries
                            )
                        color: tokens.textMuted
                        font.pixelSize: tokens.labelSize
                        wrapMode: Text.WrapAnywhere
                        Accessible.role: Accessible.StaticText
                        Accessible.name: "Strategy comparison narrative"
                        Accessible.description: text
                    }
                    Repeater {
                        objectName: "strategyLibraryComparisonRepeater"
                        model: adapter.comparisonEntries
                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: comparisonColumn.implicitHeight
                                + tokens.spaceMd * 2
                            radius: tokens.radiusSm
                            color: tokens.surface
                            ColumnLayout {
                                id: comparisonColumn
                                anchors.fill: parent
                                anchors.margins: tokens.spaceMd
                                spacing: tokens.spaceXs
                                Text {
                                    Layout.fillWidth: true
                                    text: "Identity and version · "
                                        + modelData.strategyId + " @ "
                                        + modelData.strategyVersion
                                    color: tokens.textPrimary
                                    font.pixelSize: tokens.bodySize
                                    font.bold: true
                                    wrapMode: Text.WrapAnywhere
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Source lineage · "
                                        + modelData.lineage.join(" → ")
                                    color: tokens.textMuted
                                    font.pixelSize: tokens.labelSize
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Source identity · "
                                        + modelData.sourceModule + " · "
                                        + modelData.sourcePath + " · SHA-256 "
                                        + modelData.sourceHash
                                    color: tokens.textMuted
                                    font.pixelSize: tokens.labelSize
                                    wrapMode: Text.WrapAnywhere
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Compatibility · "
                                        + modelData.surfaceVersion + " · manifest "
                                        + modelData.manifestHash
                                    color: tokens.textMuted
                                    font.pixelSize: tokens.labelSize
                                    wrapMode: Text.WrapAnywhere
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Declared capabilities · "
                                        + (modelData.capabilities.length > 0
                                            ? modelData.capabilities.join(", ")
                                            : "none")
                                    color: tokens.textMuted
                                    font.pixelSize: tokens.labelSize
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Candidate data policy · "
                                        + modelData.candidateDataPolicy
                                    color: tokens.textMuted
                                    font.pixelSize: tokens.labelSize
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Guardrail profile · "
                                        + modelData.guardrailProfileId + " @ "
                                        + modelData.guardrailProfileVersion
                                    color: tokens.textMuted
                                    font.pixelSize: tokens.labelSize
                                    wrapMode: Text.WrapAnywhere
                                }
                                Repeater {
                                    model: modelData.guardrailThresholds
                                    delegate: Text {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        text: "Guardrail threshold · "
                                            + modelData.metric + " "
                                            + modelData.operator + " "
                                            + modelData.value
                                        color: tokens.textMuted
                                        font.pixelSize: tokens.labelSize
                                        wrapMode: Text.WordWrap
                                    }
                                }
                                Repeater {
                                    model: modelData.dependencies
                                    delegate: Text {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        text: "Dependency provenance · "
                                            + modelData.kind + " · "
                                            + modelData.identity + " @ "
                                            + modelData.version + " · SHA-256 "
                                            + modelData.contentHash
                                            + " · availability "
                                            + (modelData.available
                                                ? "available" : "unavailable")
                                            + " · compatibility "
                                            + (modelData.compatible
                                                ? "compatible" : "incompatible")
                                            + (modelData.available
                                                && modelData.compatible
                                                ? " · ready" : " · blocked")
                                        color: tokens.textMuted
                                        font.pixelSize: tokens.labelSize
                                        wrapMode: Text.WrapAnywhere
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Diagnostic applicability · "
                                        + (modelData.formalCampaignEligible
                                            ? "Formal Campaign ready"
                                            : "Unavailable")
                                    color: tokens.textMuted
                                    font.pixelSize: tokens.labelSize
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }
                }
            }

            Repeater {
                id: strategyEntryRepeater
                objectName: "strategyLibraryEntryRepeater"
                model: adapter.entries

                delegate: Rectangle {
                    id: strategyCard
                    required property var modelData
                    property bool expanded: false
                    property var primaryFocusControl: inspectDetailsButton
                    objectName: "strategyLibraryEntry-" + modelData.strategyId
                    Layout.fillWidth: true
                    Layout.preferredHeight: cardColumn.implicitHeight + tokens.spaceLg * 2
                    radius: tokens.radiusMd
                    color: tokens.surface
                    border.color: modelData.formalCampaignEligible
                        ? tokens.accent : tokens.focus
                    border.width: 1

                    ColumnLayout {
                        id: cardColumn
                        anchors.fill: parent
                        anchors.margins: tokens.spaceLg
                        spacing: tokens.spaceSm

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: tokens.spaceMd

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: tokens.spaceXs
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.displayName
                                    color: tokens.textPrimary
                                    font.pixelSize: tokens.titleSize
                                    font.bold: true
                                    wrapMode: Text.WordWrap
                                    Accessible.role: Accessible.Heading
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.strategyId + " · " + modelData.strategyVersion
                                    color: tokens.textQuiet
                                    font.pixelSize: tokens.labelSize
                                    wrapMode: Text.WrapAnywhere
                                }
                            }

                            Rectangle {
                                Layout.preferredWidth: availabilityText.implicitWidth
                                    + tokens.spaceMd * 2
                                Layout.preferredHeight: availabilityText.implicitHeight
                                    + tokens.spaceSm * 2
                                radius: tokens.radiusSm
                                color: tokens.surfaceRaised
                                Text {
                                    id: availabilityText
                                    anchors.centerIn: parent
                                    text: modelData.availabilityLabel
                                    color: tokens.textPrimary
                                    font.pixelSize: tokens.labelSize
                                    font.bold: true
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: modelData.summary
                            color: tokens.textMuted
                            font.pixelSize: tokens.bodySize
                            wrapMode: Text.WordWrap
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "PTrade surface " + modelData.surfaceVersion
                                + " · Candidate data " + modelData.candidateDataPolicy
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                        }

                        Text {
                            Layout.fillWidth: true
                            text: modelData.guardrailProfileId.length > 0
                                ? "Guardrail profile " + modelData.guardrailProfileId
                                    + " @ " + modelData.guardrailProfileVersion
                                : "Guardrail profile unavailable"
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                        }

                        Button {
                            id: inspectDetailsButton
                            objectName: "inspectStrategyDetails-" + modelData.strategyId
                            property string accessibleName: (
                                text + " for " + modelData.displayName
                            )
                            text: strategyCard.expanded ? "Hide details" : "Inspect details"
                            activeFocusOnTab: true
                            Accessible.name: accessibleName
                            onClicked: strategyCard.expanded = !strategyCard.expanded
                            onActiveFocusChanged: {
                                if (activeFocus) {
                                    adapter.setFocusStrategy(
                                        strategyCard.modelData.strategyId
                                    )
                                    page.rememberFocus(this)
                                }
                            }
                        }

                        ColumnLayout {
                            objectName: "strategyLibraryDetails-" + modelData.strategyId
                            Layout.fillWidth: true
                            visible: strategyCard.expanded
                            spacing: tokens.spaceSm

                            Text {
                                Layout.fillWidth: true
                                text: "Source module " + modelData.sourceModule
                                color: tokens.textPrimary
                                font.pixelSize: tokens.bodySize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Retained source " + modelData.sourcePath
                                    + " · SHA-256 " + modelData.sourceHash
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Manifest SHA-256 " + modelData.manifestHash
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Source lineage · " + modelData.lineage.join(" → ")
                                color: tokens.textMuted
                                font.pixelSize: tokens.bodySize
                                wrapMode: Text.WordWrap
                            }
                            Repeater {
                                model: [
                                    { label: "Lifecycle callbacks", values: modelData.lifecycleCallbacks },
                                    { label: "Scheduled callbacks", values: modelData.scheduledCallbacks },
                                    { label: "Scheduling calls", values: modelData.schedulingCalls },
                                    { label: "Context fields", values: modelData.contextFields },
                                    { label: "Portfolio fields", values: modelData.portfolioFields },
                                    { label: "Market-data calls", values: modelData.marketDataCalls },
                                    { label: "History units", values: modelData.historyUnits },
                                    { label: "Configuration calls", values: modelData.configurationCalls },
                                    { label: "Signed-share interactions", values: modelData.tradingCalls },
                                    { label: "Logging calls", values: modelData.loggingCalls }
                                ]
                                delegate: Text {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    text: modelData.label + " · "
                                        + (modelData.values.length > 0
                                            ? modelData.values.join(", ") : "none")
                                    color: tokens.textMuted
                                    font.pixelSize: tokens.bodySize
                                    wrapMode: Text.WordWrap
                                }
                            }
                            Repeater {
                                model: modelData.guardrailThresholds
                                delegate: Text {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    text: "Guardrail threshold · " + modelData.metric
                                        + " " + modelData.operator + " " + modelData.value
                                    color: tokens.textMuted
                                    font.pixelSize: tokens.bodySize
                                    wrapMode: Text.WordWrap
                                }
                            }
                            Repeater {
                                model: modelData.reasons
                                delegate: Text {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    text: modelData.code + " · " + modelData.summary
                                        + " " + modelData.guidance
                                    color: tokens.textMuted
                                    font.pixelSize: tokens.bodySize
                                    wrapMode: Text.WordWrap
                                }
                            }
                            Repeater {
                                model: modelData.dependencies
                                delegate: Text {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    text: modelData.kind + " · " + modelData.identity
                                        + " @ " + modelData.version
                                        + (modelData.available && modelData.compatible
                                            ? " · ready" : " · blocked")
                                    color: tokens.textQuiet
                                    font.pixelSize: tokens.labelSize
                                    wrapMode: Text.WrapAnywhere
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Connections {
        target: adapter
        function onStateChanged() {
            if (!page.hasMeaningfulFocus
                    && adapter.focusRestorationTarget !== "search")
                Qt.callLater(page.restoreFocus)
        }
    }
}
