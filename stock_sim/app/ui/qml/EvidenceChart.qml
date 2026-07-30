import QtQuick 2.15
import QtQuick.Shapes 1.15

Item {
    id: chart
    objectName: "productionEvidenceChart"

    property var normalizedPoints: []
    property var overlayModels: []
    property real selectedPointX: -1
    property real selectedPointY: -1
    property int acceptedRevision: 0
    property int samplePointCount: normalizedPoints.length
    property int overlayCount: overlayModels.length
    property int selectedPointSourceIndex: -1
    property string selectedOverlayIdentity: ""
    property string selectedFindingIdentity: ""
    property string selectedBreakpointIdentity: ""
    property int frameSequence: 0
    property bool interactionEnabled: true
    property color seriesColor: "#76B7FF"
    property color overlayColor: "#8290A3"
    property color selectedColor: "#E9C46A"
    property color pointColor: "#F8FAFC"
    property color pointBorderColor: "#111722"
    property color focusColor: "#76B7FF"
    property int labelPixelSize: 11
    property string accessibleDescription: ""
    readonly property var mappedPoints: {
        var output = []
        var plotWidth = Math.max(width - 16, 1)
        var plotHeight = Math.max(height - 16, 1)
        for (var index = 0; index < normalizedPoints.length; ++index) {
            var point = normalizedPoints[index]
            output.push(
                Qt.point(
                    8 + Number(point.x) * plotWidth,
                    8 + (1 - Number(point.y)) * plotHeight
                )
            )
        }
        return output
    }

    signal pointSelected(real ratio)
    signal pointStepRequested(int direction)
    signal focusEntered(var item)

    Accessible.role: Accessible.Graphic
    Accessible.name: "Diagnostic evidence chart"
    Accessible.description: accessibleDescription

    Shape {
        id: evidenceSeriesShape
        objectName: "evidenceChartSeriesShape"
        anchors.fill: parent
        asynchronous: false

        ShapePath {
            fillColor: "transparent"
            strokeColor: chart.seriesColor
            strokeWidth: 1.5
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin

            PathPolyline {
                path: chart.mappedPoints
            }
        }
    }

    Item {
        objectName: "evidenceChartOverlayLayer"
        anchors.fill: parent
        anchors.margins: 8

        Repeater {
            model: chart.overlayModels

            delegate: Rectangle {
                required property var modelData
                property bool horizontal: modelData.axis === "horizontal"
                property real coordinate: Number(modelData.position)
                visible: coordinate >= 0 && coordinate <= 1
                width: horizontal ? parent.width : 1
                height: horizontal ? 1 : parent.height
                x: horizontal ? 0 : coordinate * parent.width
                y: horizontal ? (1 - coordinate) * parent.height : 0
                color: modelData.selected
                    ? chart.selectedColor
                    : chart.overlayColor
                opacity: modelData.selected ? 0.95 : 0.55
            }
        }

        Rectangle {
            objectName: "evidenceChartSelectedPoint"
            visible: chart.selectedPointX >= 0 && chart.selectedPointY >= 0
            width: 8
            height: 8
            radius: 1
            rotation: 45
            x: chart.selectedPointX * parent.width - width / 2
            y: (1 - chart.selectedPointY) * parent.height - height / 2
            color: chart.pointColor
            border.color: chart.pointBorderColor
            border.width: 1
        }
    }

    Rectangle {
        objectName: "evidenceChartSelectionSummary"
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 8
        width: selectionSummaryText.implicitWidth + 12
        height: selectionSummaryText.implicitHeight + 8
        radius: 2
        color: chart.pointBorderColor
        border.color: chart.overlayColor
        visible: chart.selectedFindingIdentity.length > 0
            || chart.selectedBreakpointIdentity.length > 0

        Text {
            id: selectionSummaryText
            anchors.centerIn: parent
            text: (
                (chart.selectedFindingIdentity || "No finding")
                + (chart.selectedBreakpointIdentity.length > 0
                    ? " · " + chart.selectedBreakpointIdentity
                    : "")
            )
            color: chart.pointColor
            font.pixelSize: chart.labelPixelSize
        }
    }

    MouseArea {
        id: pointSelection
        objectName: "evidenceChartPointSelection"
        anchors.fill: parent
        cursorShape: Qt.CrossCursor
        activeFocusOnTab: true
        enabled: chart.interactionEnabled || activeFocus
        Accessible.role: Accessible.Slider
        Accessible.name: "Select diagnostic evidence point"
        Accessible.description: chart.accessibleDescription
        Accessible.focusable: chart.interactionEnabled
        Accessible.focused: activeFocus
        Accessible.onIncreaseAction: chart.pointStepRequested(1)
        Accessible.onDecreaseAction: chart.pointStepRequested(-1)
        onActiveFocusChanged: {
            if (activeFocus)
                chart.focusEntered(pointSelection)
        }
        Keys.onLeftPressed: function(event) {
            chart.pointStepRequested(-1)
            event.accepted = true
        }
        Keys.onRightPressed: function(event) {
            chart.pointStepRequested(1)
            event.accepted = true
        }
        Keys.onPressed: function(event) {
            if (event.key === Qt.Key_Home) {
                chart.pointSelected(0)
                event.accepted = true
            } else if (event.key === Qt.Key_End) {
                chart.pointSelected(1)
                event.accepted = true
            }
        }
        onClicked: function(mouse) {
            chart.pointSelected(mouse.x / Math.max(width, 1))
        }
    }

    Rectangle {
        objectName: "evidenceChartFocusIndicator"
        anchors.fill: parent
        anchors.margins: 1
        color: "transparent"
        border.color: chart.focusColor
        border.width: 2
        visible: pointSelection.activeFocus
    }
}
