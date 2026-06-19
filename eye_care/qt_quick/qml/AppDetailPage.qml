import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

// 应用详情（step3，复刻 web #appDetailModal）：左=使用时间段(24h 柱图)，右=类别(可加新类)/显示名/前台自动勿扰/排除计时。
// 数据走 contextProperty appsBridge.detail（openDetail 后填充）。保存 saveDetail、排除 excludeApp。
Item {
    id: page
    anchors.fill: parent
    // 渐入渐出
    visible: opacity > 0.01
    opacity: open ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    z: 110                        // 比 AppSettingsPage(100) 高，叠在其上
    clip: true

    required property var bridge          // AppsBridge
    property bool open: false
    signal closed()

    // 本地编辑态
    property string catSel: "其他"
    property string dispName: ""
    property bool autoDnd: false
    property bool confirming: false

    function load() {
        var d = page.bridge ? page.bridge.detail : null;
        if (!d) return;
        catSel = d.category || "其他";
        dispName = d.displayNameOverride || "";
        autoDnd = !!d.autoDnd;
        confirming = false;
        usageChart.playEnter();      // 柱状图增长动画（每次打开/换应用重播）
    }
    onOpenChanged: if (open) load()
    Connections { target: page.bridge; function onDetailChanged() { if (page.open) page.load() } }

    function _detail() { return page.bridge ? page.bridge.detail : ({}); }

    Rectangle {
        anchors.fill: parent; color: "#b3000000"
        MouseArea { anchors.fill: parent; onClicked: page.closed(); onWheel: function(wheel){ wheel.accepted = true } }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 64, 760)
        height: Math.min(parent.height - 80, 496)
        radius: 12; color: "#0F172A"; border.color: "#1affffff"; border.width: 1
        // 卡片轻微放大渐入（配合 page 的渐显，复刻 web animate-slide-up 的弹出感）
        scale: page.open ? 1.0 : 0.95
        Behavior on scale { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
        MouseArea { anchors.fill: parent }

        ColumnLayout {
            anchors.fill: parent; spacing: 0

            // header
            RowLayout {
                Layout.fillWidth: true; Layout.margins: 16; spacing: 10
                Rectangle {
                    Layout.alignment: Qt.AlignVCenter
                    width: 36; height: 36; radius: 6; color: "#1f3b82f6"
                    readonly property string iconUrl: page._detail().icon || ""
                    readonly property bool hasIcon: iconUrl !== ""
                    Image {
                        anchors.fill: parent; anchors.margins: 4
                        visible: parent.hasIcon
                        source: parent.hasIcon ? parent.iconUrl : ""
                        fillMode: Image.PreserveAspectFit; smooth: true; asynchronous: true; cache: true
                    }
                    Text {
                        anchors.centerIn: parent; visible: !parent.hasIcon
                        text: (page._detail().title || page._detail().appShort || "?").charAt(0).toUpperCase()
                        color: "#60A5FA"; font.pixelSize: 17; font.bold: true
                    }
                }
                Text {
                    text: page._detail().title || page._detail().appShort || "应用详情"
                    color: "#ffffff"; font.pixelSize: 19; font.bold: true; elide: Text.ElideRight
                    Layout.maximumWidth: 320
                }
                Text {
                    text: page._detail().path || ""
                    color: "#6B7280"; font.pixelSize: 11; elide: Text.ElideMiddle
                    Layout.fillWidth: true; Layout.alignment: Qt.AlignVCenter
                }
                CloseX { onClicked: page.closed() }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: "#1affffff" }

            // body：左图 + 右设置
            RowLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.margins: 16; spacing: 20

                // 左：使用时间段（近 7 天逐日柱图，复刻 web appTimeChart）
                ColumnLayout {
                    Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 1; spacing: 8
                    Text { text: "使用时间段"; color: "#cbd5e1"; font.pixelSize: 13; font.weight: Font.DemiBold }
                    Rectangle {
                        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 200
                        radius: 8; color: "#80111a28"; border.color: "#0dffffff"; border.width: 1
                        DailyChart { id: usageChart; anchors.fill: parent; anchors.margins: 12; series: page._detail().daily || [] }
                    }
                }

                // 右：设置
                ColumnLayout {
                    Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 1; spacing: 14

                    Text { text: "设置"; color: "#cbd5e1"; font.pixelSize: 13; font.weight: Font.DemiBold }

                    // 应用类别（下拉 + 加新类）
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 6
                        Text { text: "应用类别"; color: "#D1D5DB"; font.pixelSize: 13; font.weight: Font.Medium }
                        Rectangle {
                            id: catBtn
                            Layout.fillWidth: true; height: 38; radius: 8
                            color: "#1E293B"; border.color: catPop.visible ? "#803b82f6" : "#1affffff"; border.width: 1
                            Text { anchors.left: parent.left; anchors.leftMargin: 12; anchors.verticalCenter: parent.verticalCenter; text: page.catSel; color: "#e5e7eb"; font.pixelSize: 14 }
                            Text { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; text: "▾"; color: "#9CA3AF"; font.pixelSize: 12 }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: catPop.open() }
                            Popup {
                                id: catPop
                                y: catBtn.height + 4; width: catBtn.width; padding: 4
                                background: Rectangle { color: "#1E293B"; radius: 8; border.color: "#1affffff"; border.width: 1 }
                                contentItem: ColumnLayout {
                                    spacing: 2
                                    ListView {
                                        Layout.fillWidth: true
                                        implicitHeight: Math.min(contentHeight, 168)
                                        clip: true; interactive: true
                                        model: page.bridge ? page.bridge.categories : []
                                        ScrollBar.vertical: ThemedSB {}
                                        delegate: Rectangle {
                                            required property var modelData
                                            width: ListView.view.width; height: 32; radius: 6
                                            readonly property bool on: modelData === page.catSel
                                            color: itMa.containsMouse ? "#1f3b82f6" : (on ? "#142f6fd6" : "transparent")
                                            Text { anchors.left: parent.left; anchors.leftMargin: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData; color: on ? "#60A5FA" : "#e5e7eb"; font.pixelSize: 14 }
                                            MouseArea { id: itMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { page.catSel = modelData; catPop.close(); } }
                                        }
                                    }
                                    Rectangle { Layout.fillWidth: true; height: 1; color: "#1affffff" }
                                    RowLayout {
                                        Layout.fillWidth: true; spacing: 6
                                        Rectangle {
                                            Layout.fillWidth: true; height: 32; radius: 6
                                            color: "#0F172A"; border.color: "#1affffff"; border.width: 1
                                            TextField {
                                                id: newCatTf
                                                anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8
                                                verticalAlignment: TextInput.AlignVCenter
                                                color: "#fff"; font.pixelSize: 13; selectByMouse: true
                                                placeholderText: "新分类名"; placeholderTextColor: "#6B7280"
                                                background: Item {}
                                            }
                                        }
                                        Rectangle {
                                            width: addTxt.implicitWidth + 16; height: 32; radius: 6
                                            color: addMa.containsMouse ? "#1affffff" : "transparent"
                                            Text { id: addTxt; anchors.centerIn: parent; text: "添加"; color: "#60A5FA"; font.pixelSize: 13 }
                                            MouseArea {
                                                id: addMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                                onClicked: {
                                                    var n = newCatTf.text.trim();
                                                    if (n !== "") { page.bridge.addCategory(n); page.catSel = n; newCatTf.text = ""; catPop.close(); }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // 显示名
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 6
                        Text { text: "显示名（别名）"; color: "#D1D5DB"; font.pixelSize: 13; font.weight: Font.Medium }
                        Rectangle {
                            Layout.fillWidth: true; height: 38; radius: 8
                            color: "#1E293B"; border.color: dispTf.activeFocus ? "#803b82f6" : "#1affffff"; border.width: dispTf.activeFocus ? 2 : 1
                            TextField {
                                id: dispTf
                                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                                verticalAlignment: TextInput.AlignVCenter
                                color: "#fff"; font.pixelSize: 14; selectByMouse: true
                                placeholderText: "留空则用默认名"; placeholderTextColor: "#6B7280"
                                background: Item {}
                                text: page.dispName
                                onTextChanged: page.dispName = text
                            }
                        }
                    }

                    // 前台自动勿扰
                    RowLayout {
                        Layout.fillWidth: true; spacing: 10
                        Rectangle {
                            Layout.alignment: Qt.AlignTop; Layout.topMargin: 2
                            width: 18; height: 18; radius: 4
                            color: page.autoDnd ? "#3B82F6" : "#0B1120"
                            border.color: page.autoDnd ? "#3B82F6" : "#33ffffff"; border.width: 1
                            Text { anchors.centerIn: parent; visible: page.autoDnd; text: "✓"; color: "#fff"; font.pixelSize: 12 }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: page.autoDnd = !page.autoDnd }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 1
                            Text { text: "前台自动勿扰"; color: "#e5e7eb"; font.pixelSize: 13; font.weight: Font.Medium }
                            Text { text: "该应用在前台时自动进入勿扰，切换走后恢复。"; color: "#6B7280"; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        }
                    }

                    // 排除计时（行内二次确认）——紧跟「前台自动勿扰」，复刻原版 space-y-4 + pt-2，无弹簧间隙
                    Rectangle {
                        Layout.fillWidth: true; height: 40; radius: 8
                        color: "#1aef4444"; border.color: "#ccef4444"; border.width: 2
                        visible: !page.confirming
                        Text { anchors.centerIn: parent; text: "排除该应用计时"; color: "#f87171"; font.pixelSize: 13; font.weight: Font.Medium }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: page.confirming = true }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 6; visible: page.confirming
                        Text { text: "排除将删除该应用全部数据，且不再记录、不再触发休息。可在黑名单恢复记录但历史不恢复。确定？"; color: "#f87171"; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 8
                            Rectangle {
                                Layout.fillWidth: true; height: 36; radius: 8; color: exMa.containsMouse ? "#dc2626" : "#ef4444"
                                Text { anchors.centerIn: parent; text: "确定排除"; color: "#fff"; font.pixelSize: 13; font.weight: Font.Medium }
                                MouseArea { id: exMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { page.bridge.excludeApp(page._detail().appShort); page.closed(); } }
                            }
                            Rectangle {
                                Layout.fillWidth: true; height: 36; radius: 8; color: cxMa.containsMouse ? "#0F172A" : "#1E293B"; border.color: "#1affffff"; border.width: 1
                                Text { anchors.centerIn: parent; text: "取消"; color: "#fff"; font.pixelSize: 13 }
                                MouseArea { id: cxMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.confirming = false }
                            }
                        }
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: "#1affffff" }
            // footer
            RowLayout {
                Layout.fillWidth: true; Layout.margins: 16; spacing: 8
                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 96; height: 38; radius: 8; color: cancMa.containsMouse ? "#0F172A" : "#1E293B"; border.color: "#1affffff"; border.width: 1
                    Text { anchors.centerIn: parent; text: "取消"; color: "#fff"; font.pixelSize: 14; font.weight: Font.Medium }
                    MouseArea { id: cancMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.closed() }
                }
                Rectangle {
                    width: 96; height: 38; radius: 8; color: saveMa.containsMouse ? "#1E40AF" : "#3B82F6"
                    Text { anchors.centerIn: parent; text: "应用"; color: "#fff"; font.pixelSize: 14; font.weight: Font.Medium }
                    MouseArea {
                        id: saveMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            page.bridge.saveDetail({ "appShort": page._detail().appShort, "category": page.catSel, "displayName": page.dispName, "autoDnd": page.autoDnd });
                            page.closed();
                        }
                    }
                }
            }
        }
    }

    // ── 内联组件 ──
    component CloseX: Rectangle {
        signal clicked()
        width: 30; height: 30; radius: 6; Layout.alignment: Qt.AlignVCenter
        color: xMa.containsMouse ? "#1affffff" : "transparent"
        Item {
            anchors.centerIn: parent; width: 14; height: 14
            Rectangle { anchors.centerIn: parent; width: 15; height: 1.5; radius: 0.75; color: xMa.containsMouse ? "#ffffff" : "#9CA3AF"; rotation: 45 }
            Rectangle { anchors.centerIn: parent; width: 15; height: 1.5; radius: 0.75; color: xMa.containsMouse ? "#ffffff" : "#9CA3AF"; rotation: -45 }
        }
        MouseArea { id: xMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.clicked() }
    }
    component ThemedSB: ScrollBar {
        id: sb
        policy: ScrollBar.AsNeeded; implicitWidth: 8; padding: 0
        contentItem: Rectangle { implicitWidth: 8; radius: 4; color: sb.pressed ? "#d960a5fa" : (sb.hovered ? "#b33b82f6" : "#733b82f6") }
        background: Rectangle { implicitWidth: 8; radius: 4; color: "#660f172a" }
    }

    // 逐日使用柱图（复刻 web appTimeChart：range_start..range_end 每天一根，渐变柱 + 顶部分钟数 + 日期标签）。
    // 复刻 web Chart.js y 轴：左侧分钟刻度 + 横向网格线（与「屏幕时间统计」图一致）。
    component DailyChart: Item {
        id: dc
        property var series: []     // [{label:"M/D", sec}]
        readonly property int n: series ? series.length : 0
        readonly property real maxSec: {
            var m = 0;
            for (var i = 0; i < dc.n; i++) m = Math.max(m, (series[i] && series[i].sec) || 0);
            return m;
        }
        // Y 轴以分钟计。关键：niceMax = step * tickCount（step 取漂亮整数 1/2/5/10…），
        // 保证每格刻度都是整数分钟、等距、不丢线（旧版 round(niceMax*i/4) 在 niceMax 不被 4 整除时
        // 会把 2.5→3 丢掉「2」线，正是 cmd 缺第三根线的原因）。
        readonly property int maxMin: Math.max(1, Math.ceil(dc.maxSec / 60))
        readonly property int tickCount: 4
        readonly property int step: {
            var raw = Math.ceil(dc.maxMin / dc.tickCount);   // 每格至少要容纳的分钟
            var pow = 1;
            while (raw > 10 * pow) pow *= 10;
            var u = raw / pow;
            var nice = (u <= 1 ? 1 : (u <= 2 ? 2 : (u <= 5 ? 5 : 10)));
            return nice * pow;
        }
        readonly property int niceMax: dc.step * dc.tickCount
        readonly property var ticks: {
            var arr = [];
            for (var i = 0; i <= dc.tickCount; i++) arr.push(dc.step * i);
            return arr;
        }

        readonly property real axisW: 42                       // 左侧分钟刻度宽（含「分钟」单位）
        readonly property real labelH: 18                      // 底部日期标签高
        readonly property real padTop: 14                      // 顶部留白（柱顶分钟数）
        readonly property real plotLeft: axisW
        readonly property real plotTop: padTop
        readonly property real plotBottom: height - labelH
        readonly property real plotW: Math.max(1, width - axisW)
        readonly property real plotH: Math.max(1, plotBottom - plotTop)

        // 增长动画：progress 0→1，柱高随之生长（复刻 web 图表入场）
        property real progress: 1.0
        NumberAnimation { id: growAnim; target: dc; property: "progress"; from: 0; to: 1; duration: 520; easing.type: Easing.OutCubic }
        function playEnter() { dc.progress = 0; growAnim.restart(); }
        Component.onCompleted: playEnter()

        // ── Y 轴网格线 + 分钟刻度 ──
        Repeater {
            model: dc.ticks
            delegate: Item {
                required property var modelData
                anchors.fill: parent
                readonly property real yy: dc.plotBottom - (dc.niceMax > 0 ? modelData / dc.niceMax : 0) * dc.plotH
                Rectangle { x: dc.plotLeft; y: parent.yy; width: dc.plotW; height: 1; color: "#0dffffff" }
                // 每档「数值 + 分钟」两行（与屏幕时间统计图一致）
                Column {
                    x: 0; width: dc.axisW - 5
                    y: parent.yy - height / 2
                    spacing: -1
                    Text {
                        width: parent.width; horizontalAlignment: Text.AlignRight
                        text: modelData; color: "#cfffffff"; font.pixelSize: 12; font.weight: Font.Medium
                    }
                    Text {
                        width: parent.width; horizontalAlignment: Text.AlignRight
                        text: "分钟"; color: "#8cffffff"; font.pixelSize: 10
                    }
                }
            }
        }

        // ── 柱 + 顶部分钟数 + 日期标签 ──
        Row {
            id: barsRow
            x: dc.plotLeft; y: 0
            width: dc.plotW; height: dc.height
            spacing: dc.n > 1 ? Math.min(20, dc.plotW * 0.03) : 0
            Repeater {
                model: dc.series
                delegate: Item {
                    id: cell
                    required property var modelData
                    width: dc.n > 0 ? (dc.plotW - barsRow.spacing * (dc.n - 1)) / dc.n : 0
                    height: dc.height
                    readonly property real v: (modelData && modelData.sec) || 0
                    // 柱顶分钟数（>0 才显示）
                    Text {
                        visible: cell.v > 0
                        anchors.horizontalCenter: bar.horizontalCenter
                        y: Math.max(0, bar.y - height - 2)
                        text: Math.round(cell.v / 60) + ""
                        color: "#cccbd5e1"; font.pixelSize: 11; font.weight: Font.DemiBold
                    }
                    Rectangle {
                        id: bar
                        width: Math.min(cell.width, 28)
                        anchors.horizontalCenter: parent.horizontalCenter
                        y: dc.plotBottom - height
                        height: Math.max(cell.v > 0 ? 3 : 0, (dc.niceMax > 0 ? (cell.v / 60) / dc.niceMax : 0) * dc.plotH) * dc.progress
                        radius: 3; topLeftRadius: 4; topRightRadius: 4
                        gradient: Gradient {
                            orientation: Gradient.Vertical
                            GradientStop { position: 0.0; color: "#e63b82f6" }
                            GradientStop { position: 1.0; color: "#553b82f6" }
                        }
                    }
                    // 日期标签
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        y: dc.plotBottom + 3
                        text: (modelData && modelData.label) || ""
                        color: "#a6ffffff"; font.pixelSize: 11; font.weight: Font.Medium
                    }
                }
            }
        }
        // 基线（最底刻度线已由 ticks[0] 画出；此处加粗一条更醒目）
        Rectangle { x: dc.plotLeft; y: dc.plotBottom; width: dc.plotW; height: 1; color: "#1affffff" }
        // 空态
        Text {
            visible: dc.n === 0
            anchors.centerIn: parent
            text: "暂无使用记录"; color: "#6B7280"; font.pixelSize: 12
        }
    }
}
