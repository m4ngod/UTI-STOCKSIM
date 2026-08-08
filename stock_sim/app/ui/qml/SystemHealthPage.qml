import QtQuick 2.15
import QtQuick.Layouts 1.15

FocusScope {
    id: page
    objectName: "systemHealthPage"
    property var adapter
    property var tokens
    property var leaveFocusTarget: null
    readonly property bool hasMeaningfulFocus: statusSummary.activeFocus
        || diagnosticContextStatus.activeFocus
        || dataSourceStatus.activeFocus

    function restoreFocus() {
        statusSummary.forceActiveFocus()
        return true
    }

    Rectangle {
        anchors.fill: parent
        color: tokens.background

        Flickable {
            id: systemHealthFlickable
            objectName: "systemHealthFlickable"
            anchors.fill: parent
            anchors.margins: tokens.spaceLg
            contentWidth: width
            contentHeight: content.implicitHeight
            clip: true

            ColumnLayout {
                id: content
                width: systemHealthFlickable.width
                spacing: tokens.spaceMd

                Text {
                    Layout.fillWidth: true
                    text: "SYSTEM HEALTH"
                    color: tokens.accent
                    font.pixelSize: tokens.labelSize
                    font.bold: true
                    wrapMode: Text.WordWrap
                }

                Text {
                    Layout.fillWidth: true
                    text: "Diagnostic System Reliability & Compatibility"
                    color: tokens.textPrimary
                    font.pixelSize: 28
                    font.bold: true
                    wrapMode: Text.WordWrap
                }

                Text {
                    Layout.fillWidth: true
                    text: "A read-only view of runtime, diagnostic data-source, queue, cache, durable persistence, and version compatibility facts."
                    color: tokens.textMuted
                    font.pixelSize: tokens.bodySize
                    wrapMode: Text.WordWrap
                }

                Rectangle {
                    id: statusSummary
                    objectName: "systemHealthAccessibleStatus"
                    property string accessibleName: (
                        "System Health " + adapter.presentationState
                        + ", Runtime Health " + adapter.componentClassification
                        + ", Data Source Health "
                        + adapter.dataSourceClassification
                        + ", source connection " + adapter.dataSourceConnection
                        + ", source freshness " + adapter.dataSourceFreshness
                        + ", Queue Health " + adapter.queueClassification
                        + ", pending " + adapter.queuePendingCount
                        + ", running " + adapter.queueRunningCount
                        + ", blocked " + adapter.queueBlockedCount
                        + ", Cache Health " + adapter.cacheClassification
                        + ", cache freshness " + adapter.cacheFreshness
                        + ", cache compatibility " + adapter.cacheCompatibility
                        + ", Persistence Health " + adapter.persistenceClassification
                        + ", availability " + adapter.persistenceAvailability
                        + ", schema " + adapter.persistenceSchemaCompatibility
                        + ", Release binding "
                        + adapter.releaseManifestCompatibility
                        + ", Version Health " + adapter.versionClassification
                        + ", Reproduction Manifest "
                        + adapter.manifestCompatibility
                        + ", freshness " + adapter.freshness
                        + ", completeness " + adapter.completeness
                    )
                    activeFocusOnTab: true
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.max(
                        116,
                        statusColumn.implicitHeight + tokens.spaceMd * 2
                    )
                    radius: tokens.radiusMd
                    color: tokens.surfaceRaised
                    border.color: activeFocus ? tokens.focus : tokens.border
                    border.width: activeFocus ? tokens.focusWidth : 1
                    Accessible.role: Accessible.StaticText
                    Accessible.name: accessibleName
                    Accessible.description: adapter.statusText
                    Accessible.focusable: true
                    Accessible.focused: activeFocus
                    Keys.onEscapePressed: function(event) {
                        if (page.leaveFocusTarget !== null)
                            page.leaveFocusTarget.forceActiveFocus()
                        event.accepted = true
                    }
                    Keys.onBacktabPressed: function(event) {
                        if (page.leaveFocusTarget !== null)
                            page.leaveFocusTarget.forceActiveFocus()
                        event.accepted = true
                    }

                    ColumnLayout {
                        id: statusColumn
                        anchors.fill: parent
                        anchors.margins: tokens.spaceMd
                        spacing: tokens.spaceXs

                        Text {
                            Layout.fillWidth: true
                            text: adapter.presentationState.toUpperCase()
                            color: tokens.textPrimary
                            font.pixelSize: tokens.bodySize
                            font.bold: true
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            Layout.fillWidth: true
                            text: adapter.statusText
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }

                Rectangle {
                    id: diagnosticContextStatus
                    objectName: "diagnosticContextAccessibleStatus"
                    property string accessibleName: adapter.diagnosticContextAccessibleText
                    activeFocusOnTab: true
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.max(
                        176,
                        diagnosticContextColumn.implicitHeight + tokens.spaceMd * 2
                    )
                    radius: tokens.radiusMd
                    color: tokens.surfaceRaised
                    border.color: activeFocus ? tokens.focus : tokens.border
                    border.width: activeFocus ? tokens.focusWidth : 1
                    Accessible.role: Accessible.StaticText
                    Accessible.name: accessibleName
                    Accessible.description: adapter.diagnosticContextExplanation
                    Accessible.focusable: true
                    Accessible.focused: activeFocus
                    Keys.onEscapePressed: function(event) {
                        if (page.leaveFocusTarget !== null)
                            page.leaveFocusTarget.forceActiveFocus()
                        event.accepted = true
                    }
                    Keys.onBacktabPressed: function(event) {
                        statusSummary.forceActiveFocus()
                        event.accepted = true
                    }

                    ColumnLayout {
                        id: diagnosticContextColumn
                        anchors.fill: parent
                        anchors.margins: tokens.spaceMd
                        spacing: tokens.spaceXs

                        Text {
                            Layout.fillWidth: true
                            text: "DIAGNOSTIC CONTEXT · "
                                + adapter.diagnosticContextResolution.toUpperCase()
                            color: tokens.textPrimary
                            font.pixelSize: tokens.bodySize
                            font.bold: true
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "Overall · " + adapter.overallClassification
                                + " · " + adapter.diagnosticContextVersionText
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                        }
                        Text {
                            Layout.fillWidth: true
                            text: adapter.diagnosticIdentityText
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "Component impact · " + adapter.componentImpactText
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }

                Rectangle {
                    id: dataSourceStatus
                    objectName: "dataSourceAccessibleStatus"
                    property string accessibleName: (
                        "Diagnostic Data Source "
                        + adapter.dataSourceClassification
                        + ", connection " + adapter.dataSourceConnection
                        + ", fallback " + adapter.dataSourceFallback
                        + ", recovery " + adapter.dataSourceRecoveryPhase
                        + ", freshness " + adapter.dataSourceFreshness
                    )
                    activeFocusOnTab: true
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.max(
                        116,
                        dataSourceStatusColumn.implicitHeight + tokens.spaceMd * 2
                    )
                    radius: tokens.radiusMd
                    color: tokens.surfaceRaised
                    border.color: activeFocus ? tokens.focus : tokens.border
                    border.width: activeFocus ? tokens.focusWidth : 1
                    Accessible.role: Accessible.StaticText
                    Accessible.name: accessibleName
                    Accessible.description: adapter.dataSourceExplanation
                    Accessible.focusable: true
                    Accessible.focused: activeFocus
                    Keys.onEscapePressed: function(event) {
                        if (page.leaveFocusTarget !== null)
                            page.leaveFocusTarget.forceActiveFocus()
                        event.accepted = true
                    }
                    Keys.onBacktabPressed: function(event) {
                        diagnosticContextStatus.forceActiveFocus()
                        event.accepted = true
                    }

                    ColumnLayout {
                        id: dataSourceStatusColumn
                        anchors.fill: parent
                        anchors.margins: tokens.spaceMd
                        spacing: tokens.spaceXs

                        Text {
                            Layout.fillWidth: true
                            text: "DIAGNOSTIC DATA SOURCE · "
                                + adapter.dataSourceClassification.toUpperCase()
                            color: tokens.textPrimary
                            font.pixelSize: tokens.bodySize
                            font.bold: true
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "Connection · " + adapter.dataSourceConnection
                                + " · fallback " + adapter.dataSourceFallback
                                + " · recovery "
                                + adapter.dataSourceRecoveryPhase
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                        }
                        Text {
                            Layout.fillWidth: true
                            text: adapter.dataSourceExplanation
                            color: tokens.textMuted
                            font.pixelSize: tokens.labelSize
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: tokens.textScale >= 1.75 ? 1 : 2
                    columnSpacing: tokens.spaceMd
                    rowSpacing: tokens.spaceMd

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(
                            190,
                            dataSourceIdentityColumn.implicitHeight
                                + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border

                        ColumnLayout {
                            id: dataSourceIdentityColumn
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: "SAFE SOURCE IDENTITY"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                objectName: "dataSourceIdentityText"
                                Layout.fillWidth: true
                                text: adapter.dataSourceIdentityText
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Affected scope · "
                                    + adapter.dataSourceAffectedScopeText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(
                            190,
                            dataSourceObservationColumn.implicitHeight
                                + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border

                        ColumnLayout {
                            id: dataSourceObservationColumn
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: "SOURCE OBSERVATION"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                objectName: "dataSourceRevisionText"
                                Layout.fillWidth: true
                                text: adapter.dataSourceRevisionText === "Unavailable"
                                    ? "Accepted · Unavailable"
                                    : "Accepted · "
                                        + adapter.dataSourceRevisionText
                                        + " · "
                                        + adapter.dataSourceGenerationText
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Current transport generation · "
                                    + adapter.dataSourceCurrentGenerationText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Freshness · " + adapter.dataSourceFreshness
                                    + " · age " + adapter.dataSourceAgeText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Last reliable · "
                                    + adapter.dataSourceLastReliableText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: tokens.textScale >= 1.75 ? 1 : 2
                    columnSpacing: tokens.spaceMd
                    rowSpacing: tokens.spaceMd

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(
                            244,
                            persistenceColumn.implicitHeight + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border

                        ColumnLayout {
                            id: persistenceColumn
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: "DIAGNOSTIC PERSISTENCE"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Persistence Health · "
                                    + adapter.persistenceClassification
                                    + " · availability "
                                    + adapter.persistenceAvailability
                                color: tokens.textPrimary
                                font.pixelSize: tokens.bodySize
                                font.bold: true
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Persistence freshness · "
                                    + adapter.persistenceFreshness
                                    + " · age " + adapter.persistenceAgeText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Schema compatibility · "
                                    + adapter.persistenceSchemaCompatibility
                                    + " · head " + adapter.persistenceSchemaHead
                                    + " · supported "
                                    + adapter.persistenceSupportedSchemaHead
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Durable read · "
                                    + adapter.persistenceDurableReadText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Durable write · "
                                    + adapter.persistenceDurableWriteText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Reopen verification · "
                                    + adapter.persistenceReopenVerification
                                    + " · recovery "
                                    + adapter.persistenceRecoveryState
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Affected scope · "
                                    + adapter.persistenceAffectedScope
                                    + " · " + adapter.persistenceExplanation
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(
                            278,
                            versionColumn.implicitHeight + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border

                        ColumnLayout {
                            id: versionColumn
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: "VERSION COMPATIBILITY"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Version Health · "
                                    + adapter.versionClassification
                                    + " · Release binding "
                                    + adapter.releaseManifestCompatibility
                                    + " · Reproduction Manifest "
                                    + adapter.manifestCompatibility
                                color: tokens.textPrimary
                                font.pixelSize: tokens.bodySize
                                font.bold: true
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Product build · " + adapter.productBuild
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Feature registry · "
                                    + adapter.featureRegistryText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Dependency lock · "
                                    + adapter.dependencyLockIdentity
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Runner · " + adapter.runnerVersion
                                    + " · schema "
                                    + adapter.diagnosticSchemaVersion
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Evidence · "
                                    + adapter.evidenceFormatVersion
                                    + " · Manifest · "
                                    + adapter.manifestFormatVersion
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: adapter.versionExplanation
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(
                            154,
                            runtimeColumn.implicitHeight + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border

                        ColumnLayout {
                            id: runtimeColumn
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: "APPLICATION RUNTIME"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Application runtime · "
                                    + adapter.componentClassification
                                color: tokens.textPrimary
                                font.pixelSize: tokens.bodySize
                                font.bold: true
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: adapter.componentExplanation
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }

                    Rectangle {
                        id: queueCard
                        objectName: "diagnosticQueueHealthCard"
                        property string accessibleName: (
                            "Diagnostic queue " + adapter.queueClassification
                            + ", pending " + adapter.queuePendingCount
                            + ", running " + adapter.queueRunningCount
                            + ", blocked " + adapter.queueBlockedCount
                        )
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(
                            224,
                            queueColumn.implicitHeight + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border
                        Accessible.role: Accessible.StaticText
                        Accessible.name: accessibleName
                        Accessible.description: adapter.queueExplanation

                        ColumnLayout {
                            id: queueColumn
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: "DIAGNOSTIC QUEUE"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Diagnostic queue · "
                                    + adapter.queueClassification
                                color: tokens.textPrimary
                                font.pixelSize: tokens.bodySize
                                font.bold: true
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Pending " + adapter.queuePendingCount
                                    + " · running " + adapter.queueRunningCount
                                    + " · blocked " + adapter.queueBlockedCount
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Oldest pending · "
                                    + adapter.queueOldestPendingAgeText
                                    + " · consumer "
                                    + adapter.queueConsumerAvailability
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Blockage · " + adapter.queueBlockageReason
                                    + " · freshness " + adapter.queueFreshness
                                    + " · recovery " + adapter.queueRecoveryPhase
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Affected scope · "
                                    + adapter.queueAffectedScope
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: adapter.queueExplanation
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }

                    Rectangle {
                        id: cacheCard
                        objectName: "diagnosticCacheHealthCard"
                        property string accessibleName: (
                            "Diagnostic cache " + adapter.cacheClassification
                            + ", fallback " + adapter.cacheFallback
                            + ", compatibility " + adapter.cacheCompatibility
                        )
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(
                            224,
                            cacheColumn.implicitHeight + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border
                        Accessible.role: Accessible.StaticText
                        Accessible.name: accessibleName
                        Accessible.description: adapter.cacheExplanation

                        ColumnLayout {
                            id: cacheColumn
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: "DIAGNOSTIC CACHE"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Diagnostic cache · "
                                    + adapter.cacheClassification
                                color: tokens.textPrimary
                                font.pixelSize: tokens.bodySize
                                font.bold: true
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Freshness " + adapter.cacheFreshness
                                    + " · age " + adapter.cacheAgeText
                                    + " · generation "
                                    + adapter.cacheGenerationText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Fallback " + adapter.cacheFallback
                                    + " · refresh "
                                    + adapter.cacheLastRefreshResult
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Compatibility " + adapter.cacheCompatibility
                                    + " · recovery " + adapter.cacheRecoveryPhase
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Affected scope · "
                                    + adapter.cacheAffectedScope
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: adapter.cacheExplanation
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(
                            154,
                            observationColumn.implicitHeight + tokens.spaceMd * 2
                        )
                        radius: tokens.radiusMd
                        color: tokens.surface
                        border.color: tokens.border

                        ColumnLayout {
                            id: observationColumn
                            anchors.fill: parent
                            anchors.margins: tokens.spaceMd
                            spacing: tokens.spaceXs

                            Text {
                                text: "OBSERVATION"
                                color: tokens.accent
                                font.pixelSize: tokens.labelSize
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Revision · " + adapter.revisionText
                                color: tokens.textPrimary
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Freshness · " + adapter.freshness
                                    + " · age " + adapter.ageText
                                    + " / " + adapter.freshnessThresholdText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Observed · " + adapter.observedAtText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Last reliable · " + adapter.lastReliableText
                                color: tokens.textMuted
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Source · " + adapter.sourceIdentity
                                    + " · " + adapter.sourceGenerationText
                                color: tokens.textQuiet
                                font.pixelSize: tokens.labelSize
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "No infrastructure controls are available in System Health."
                    color: tokens.textQuiet
                    font.pixelSize: tokens.labelSize
                    horizontalAlignment: Text.AlignRight
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}
