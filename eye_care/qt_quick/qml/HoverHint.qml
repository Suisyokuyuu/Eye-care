import QtQuick

// Same pointer-following hint as the original settings page; above scrolling content.
Item {
    id: hint
    anchors.fill: parent; z: 999; enabled: false
    property string tipText: ""
    property real px: 0
    property real py: 0
    visible: opacity > 0.01
    opacity: tipText !== "" ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 120 } }
    function show(text, pt) { tipText = text; px = pt.x; py = pt.y; }
    function hide() { tipText = ""; }
    Rectangle {
        x: Math.max(8, Math.min(hint.px + 18, hint.width - width - 8))
        y: hint.py + 20 + height <= hint.height - 8 ? hint.py + 20 : Math.max(8, hint.py - height - 20)
        width: label.width + 24; height: label.height + 18
        radius: 8; color: "#FA0B1120"; border.color: "#40ffffff"
        Text {
            id: label; anchors.centerIn: parent
            width: Math.min(implicitWidth, 340, hint.width - 48)
            text: hint.tipText; color: "#e5e7eb"; font.pixelSize: 12
            lineHeight: 1.25; wrapMode: Text.WordWrap
        }
    }
}
