import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

// 检查更新（step3，复刻 web #updateCheckModal）：打开即检查，显示结果。
// 有更新→「前往下载」+「关闭」；否则只「关闭」。数据走 contextProperty updateBridge。
Item {
    id: page
    anchors.fill: parent
    // 渐入渐出
    visible: opacity > 0.01
    opacity: open ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    z: 120

    required property var bridge          // UpdateBridge
    property bool open: false
    signal closed()

    onOpenChanged: if (open) bridge.check()

    Rectangle {
        anchors.fill: parent; color: "#b3000000"
        MouseArea { anchors.fill: parent; onClicked: page.closed(); onWheel: function(wheel){ wheel.accepted = true } }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 440)
        height: contentCol.implicitHeight + 48
        radius: 12; color: "#0F172A"; border.color: "#1affffff"; border.width: 1
        MouseArea { anchors.fill: parent }

        ColumnLayout {
            id: contentCol
            anchors.fill: parent; anchors.margins: 24; spacing: 16

            RowLayout {
                Layout.fillWidth: true
                Text { text: "检查更新"; color: "#ffffff"; font.pixelSize: 20; font.bold: true }
                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 30; height: 30; radius: 6
                    color: xMa.containsMouse ? "#1affffff" : "transparent"
                    Item {
                        anchors.centerIn: parent; width: 14; height: 14
                        Rectangle { anchors.centerIn: parent; width: 15; height: 1.5; radius: 0.75; color: xMa.containsMouse ? "#ffffff" : "#9CA3AF"; rotation: 45 }
                        Rectangle { anchors.centerIn: parent; width: 15; height: 1.5; radius: 0.75; color: xMa.containsMouse ? "#ffffff" : "#9CA3AF"; rotation: -45 }
                    }
                    MouseArea { id: xMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.closed() }
                }
            }

            RowLayout {
                Layout.fillWidth: true; spacing: 8
                // 忙转圈：底环 + 绕中心公转的亮点（整个 Item 旋转 → 亮点可见地转）
                Item {
                    id: spinner
                    visible: page.bridge && page.bridge.busy
                    width: 16; height: 16
                    Rectangle {
                        anchors.fill: parent; radius: 8; color: "transparent"
                        border.color: "#3b82f6"; border.width: 2; opacity: 0.3
                    }
                    Item {
                        anchors.fill: parent
                        RotationAnimator on rotation { from: 0; to: 360; duration: 900; loops: Animation.Infinite; running: spinner.visible }
                        Rectangle {
                            width: 5; height: 5; radius: 2.5; color: "#60A5FA"
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: -1
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: page.bridge ? page.bridge.message : ""
                    color: "#d1d5db"; font.pixelSize: 14; wrapMode: Text.WordWrap
                }
            }

            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Item { Layout.fillWidth: true }
                Rectangle {
                    visible: page.bridge && page.bridge.hasUpdate
                    width: dlTxt.implicitWidth + 28; height: 38; radius: 8
                    color: dlMa.containsMouse ? "#1E40AF" : "#3B82F6"
                    Text { id: dlTxt; anchors.centerIn: parent; text: "前往下载"; color: "#fff"; font.pixelSize: 14; font.weight: Font.Medium }
                    MouseArea { id: dlMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { page.bridge.openUrl(); page.closed(); } }
                }
                Rectangle {
                    width: clTxt.implicitWidth + 28; height: 38; radius: 8
                    color: clMa.containsMouse ? "#0F172A" : "#1E293B"; border.color: "#1affffff"; border.width: 1
                    Text { id: clTxt; anchors.centerIn: parent; text: "关闭"; color: "#fff"; font.pixelSize: 14; font.weight: Font.Medium }
                    MouseArea { id: clMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.closed() }
                }
            }
        }
    }
}
