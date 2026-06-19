import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

// 黑名单页（step3，复刻 web #blacklistModal）：全屏变暗 + 居中卡片(dark-200 rounded-xl p-8 max-w-2xl)。
// 列出已排除计时的应用，逐个移除（行内二次确认，替代 web 的 confirm 弹窗）。
// 数据走 contextProperty blacklistBridge：items=[{appShort,displayName}]，移除调 bridge.remove(appShort)。
Item {
    id: page
    anchors.fill: parent
    // 渐入渐出
    visible: opacity > 0.01
    opacity: open ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    z: 100

    required property var bridge          // BlacklistBridge
    property bool open: false
    signal closed()

    onOpenChanged: if (open) bridge.reload()

    // 背景变暗
    Rectangle {
        anchors.fill: parent
        color: "#b3000000"
        MouseArea { anchors.fill: parent; onClicked: page.closed(); onWheel: function(wheel){ wheel.accepted = true } }
    }

    // 卡片
    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 672)
        // 跟随内容高度（短名单不再撑成大空框），上限不超过窗口
        height: Math.min(parent.height - 48, body.implicitHeight + 64)
        radius: 12
        color: "#0F172A"
        border.color: "#1affffff"; border.width: 1
        MouseArea { anchors.fill: parent }

        ColumnLayout {
            id: body
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            anchors.margins: 24
            spacing: 10

            // 标题栏
            RowLayout {
                Layout.fillWidth: true
                Text { text: "黑名单"; color: "#ffffff"; font.pixelSize: 24; font.bold: true }
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

            Text {
                Layout.fillWidth: true
                text: "以下应用已排除计时，不会记录使用也不会触发休息提示。移除后将恢复记录（历史数据不恢复）。"
                color: "#9CA3AF"; font.pixelSize: 13; wrapMode: Text.WordWrap
            }

            // 空态
            Text {
                visible: !page.bridge || page.bridge.items.length === 0
                Layout.fillWidth: true; Layout.topMargin: 8
                text: "黑名单为空"; color: "#6B7280"; font.pixelSize: 13
            }

            // 列表
            ListView {
                id: list
                visible: page.bridge && page.bridge.items.length > 0
                Layout.fillWidth: true
                // 高度跟随内容（封顶到窗口可用高度），避免短名单留大片空白
                Layout.preferredHeight: Math.min(contentHeight, page.height - 300)
                clip: true
                spacing: 6
                model: page.bridge ? page.bridge.items : []
                ScrollBar.vertical: ThemedSB {}

                delegate: Rectangle {
                    required property var modelData
                    width: list.width - 12
                    height: 44
                    radius: 6
                    property bool confirming: false
                    // 扁平单色（去掉纵向渐变凹凸感）
                    border.color: "#0dffffff"; border.width: 1
                    color: "#bf162032"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12; anchors.rightMargin: 8
                        spacing: 10
                        // 应用图标（真实 exe 图标 data_url）+ 首字母兜底
                        Rectangle {
                            Layout.alignment: Qt.AlignVCenter
                            width: 28; height: 28; radius: 6; color: "#1f3b82f6"
                            readonly property bool hasIcon: (modelData.icon !== undefined) && (modelData.icon !== "")
                            Image {
                                anchors.fill: parent; anchors.margins: 3
                                visible: parent.hasIcon
                                source: parent.hasIcon ? modelData.icon : ""
                                fillMode: Image.PreserveAspectFit; smooth: true; asynchronous: true; cache: true
                            }
                            Text {
                                anchors.centerIn: parent; visible: !parent.hasIcon
                                text: (modelData.displayName || modelData.appShort).charAt(0).toUpperCase()
                                color: "#60A5FA"; font.pixelSize: 13; font.bold: true
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            text: modelData.displayName || modelData.appShort
                            color: "#f1f5f9"; font.pixelSize: 14; font.weight: Font.Medium
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.alignment: Qt.AlignVCenter
                            text: modelData.appShort; color: "#9CA3AF"; font.pixelSize: 12
                            elide: Text.ElideRight; Layout.maximumWidth: 220
                        }

                        // 默认：移除按钮；点击 → 行内确认
                        GhostBtn {
                            visible: !confirming
                            Layout.alignment: Qt.AlignVCenter
                            label: "移除"; accent: true
                            onClicked: confirming = true
                        }
                        // 确认态：确定 / 取消
                        Row {
                            visible: confirming
                            Layout.alignment: Qt.AlignVCenter
                            spacing: 6
                            GhostBtn { label: "确定移除"; danger: true; onClicked: { page.bridge.remove(modelData.appShort); } }
                            GhostBtn { label: "取消"; onClicked: confirming = false }
                        }
                    }
                }
            }

            // 底部
            RowLayout {
                Layout.fillWidth: true
                FooterBtn { Layout.fillWidth: true; text: "关闭"; onClicked: page.closed() }
            }
        }
    }

    // ── 内联组件 ──

    // btn-ghost 文字按钮（accent=蓝字 / danger=红字 / 默认=灰字）
    component GhostBtn: Rectangle {
        property string label: ""
        property bool accent: false
        property bool danger: false
        signal clicked()
        implicitWidth: gbTxt.implicitWidth + 20; implicitHeight: 30; radius: 6
        color: gbMa.containsMouse ? "#1affffff" : "transparent"
        Text {
            id: gbTxt; anchors.centerIn: parent; text: parent.label; font.pixelSize: 13
            color: danger ? "#f87171" : (accent ? "#60A5FA" : "#cbd5e1")
        }
        MouseArea { id: gbMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.clicked() }
    }

    // btn-secondary
    component FooterBtn: Rectangle {
        property string text: ""
        signal clicked()
        implicitHeight: 40; radius: 8
        color: fbMa.containsMouse ? "#0F172A" : "#1E293B"
        border.color: "#1affffff"; border.width: 1
        Text { anchors.centerIn: parent; text: parent.text; color: "#ffffff"; font.pixelSize: 14; font.weight: Font.Medium }
        MouseArea { id: fbMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.clicked() }
    }

    component ThemedSB: ScrollBar {
        id: sb
        policy: ScrollBar.AsNeeded
        implicitWidth: 8; padding: 0
        contentItem: Rectangle {
            implicitWidth: 8; radius: 4
            color: sb.pressed ? "#d960a5fa" : (sb.hovered ? "#b33b82f6" : "#733b82f6")
        }
        background: Rectangle { implicitWidth: 8; radius: 4; color: "#660f172a" }
    }
}
