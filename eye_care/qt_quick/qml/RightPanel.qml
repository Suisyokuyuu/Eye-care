import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Effects

// 主仪表盘「右栏」可复用组件（Item，宿主注入 bridge）——按 web 真实 CSS/结构还原。
// 上：屏幕时间统计（TimeBarChart + Top4）；下：仪表卡片网格 + 立刻休息。数据全部读 panel.bridge。
// 外壳不自带 margin，由宿主（Window/Layout）控制留白。
Item {
    id: panel

    required property var bridge // 宿主注入 RightPanelBridge（required：子绑定求值前已就位，避免瞬时 null）
    signal restRequested()       // 「立刻休息」点击 → 宿主接 showRestOverlay

    property string highlightKey: ""    // 外部联动高亮（app 名；宿主把左右栏串起来）
    signal highlight(string key)        // 本栏 hover（柱状图）外发，""=离开
    signal appActivated(string key, bool isCategory)  // 点击柱状图 app 段外发 → 宿主打开详情

    function solidOf(it) { return Qt.rgba(it.r / 255, it.g / 255, it.b / 255, 1); }
    // 返回时段柱状图卡片在窗口坐标系中的矩形（供引导覆盖层定位聚光灯）
    function barChartGlobalRect() {
        var p = barChartCard.mapToItem(null, 0, 0);
        return Qt.rect(p.x, p.y, barChartCard.width, barChartCard.height);
    }
    // 返回「立刻休息」按钮在窗口坐标系中的矩形
    function restBtnGlobalRect() {
        var p = restBtn.mapToItem(null, 0, 0);
        return Qt.rect(p.x, p.y, restBtn.width, restBtn.height);
    }

    // 仅切周期重播柱状图入场；普通刷新(10s 轮询)只更新数据不重播。
    Connections {
        target: panel.bridge
        function onResetAnim() { bars.playEnter() }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        // ══ 上：屏幕时间统计 ══
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 8
            border.color: "#1affffff"; border.width: 1
            gradient: Gradient {                 // 与左栏统一：顶部偏亮蓝灰、向下渐深（避免右栏顶部发黑、左右不一致）
                orientation: Gradient.Vertical
                GradientStop { position: 0.00; color: "#26344b" }
                GradientStop { position: 0.25; color: "#1c2637" }
                GradientStop { position: 0.55; color: "#121a28" }
                GradientStop { position: 1.00; color: "#141e2d" }
            }
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "屏幕时间统计"; color: "#f1f5f9"; font.pixelSize: 16; font.bold: true }
                    Item { Layout.fillWidth: true }
                    Text { text: panel.bridge.rangeLabel; color: "#9ca3af"; font.pixelSize: 12 }
                }

                // 图表卡片（panel-inner）
                Rectangle {
                    id: barChartCard
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 160
                    radius: 6
                    border.color: "#0dffffff"; border.width: 1
                    gradient: Gradient {
                        orientation: Gradient.Vertical
                        GradientStop { position: 0.0; color: "#991e293b" }
                        GradientStop { position: 1.0; color: "#d90f172a" }
                    }
                    TimeBarChart {
                        id: bars
                        anchors.fill: parent
                        anchors.margins: 10
                        labels: panel.bridge.barLabels
                        series: panel.bridge.barSeries
                        yMax: panel.bridge.yMax
                        yTicks: panel.bridge.yTicks
                        useHours: panel.bridge.useHours
                        highlightName: panel.highlightKey
                        onHovered: function(name) { panel.highlight(name); }
                        onClicked: function(key) { panel.appActivated(key, false); }
                    }
                }

                // Top4 分布
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: panel.bridge.top4
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            spacing: 1
                            Text {
                                text: modelData.name; color: panel.solidOf(modelData)
                                font.pixelSize: 12; elide: Text.ElideRight; Layout.fillWidth: true
                            }
                            Text { text: modelData.val; color: "#f1f5f9"; font.pixelSize: 13; font.weight: Font.Medium }
                        }
                    }
                }
            }
        }

        // ══ 下：仪表卡片 + 立刻休息 ══
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: dashCol.implicitHeight + 24
            radius: 8
            border.color: "#1affffff"; border.width: 1
            gradient: Gradient {                 // 与左栏统一
                orientation: Gradient.Vertical
                GradientStop { position: 0.00; color: "#26344b" }
                GradientStop { position: 0.25; color: "#1c2637" }
                GradientStop { position: 0.55; color: "#121a28" }
                GradientStop { position: 1.00; color: "#141e2d" }
            }
            ColumnLayout {
                id: dashCol
                anchors.fill: parent
                anchors.margins: 12
                spacing: 14

                // KPI 卡片网格（第一排 4 张 + 第二排整宽 4 小项）
                GridLayout {
                    Layout.fillWidth: true
                    columns: 4
                    rowSpacing: 12; columnSpacing: 12
                    KpiCard { Layout.fillWidth: true; label: "已连续用眼"; value: panel.bridge.continuousText }
                    KpiCard { Layout.fillWidth: true; label: "今日屏幕时间"; value: panel.bridge.totalText }
                    KpiCard { Layout.fillWidth: true; label: "休息完成率"; value: panel.bridge.rateText }
                    KpiCard { Layout.fillWidth: true; label: "最长连续专注"; value: panel.bridge.focusText }
                    // 第二排：整宽一张卡，内含 4 小项
                    Rectangle {
                        Layout.columnSpan: 4
                        Layout.fillWidth: true
                        radius: 12
                        color: rowMa.containsMouse ? "#0fffffff" : "#0affffff"
                        border.color: rowMa.containsMouse ? "#1affffff" : "#14ffffff"; border.width: 1
                        implicitHeight: 60
                        MouseArea { id: rowMa; anchors.fill: parent; hoverEnabled: true }
                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 16
                            SmallCell { Layout.fillWidth: true; label: "提醒频率"; value: panel.bridge.reminderText }
                            SmallCell { Layout.fillWidth: true; label: "休息时长"; value: panel.bridge.durationText }
                            SmallCell { Layout.fillWidth: true; label: "今日休息"; value: panel.bridge.doneText }
                            SmallCell { Layout.fillWidth: true; label: "今日跳过"; value: panel.bridge.skipText }
                        }
                    }
                }

                // 立刻休息（btn-primary：整宽 46 高、圆角 12、16px 600）
                Rectangle {
                    id: restBtn
                    Layout.fillWidth: true
                    Layout.preferredHeight: 46
                    radius: 12
                    color: restMa.pressed ? "#1e40af" : (restMa.containsMouse ? "#1e40af" : "#3b82f6")
                    Behavior on color { ColorAnimation { duration: 150 } }
                    Text { anchors.centerIn: parent; text: "立刻休息"; color: "#ffffff"; font.pixelSize: 16; font.weight: Font.DemiBold }
                    MouseArea {
                        id: restMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: panel.restRequested()
                    }
                }
            }
        }
    }

    // ── 内联组件 ──

    // KPI 卡片：.dashboard-card--kpi（label 11/.65 + value 18 bold 蓝）
    component KpiCard: Rectangle {
        id: card
        property string label: ""
        property string value: ""
        radius: 12
        implicitHeight: 64
        color: kpiMa.containsMouse ? "#0fffffff" : "#0affffff"
        border.color: kpiMa.containsMouse ? "#1affffff" : "#14ffffff"; border.width: 1
        MouseArea { id: kpiMa; anchors.fill: parent; hoverEnabled: true }
        Column {
            anchors.left: parent.left; anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 14; anchors.rightMargin: 14
            spacing: 6
            Text { text: card.label; color: "#a6ffffff"; font.pixelSize: 13; width: parent.width; elide: Text.ElideRight }
            Text { text: card.value; color: "#3b82f6"; font.pixelSize: 19; font.bold: true }
        }
    }

    // 第二排小项：label-sm 11/.6 + value-sm 14/600 白
    component SmallCell: ColumnLayout {
        id: cell
        property string label: ""
        property string value: ""
        spacing: 2
        Text { text: cell.label; color: "#99ffffff"; font.pixelSize: 13; elide: Text.ElideRight; Layout.fillWidth: true }
        Text { text: cell.value; color: "#f3ffffff"; font.pixelSize: 15; font.weight: Font.DemiBold }
    }
}
