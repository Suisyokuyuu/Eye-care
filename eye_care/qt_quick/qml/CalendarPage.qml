import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

// 日期选择器（复刻 web #calendarModal）：单月网格 + 有数据日子高亮 + **范围选择**（先点开始→再点结束，同天即单日）。
// 数据走 contextProperty calendarBridge。确定→发 pickedRange(start,end)，外壳：同天→setDate，跨天→setRange。
Item {
    id: page
    anchors.fill: parent
    // 渐入渐出
    visible: opacity > 0.01
    opacity: open ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    z: 105

    required property var bridge          // CalendarBridge
    property bool open: false
    signal closed()
    signal pickedRange(string start, string end)
    // 范围是否跨天（端点是否需要半边连接带）
    readonly property bool isRange: page.bridge && page.bridge.rangeStart !== page.bridge.rangeEnd

    onOpenChanged: if (open) bridge.reload()

    Rectangle {
        anchors.fill: parent; color: "#99000000"
        MouseArea { anchors.fill: parent; onClicked: page.closed(); onWheel: function(wheel){ wheel.accepted = true } }
    }

    Rectangle {
        anchors.centerIn: parent
        width: 360
        height: col.implicitHeight + 8
        radius: 12
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: "#1c2637" }
            GradientStop { position: 1.0; color: "#121a28" }
        }
        border.color: "#1affffff"; border.width: 1
        clip: true
        MouseArea { anchors.fill: parent }

        ColumnLayout {
            id: col
            anchors.fill: parent; spacing: 0

            // 标题栏
            RowLayout {
                Layout.fillWidth: true; Layout.leftMargin: 20; Layout.rightMargin: 14; Layout.topMargin: 14; Layout.bottomMargin: 6
                Text { text: "选择日期"; color: "#ffffff"; font.pixelSize: 18; font.bold: true }
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
            Rectangle { Layout.fillWidth: true; height: 1; color: "#1affffff" }

            // 范围提示 + 当前选择
            ColumnLayout {
                Layout.fillWidth: true; Layout.leftMargin: 20; Layout.rightMargin: 20; Layout.topMargin: 8; spacing: 1
                Text { text: "选开始 → 再选结束（同天即单日）"; color: "#94a3b8"; font.pixelSize: 13 }
                Text { text: page.bridge ? page.bridge.rangeLabel : ""; color: "#60A5FA"; font.pixelSize: 14; font.weight: Font.DemiBold }
            }

            // 月份导航
            RowLayout {
                Layout.fillWidth: true; Layout.leftMargin: 20; Layout.rightMargin: 20; Layout.topMargin: 12; Layout.bottomMargin: 4
                NavBtn { glyph: "◀"; onClicked: page.bridge.prev() }
                Item { Layout.fillWidth: true }
                Text { text: page.bridge ? page.bridge.monthTitle : ""; color: "#fff"; font.pixelSize: 14; font.weight: Font.Medium }
                Item { Layout.fillWidth: true }
                NavBtn { glyph: "▶"; onClicked: page.bridge.next() }
            }

            // 周表头
            Row {
                Layout.alignment: Qt.AlignHCenter
                Repeater {
                    model: page.bridge ? page.bridge.weekHeaders : []
                    delegate: Item {
                        required property var modelData
                        width: 40; height: 24
                        Text { anchors.centerIn: parent; text: modelData; color: "#94a3b8"; font.pixelSize: 12 }
                    }
                }
            }

            // 日期网格 6x7
            Grid {
                Layout.alignment: Qt.AlignHCenter; Layout.bottomMargin: 6
                columns: 7; rowSpacing: 2; columnSpacing: 0
                Repeater {
                    model: page.bridge ? page.bridge.cells : []
                    delegate: Item {
                        required property var modelData
                        width: 40; height: 38
                        // 范围连接带（底层）：中间整格；端点半边（朝向区间内侧）
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            height: 32; color: "#242f6fd6"
                            visible: modelData.inRange || (page.isRange && (modelData.rangeStart || modelData.rangeEnd))
                            x: modelData.inRange ? 0 : (modelData.rangeStart ? 20 : 0)
                            width: modelData.inRange ? 40 : 20
                        }
                        Rectangle {
                            anchors.centerIn: parent
                            width: 32; height: 32; radius: 8
                            color: modelData.selected ? "#3B82F6"
                                 : (cMa.containsMouse && modelData.inMonth ? "#1f3b82f6" : "transparent")
                            border.color: modelData.isToday && !modelData.selected ? "#60A5FA" : "transparent"
                            border.width: 1
                            Text {
                                anchors.centerIn: parent; text: modelData.day
                                font.pixelSize: 13
                                color: modelData.selected ? "#ffffff"
                                     : (modelData.inMonth ? "#e5e7eb" : "#475569")
                            }
                            // 有数据小圆点
                            Rectangle {
                                visible: modelData.hasData && !modelData.selected
                                width: 4; height: 4; radius: 2
                                color: "#60A5FA"
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.bottom: parent.bottom; anchors.bottomMargin: 3
                            }
                        }
                        MouseArea {
                            id: cMa; anchors.fill: parent; hoverEnabled: true
                            cursorShape: modelData.inMonth ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: if (modelData.inMonth) page.bridge.select(modelData.iso)
                        }
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: "#1affffff" }
            // 底部
            RowLayout {
                Layout.fillWidth: true; Layout.margins: 14; spacing: 8
                Rectangle {
                    width: 68; height: 36; radius: 8; color: rstMa.containsMouse ? "#1affffff" : "transparent"
                    Text { anchors.centerIn: parent; text: "清空"; color: "#cbd5e1"; font.pixelSize: 14 }
                    MouseArea { id: rstMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.bridge.reset() }
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 84; height: 36; radius: 8; color: cancMa.containsMouse ? "#0F172A" : "#1E293B"; border.color: "#1affffff"; border.width: 1
                    Text { anchors.centerIn: parent; text: "取消"; color: "#fff"; font.pixelSize: 14 }
                    MouseArea { id: cancMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.closed() }
                }
                Rectangle {
                    width: 84; height: 36; radius: 8; color: okMa.containsMouse ? "#1E40AF" : "#3B82F6"
                    Text { anchors.centerIn: parent; text: "确定"; color: "#fff"; font.pixelSize: 14; font.weight: Font.Medium }
                    MouseArea { id: okMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { page.pickedRange(page.bridge.rangeStart, page.bridge.rangeEnd); page.closed(); } }
                }
            }
        }
    }

    component NavBtn: Rectangle {
        property string glyph: ""
        signal clicked()
        width: 32; height: 32; radius: 6
        color: nbMa.containsMouse ? "#1affffff" : "transparent"
        Text { anchors.centerIn: parent; text: parent.glyph; color: nbMa.containsMouse ? "#fff" : "#cbd5e1"; font.pixelSize: 13 }
        MouseArea { id: nbMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.clicked() }
    }
}
