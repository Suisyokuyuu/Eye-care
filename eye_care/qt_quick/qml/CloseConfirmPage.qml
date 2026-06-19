import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

// 关闭主窗口确认弹窗（复刻 web #closeWindowModal）：最小化到托盘 / 退出程序，可勾选「记住选择」。
// 无 bridge；选择后发 chosen(action, remember)，由宿主执行（最小化/退出/持久化 close_action）。
Item {
    id: page
    anchors.fill: parent
    // 渐入渐出
    visible: opacity > 0.01
    opacity: open ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    z: 130

    property bool open: false
    property bool remember: false
    signal closed()
    signal chosen(string action, bool remember)   // action: "minimize" | "quit"

    onOpenChanged: if (open) remember = false

    Rectangle {
        anchors.fill: parent; color: "#b3000000"
        MouseArea { anchors.fill: parent; onClicked: page.closed(); onWheel: function(wheel){ wheel.accepted = true } }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 384)        // max-w-sm
        height: col.implicitHeight + 40
        radius: 12; color: "#0F172A"; border.color: "#1affffff"; border.width: 1
        MouseArea { anchors.fill: parent }

        ColumnLayout {
            id: col
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            anchors.margins: 20; spacing: 16

            RowLayout {
                Layout.fillWidth: true
                Text { text: "关闭主窗口"; color: "#ffffff"; font.pixelSize: 18; font.weight: Font.DemiBold }
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

            // 记住选择
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Rectangle {
                    width: 18; height: 18; radius: 4
                    color: page.remember ? "#3B82F6" : "#0B1120"
                    border.color: page.remember ? "#3B82F6" : "#33ffffff"; border.width: 1
                    Text { anchors.centerIn: parent; visible: page.remember; text: "✓"; color: "#fff"; font.pixelSize: 12 }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: page.remember = !page.remember }
                }
                Text {
                    text: "记住选择，不再询问"; color: "#9CA3AF"; font.pixelSize: 13
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: page.remember = !page.remember }
                }
            }

            // 操作
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                Rectangle {
                    Layout.fillWidth: true; height: 40; radius: 8
                    color: minMa.containsMouse ? "#0F172A" : "#1E293B"; border.color: "#1affffff"; border.width: 1
                    Text { anchors.centerIn: parent; text: "最小化到托盘"; color: "#fff"; font.pixelSize: 13; font.weight: Font.Medium }
                    MouseArea { id: minMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: { page.chosen("minimize", page.remember); page.closed(); } }
                }
                Rectangle {
                    Layout.fillWidth: true; height: 40; radius: 8
                    color: quitMa.containsMouse ? "#1E40AF" : "#3B82F6"
                    Text { anchors.centerIn: parent; text: "退出程序"; color: "#fff"; font.pixelSize: 13; font.weight: Font.Medium }
                    MouseArea { id: quitMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: { page.chosen("quit", page.remember); page.closed(); } }
                }
            }
        }
    }
}
