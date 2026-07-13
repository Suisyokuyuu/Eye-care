import QtQuick
import QtQuick.Window

// 休息提醒浮层（QML 原生版，复刻原 web notify 浮层观感）。
// - 无边框 / 置顶 / Tool / 透明背景，由 Windows Acrylic（Python 侧 win_effects）透出毛玻璃。
// - Python 读写 messageText / cardVisible，监听 actionTriggered(name)。
//   name: "rest"=立刻休息, "snooze"=跳过本轮, "dismiss"=关闭/自动隐藏。
Window {
    id: win
    width: 400
    height: 160
    flags: Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
    color: "transparent"
    visible: false
    // 整窗透明度随 cardVisible 淡入淡出：亚克力暗底也随之消失，避免渐隐时留下黑色残影。
    // Python hide_notify 仍在 ~230ms 后 setVisible(false)，> 本动画 200ms，保证淡完再隐藏。
    opacity: cardVisible ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutQuad } }

    // ---- 与 Python 的契约 ----
    property string messageText: "连续使用时间已达到提醒阈值，建议休息。"
    property bool cardVisible: false
    signal actionTriggered(string name)

    Rectangle {
        id: card
        anchors.fill: parent
        // 半透明深色，叠在 Acrylic 之上（近似原 tint 0xBB101826）
        color: "#26101826"
        opacity: win.cardVisible ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutQuad } }

        // 轻微内描边
        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.color: "#14FFFFFF"
            border.width: 1
        }

        Column {
            anchors.fill: parent

            // 标题栏
            Item {
                width: parent.width
                height: 44

                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    spacing: 8
                    Rectangle {
                        width: 8; height: 8; radius: 4
                        color: "#3b82f6"
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "休息提醒"
                        color: "#ffffff"
                        font.pixelSize: 13
                        font.bold: true
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                Rectangle {
                    id: closeBtn
                    width: 32; height: 32; radius: 10
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    color: closeMa.containsMouse ? "#1FFFFFFF" : "#0FFFFFFF"
                    border.color: "#1AFFFFFF"
                    border.width: 1
                    Text { anchors.centerIn: parent; text: "✕"; color: "#E6FFFFFF"; font.pixelSize: 13 }
                    MouseArea {
                        id: closeMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: win.actionTriggered("dismiss")
                    }
                }

                Rectangle {
                    anchors.bottom: parent.bottom
                    width: parent.width
                    height: 1
                    color: "#14FFFFFF"
                }
            }

            // 正文
            Item {
                width: parent.width
                height: parent.height - 44

                Text {
                    id: msg
                    text: win.messageText
                    color: "#F2E5E7EB"
                    font.pixelSize: 13
                    lineHeight: 1.45
                    wrapMode: Text.WordWrap
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14
                    anchors.topMargin: 14
                }

                Row {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.rightMargin: 14
                    anchors.bottomMargin: 12
                    spacing: 10

                    // 跳过本轮
                    Rectangle {
                        width: laterTxt.implicitWidth + 32
                        height: 34
                        radius: 12
                        color: laterMa.containsMouse ? "#14FFFFFF" : "#12FFFFFF"
                        border.color: "#1FFFFFFF"
                        border.width: 1
                        Text { id: laterTxt; anchors.centerIn: parent; text: "跳过本轮"; color: "#E5E7EB"; font.pixelSize: 13 }
                        MouseArea {
                            id: laterMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: win.actionTriggered("snooze")
                        }
                    }

                    // 立刻休息
                    Rectangle {
                        width: nowTxt.implicitWidth + 32
                        height: 34
                        radius: 12
                        color: nowMa.containsMouse ? "#E63b82f6" : "#C73b82f6"
                        border.color: "#D13b82f6"
                        border.width: 1
                        Text { id: nowTxt; anchors.centerIn: parent; text: "立刻休息"; color: "#ffffff"; font.pixelSize: 13 }
                        MouseArea {
                            id: nowMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: win.actionTriggered("rest")
                        }
                    }
                }
            }
        }
    }
}
