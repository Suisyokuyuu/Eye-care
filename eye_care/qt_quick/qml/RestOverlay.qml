import QtQuick
import QtQuick.Window
import QtQuick.Effects

// 全屏休息遮罩（QML 原生版，复刻原 web rest 遮罩 rest/rest.css 观感）。
// - 无边框 / 置顶 / Tool / 透明背景，磨砂由 Windows Acrylic（Python 侧 win_effects, tint 0x33101826）负责。
// - 关键口径（沿用 web 版）：Web/QML 层不做模糊，只铺极淡暗色 + 半透明卡片；模糊全交给窗口级 Acrylic。
// - 倒计时文本由 Python 每 250ms 写 timeText（与 web 一致，用墙钟算余量，避免计时漂移）。
// - 拦截除「跳过本轮」外的一切点击，防穿透到后面窗口。
// 契约：Python 读写 timeText / overlayVisible，监听 actionTriggered(name)，name 目前仅 "snooze"。
Window {
    id: win
    flags: Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
    color: "transparent"
    visible: false

    property string timeText: "00:00"
    property string hintText: "放松眼睛，看看远处"
    property bool overlayVisible: false
    signal actionTriggered(string name)

    // Esc = 跳过本轮
    Shortcut { sequence: "Esc"; onActivated: win.actionTriggered("snooze") }

    Item {
        anchors.fill: parent
        opacity: win.overlayVisible ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: 300; easing.type: Easing.InOutQuad } }

        // 极淡暗色底（rgba(0,0,0,0.10)）；真正的磨砂来自窗口级 Acrylic
        Rectangle {
            anchors.fill: parent
            color: "#1A000000"
        }

        // 吃掉非「跳过本轮」的所有点击，防止穿透到后面的窗口
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.AllButtons
            onClicked: {}
            onPressed: {}
        }

        // 居中卡片
        Rectangle {
            id: card
            anchors.centerIn: parent
            width: Math.min(520, parent.width - 48)
            radius: 18
            color: "#66080E1C"            // rgba(8,14,28,0.40)
            border.color: "#1AFFFFFF"     // rgba(255,255,255,0.10)
            border.width: 1
            // 高度自适应内容
            implicitHeight: content.implicitHeight + 40

            // 复刻 web .rest-card 的投影：box-shadow 0 18px 60px rgba(0,0,0,0.45)
            layer.enabled: true
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowColor: "#73000000"      // rgba(0,0,0,0.45)
                blurMax: 48
                shadowBlur: 1.0
                shadowVerticalOffset: 18
                shadowHorizontalOffset: 0
            }

            Column {
                id: content
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: 22
                width: parent.width - 44
                spacing: 0

                Text {
                    text: "休息中"
                    color: "#A6FFFFFF"
                    font.pixelSize: 16
                    font.letterSpacing: 0.2
                    horizontalAlignment: Text.AlignHCenter
                    width: parent.width
                }
                Item { width: 1; height: 10 }
                Text {
                    text: win.timeText
                    color: "#EBFFFFFF"
                    font.pixelSize: 56
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    width: parent.width
                }
                Item { width: 1; height: 10 }
                Text {
                    text: win.hintText
                    color: "#A6FFFFFF"
                    font.pixelSize: 13
                    horizontalAlignment: Text.AlignHCenter
                    width: parent.width
                }
                Item { width: 1; height: 16 }

                // 「跳过本轮」按钮（复刻 .btn.secondary 背景 #2d7dd2）
                Rectangle {
                    id: snoozeBtn
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: snoozeTxt.implicitWidth + 36
                    height: 38
                    radius: 12
                    color: snoozeMa.containsMouse ? "#3A8AE0" : "#2d7dd2"
                    Text {
                        id: snoozeTxt
                        anchors.centerIn: parent
                        text: "跳过本轮"
                        color: "#ffffff"
                        font.pixelSize: 14
                        font.bold: true
                    }
                    MouseArea {
                        id: snoozeMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: win.actionTriggered("snooze")
                    }
                }
            }
        }
    }
}
