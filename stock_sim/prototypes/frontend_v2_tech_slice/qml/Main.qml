// THROWAWAY PROTOTYPE — issue #33 Qt Quick/QML vertical slice.
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import UTI.Prototype 1.0

ApplicationWindow {
    id: window
    visible: true
    width: 1280
    height: 800
    minimumWidth: 860
    minimumHeight: 620
    color: "#070a0e"
    title: "UTI Diagnostics — Qt Quick/QML vertical slice prototype"

    readonly property color bg: "#070a0e"
    readonly property color surface: "#0d1218"
    readonly property color surface2: "#111820"
    readonly property color line: "#24303b"
    readonly property color textColor: "#f1f4f7"
    readonly property color muted: "#8c98a5"
    readonly property color quiet: "#687582"
    readonly property color green: "#82dec0"
    readonly property color red: "#ff928d"
    readonly property color amber: "#e7bd77"
    readonly property color blue: "#9fbfff"

    function statusColor(status) {
        if (status === "pass") return green
        if (status === "fail") return red
        if (status === "warning") return amber
        return blue
    }

    Shortcut {
        sequence: "Ctrl+K"
        onActivated: filterField.forceActiveFocus()
    }
    Shortcut {
        sequence: "Escape"
        onActivated: backend.closeDetails()
    }
    Shortcut {
        sequence: "Left"
        onActivated: if (!filterField.activeFocus) backend.chooseTechnology("widgets")
    }
    Shortcut {
        sequence: "Right"
        onActivated: if (!filterField.activeFocus) backend.chooseTechnology("web")
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        anchors.bottomMargin: 76
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            spacing: 16
            Label {
                text: "UTI Diagnostics"
                color: green
                font.pixelSize: 16
                font.bold: true
                Accessible.name: "UTI Diagnostics"
            }
            Label {
                text: "Breakout v4.2  /  Liquidity stress × 1.8  /  DGN-24-0719-A"
                color: muted
                font.pixelSize: 10
            }
            Item { Layout.fillWidth: true }
            Label {
                text: "● runtime adapter ready"
                color: green
                font.pixelSize: 10
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            Label {
                text: "PROTOTYPE STATES"
                color: quiet
                font.pixelSize: 9
                font.bold: true
            }
            Repeater {
                model: backend.stateNames
                delegate: Button {
                    required property string modelData
                    text: modelData.charAt(0).toUpperCase() + modelData.slice(1)
                    checked: backend.stateName === modelData
                    checkable: true
                    Accessible.name: "Show " + modelData + " state"
                    onClicked: backend.setState(modelData)
                    background: Rectangle {
                        radius: 5
                        color: parent.checked ? "#13241f" : surface
                        border.color: parent.checked ? green : line
                    }
                    contentItem: Text {
                        text: parent.text
                        color: parent.checked ? green : muted
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        font.pixelSize: 9
                    }
                }
            }
            Item { Layout.fillWidth: true }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 96
            color: surface
            border.color: line
            radius: 7
            RowLayout {
                anchors.fill: parent
                anchors.margins: 14
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 5
                    Label {
                        text: backend.stateName.toUpperCase() + " · " + backend.revisionText
                        color: quiet
                        font.pixelSize: 9
                        font.bold: true
                    }
                    Label {
                        text: backend.headline
                        color: textColor
                        font.pixelSize: 16
                        font.bold: true
                    }
                    Label {
                        text: backend.detail
                        color: muted
                        font.pixelSize: 10
                    }
                }
                ColumnLayout {
                    Layout.preferredWidth: 250
                    Label {
                        Layout.alignment: Qt.AlignRight
                        text: backend.progress + "%"
                        color: green
                        font.family: "Consolas"
                        font.pixelSize: 18
                        font.bold: true
                    }
                    ProgressBar {
                        id: campaignProgress
                        Layout.fillWidth: true
                        value: backend.progress / 100
                        Accessible.name: "Campaign progress " + backend.progress + " percent"
                        background: Rectangle {
                            implicitHeight: 8
                            color: line
                        }
                        contentItem: Item {
                            implicitHeight: 8
                            Rectangle {
                                width: campaignProgress.visualPosition * parent.width
                                height: parent.height
                                color: green
                            }
                        }
                    }
                    Label {
                        Layout.alignment: Qt.AlignRight
                        text: backend.replicaText
                        color: quiet
                        font.pixelSize: 9
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true
                text: "Can the apparent return lead survive hidden and fee stress?"
                color: textColor
                font.family: "Georgia"
                font.pixelSize: 22
            }
            TextField {
                id: filterField
                objectName: "filterField"
                Layout.preferredWidth: 290
                placeholderText: "Filter 50 candidates…  Ctrl+K"
                Accessible.name: "Filter candidates"
                color: textColor
                placeholderTextColor: quiet
                onTextChanged: backend.filterCandidates(text)
                background: Rectangle {
                    color: surface2
                    border.color: filterField.activeFocus ? blue : line
                    radius: 6
                }
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            Rectangle {
                SplitView.preferredWidth: 610
                SplitView.minimumWidth: 390
                color: surface
                border.color: line
                radius: 7
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 7
                    Label {
                        text: "COMPARISON SIGNAL · NOT A CONCLUSION"
                        color: quiet
                        font.pixelSize: 9
                        font.bold: true
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Repeater {
                            model: [
                                ["Rank", "rank", 38],
                                ["Candidate", "candidate", 112],
                                ["Model", "candidate", 120],
                                ["Return", "return", 70],
                                ["Drawdown", "return", 76],
                                ["Evidence", "evidence", 72],
                                ["Lock", "evidence", 62]
                            ]
                            delegate: Button {
                                required property var modelData
                                text: modelData[0]
                                Layout.preferredWidth: modelData[2]
                                Accessible.name: "Sort by " + modelData[0]
                                onClicked: backend.sortCandidates(modelData[1])
                                background: Rectangle { color: "transparent" }
                                contentItem: Text {
                                    text: parent.text
                                    color: quiet
                                    font.pixelSize: 8
                                    font.bold: true
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                        }
                    }
                    ListView {
                        id: candidateList
                        objectName: "candidateList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: backend.candidates
                        currentIndex: count > 0 ? 0 : -1
                        activeFocusOnTab: true
                        Accessible.name: "50 candidate comparison table"
                        keyNavigationWraps: false
                        Keys.onReturnPressed: backend.openDetails(currentIndex)
                        Keys.onEnterPressed: backend.openDetails(currentIndex)
                        delegate: Rectangle {
                            required property int index
                            required property int rank
                            required property string candidateId
                            required property string modelName
                            required property string returnText
                            required property string drawdownText
                            required property string evidenceStatus
                            required property string researchLock
                            width: candidateList.width
                            height: 32
                            color: ListView.isCurrentItem ? "#183029" : (index % 2 ? surface2 : surface)
                            Accessible.name: rank + " " + candidateId + " " + returnText + " " + evidenceStatus + " " + researchLock
                            MouseArea {
                                anchors.fill: parent
                                onClicked: {
                                    candidateList.currentIndex = index
                                    candidateList.forceActiveFocus()
                                }
                                onDoubleClicked: backend.openDetails(index)
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 6
                                anchors.rightMargin: 6
                                spacing: 7
                                Label { text: rank; color: muted; Layout.preferredWidth: 32; horizontalAlignment: Text.AlignRight }
                                Label { text: candidateId; color: textColor; font.bold: true; Layout.preferredWidth: 105 }
                                Label { text: modelName; color: muted; Layout.preferredWidth: 113; elide: Text.ElideRight }
                                Label { text: returnText; color: textColor; Layout.preferredWidth: 62; horizontalAlignment: Text.AlignRight; font.family: "Consolas" }
                                Label { text: drawdownText; color: muted; Layout.preferredWidth: 68; horizontalAlignment: Text.AlignRight; font.family: "Consolas" }
                                Label { text: evidenceStatus; color: window.statusColor(evidenceStatus); Layout.preferredWidth: 65 }
                                Label { text: researchLock; color: muted; Layout.preferredWidth: 58 }
                            }
                        }
                    }
                }
            }

            Rectangle {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 390
                color: surface
                border.color: line
                radius: 7
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 7
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Label {
                                text: "100K-POINT EVIDENCE TIMELINE · 3 OVERLAYS"
                                color: quiet
                                font.pixelSize: 9
                                font.bold: true
                            }
                            Label {
                                text: "Candidate vs baseline under stress"
                                color: textColor
                                font.family: "Georgia"
                                font.pixelSize: 17
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            text: "paint cap 20 fps"
                            color: amber
                            font.family: "Consolas"
                            font.pixelSize: 9
                        }
                    }
                    EvidenceTimeline {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Accessible.role: Accessible.Graphic
                        Accessible.name: "Evidence timeline chart"
                        Accessible.description: backend.chartSummary
                    }
                    Label {
                        Layout.fillWidth: true
                        text: backend.chartSummary
                        color: muted
                        wrapMode: Text.WordWrap
                        font.pixelSize: 9
                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            text: "READ-ONLY PROTOTYPE · no Create/Start/Stop/Evaluate, gate override, promotion, or manual order capability"
            color: quiet
            font.pixelSize: 9
        }
    }

    Rectangle {
        id: detailsDrawer
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        width: Math.min(390, parent.width * 0.42)
        visible: backend.detailsOpen
        color: surface2
        border.color: line
        z: 20
        Accessible.role: Accessible.Pane
        Accessible.name: "Candidate evidence details"
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Label {
                    Layout.fillWidth: true
                    text: backend.detailsTitle
                    color: textColor
                    font.family: "Georgia"
                    font.pixelSize: 20
                }
                Button {
                    text: "×"
                    Accessible.name: "Close candidate details"
                    onClicked: backend.closeDetails()
                }
            }
            Label {
                Layout.fillWidth: true
                text: backend.detailsCopy
                wrapMode: Text.WordWrap
                color: muted
                font.pixelSize: 10
            }
            Label {
                text: "TEXT AND TABLE EQUIVALENT"
                color: quiet
                font.bold: true
                font.pixelSize: 9
            }
            TextArea {
                Layout.fillWidth: true
                Layout.fillHeight: true
                readOnly: true
                text: backend.chartSummary + "\n\nSampled steps: 0, 9090, 18181, 27272, 36363, 45454, 54545, 63636, 72727, 81818, 90909, 99999."
                color: textColor
                wrapMode: TextEdit.Wrap
                Accessible.name: "Evidence timeline text and table equivalent"
                background: Rectangle { color: surface; border.color: line; radius: 6 }
            }
        }
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 12
        width: switchRow.implicitWidth + 18
        height: 42
        radius: 21
        color: "#f2efe8"
        border.color: "#c5c0b6"
        z: 30
        Accessible.name: "Technology prototype switcher"
        RowLayout {
            id: switchRow
            anchors.centerIn: parent
            spacing: 10
            Button {
                text: "←"
                Accessible.name: "Previous technology prototype"
                onClicked: backend.chooseTechnology("widgets")
                background: Rectangle { color: "transparent" }
            }
            Label {
                text: "Q — Qt Quick/QML · same contract · declarative scene"
                color: "#1a2026"
                font.family: "Consolas"
                font.pixelSize: 9
            }
            Button {
                text: "→"
                Accessible.name: "Next technology prototype"
                onClicked: backend.chooseTechnology("web")
                background: Rectangle { color: "transparent" }
            }
        }
    }
}
