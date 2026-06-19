import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

// 通用二选一小窗（step3，复刻 web #importExportChoiceModal）：导入/导出的类型选择。
// 不带 bridge：外壳设置 title/label1/label2，点选发 chosen(1|2)。实际导入导出的文件 IO 属外壳/host（step4）。
Item {
    id: page
    anchors.fill: parent
    // 渐入渐出
    visible: opacity > 0.01
    opacity: open ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    z: 115

    property bool open: false
    property string title: "请选择"
    property string label1: "按钮1"
    property string label2: "按钮2"
    signal closed()
    signal chosen(int which)        // 1=主按钮 2=次按钮

    Rectangle {
        anchors.fill: parent; color: "#b3000000"
        MouseArea { anchors.fill: parent; onClicked: page.closed(); onWheel: function(wheel){ wheel.accepted = true } }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 384)
        height: col.implicitHeight + 8
        radius: 12; color: "#0F172A"; border.color: "#1affffff"; border.width: 1
        clip: true
        MouseArea { anchors.fill: parent }

        ColumnLayout {
            id: col
            anchors.fill: parent; spacing: 0

            RowLayout {
                Layout.fillWidth: true; Layout.leftMargin: 24; Layout.rightMargin: 16; Layout.topMargin: 16; Layout.bottomMargin: 8
                Text { text: page.title; color: "#ffffff"; font.pixelSize: 17; font.weight: Font.DemiBold }
                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 28; height: 28; radius: 6
                    color: xMa.containsMouse ? "#1affffff" : "transparent"
                    Item {
                        anchors.centerIn: parent; width: 13; height: 13
                        Rectangle { anchors.centerIn: parent; width: 14; height: 1.5; radius: 0.75; color: xMa.containsMouse ? "#ffffff" : "#9CA3AF"; rotation: 45 }
                        Rectangle { anchors.centerIn: parent; width: 14; height: 1.5; radius: 0.75; color: xMa.containsMouse ? "#ffffff" : "#9CA3AF"; rotation: -45 }
                    }
                    MouseArea { id: xMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.closed() }
                }
            }

            RowLayout {
                Layout.fillWidth: true; Layout.leftMargin: 24; Layout.rightMargin: 24; Layout.bottomMargin: 24; spacing: 12
                Rectangle {
                    Layout.fillWidth: true; height: 40; radius: 8; color: b1Ma.containsMouse ? "#1E40AF" : "#3B82F6"
                    Text { anchors.centerIn: parent; text: page.label1; color: "#fff"; font.pixelSize: 14; font.weight: Font.Medium }
                    MouseArea { id: b1Ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { page.chosen(1); page.closed(); } }
                }
                Rectangle {
                    Layout.fillWidth: true; height: 40; radius: 8; color: b2Ma.containsMouse ? "#0F172A" : "#1E293B"; border.color: "#1affffff"; border.width: 1
                    Text { anchors.centerIn: parent; text: page.label2; color: "#fff"; font.pixelSize: 14; font.weight: Font.Medium }
                    MouseArea { id: b2Ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { page.chosen(2); page.closed(); } }
                }
            }
        }
    }
}
