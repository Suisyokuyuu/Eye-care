import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic    // 强制 Basic 样式：Windows 原生样式不完全吃自定义 ScrollBar 外观（会画成 tk 原生条）
import QtQuick.Effects           // MultiEffect：选中 tab 的柔和阴影/蓝光

// 主仪表盘「左栏」可复用组件（Item，宿主注入 bridge）——按 web 真实 CSS 逐项还原。
// 由 AppShell 嵌入（宿主注入 LeftPanelBridge）。
// 数据全部读 panel.bridge（LeftPanelBridge）；切「应用/分类」「日/周/月」调 bridge.setView/setPeriod。
// 关键还原点见 styles.css/custom.css：tab=下划线非填充块、按钮=btn-ghost、饼图=DoughnutChart、
// 卡片=.app-list-row 三段式。外壳不自带 margin，由宿主（Window/Layout）控制留白。
Item {
    id: panel

    required property var bridge // 宿主注入 LeftPanelBridge（required：子绑定求值前已就位，避免瞬时 null）
    readonly property color primary: "#3b82f6"

    property string highlightKey: ""        // 外部联动高亮（app 名；宿主把左右栏串起来）
    signal highlight(string key)            // 本栏 hover（饼图/卡片）外发，""=离开
    signal periodSelected(string period)    // 周期切换外发，宿主用来同步右栏
    signal calendarRequested()              // 点日历按钮外发，宿主打开日期选择器
    signal appActivated(string key, bool isCategory)  // 点应用/分类卡片外发，宿主打开详情
    signal stepDay(int delta)               // 日期 ◀▶（±1 天）外发，宿主同步左右栏

    // 返回视图 tab 行在窗口坐标系中的矩形（供引导覆盖层定位聚光灯）
    function viewTabsGlobalRect() {
        var p = viewTabsWrap.mapToItem(null, 0, 0);
        return Qt.rect(p.x, p.y, viewTabsWrap.width, viewTabsWrap.height);
    }
    // 返回日期导航行在窗口坐标系中的矩形
    function dateNavGlobalRect() {
        var p = dateNavRow.mapToItem(null, 0, 0);
        return Qt.rect(p.x, p.y, dateNavRow.width, dateNavRow.height);
    }

    // 滚动列表到指定 key 对应的条目（饼图/柱状图点击联动；带缓动动画）
    function scrollToKey(k) {
        var items = panel.bridge ? panel.bridge.appList : [];
        for (var i = 0; i < items.length; i++) {
            if (items[i].key === k) {
                var itemH = 52 + 6;                // delegate height(52) + spacing(6)
                var itemTop = i * itemH;
                var itemBot = itemTop + 52;
                var curTop = list.contentY;
                var curBot = curTop + list.height;
                var target;
                if (itemTop < curTop) {
                    target = itemTop;
                } else if (itemBot > curBot) {
                    target = itemBot - list.height;
                } else {
                    return;                         // 已完全可见，不滚
                }
                target = Math.max(0, Math.min(target, Math.max(0, list.contentHeight - list.height)));
                listScrollAnim.to = target;
                listScrollAnim.restart();
                return;
            }
        }
    }
    NumberAnimation {
        id: listScrollAnim
        target: list
        property: "contentY"
        duration: 280
        easing.type: Easing.OutCubic
    }

    // 颜色随 bridge 每条数据的 r/g/b 走（web charts.js 规则已在 bridge 算好），这里只做 0-255→Qt.rgba。
    function solidOf(it)  { return Qt.rgba(it.r / 255, it.g / 255, it.b / 255, 1); }
    function dimOf(it, a) { return Qt.rgba(it.r / 255, it.g / 255, it.b / 255, a); }

    property int viewTab: 0     // 0=应用 1=分类
    property int periodTab: 0   // 0=日 1=周 2=月
    function _periodStr(t) { return t === 1 ? "week" : (t === 2 ? "month" : "day"); }
    onViewTabChanged: panel.bridge.setView(viewTab === 1 ? "category" : "app")
    onPeriodTabChanged: { panel.bridge.setPeriod(_periodStr(periodTab)); panel.periodSelected(_periodStr(periodTab)); }

    // 仅切视图/周期重播饼图入场（复刻 web chartViewEnter）；普通刷新(10s 轮询)只更新数据不重播。
    Connections {
        target: panel.bridge
        function onResetAnim() { pie.playEnter() }
    }

    // 面板外壳（复刻 panel-gradient-left）
    Rectangle {
        anchors.fill: parent
        radius: 8
        border.color: "#1affffff"
        border.width: 1
        gradient: Gradient {
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

            // ── 标题 + 日期导航 ──
            RowLayout {
                Layout.fillWidth: true
                Text { text: "应用使用统计"; color: "#f1f5f9"; font.pixelSize: 16; font.bold: true }
                Item { Layout.fillWidth: true }
                Row {
                    id: dateNavRow
                    spacing: 4
                    GhostBtn { glyph: "◀"; tip: "上一天"; onClicked: panel.stepDay(-1) }
                    Rectangle {
                        height: 34; radius: 6
                        color: "#1a212e"; border.color: "#1affffff"; border.width: 1
                        width: dateRow.width + 18; anchors.verticalCenter: parent.verticalCenter
                        // 日期文本最小宽度=标准 MM-DD 宽度，使「今日」与日期同宽，翻页时按钮不位移
                        // （用户反馈：显示【今日】时按钮变窄、鼠标无法连续翻页）。周/月范围串更宽且彼此等宽。
                        TextMetrics { id: dateMetrics; font: dateLbl.font; text: "88-88" }
                        Row {
                            id: dateRow; anchors.centerIn: parent; spacing: 6
                            Text {
                                id: dateLbl
                                text: panel.bridge.dateText; color: "#cbd5e1"; font.pixelSize: 14
                                anchors.verticalCenter: parent.verticalCenter
                                horizontalAlignment: Text.AlignHCenter
                                width: Math.max(implicitWidth, dateMetrics.width)
                            }
                            CalBtn { tip: "选择日期"; anchors.verticalCenter: parent.verticalCenter; onClicked: panel.calendarRequested() }
                        }
                    }
                    GhostBtn { glyph: "▶"; tip: "下一天"; onClicked: panel.stepDay(1) }
                }
            }

            // ── 两排 tab：应用/分类（pill：选中浅蓝底+白字+顶部蓝条）| 日/周/月（深色分段：选中浅蓝底+蓝字+底部蓝条）──
            RowLayout {
                Layout.fillWidth: true
                // 应用/分类：圆角容器(rounded-xl=12 + p-0.5)包两枚圆角 pill，整体呈圆按钮组（复刻 .view-tabs）
                Rectangle {
                    id: viewTabsWrap
                    height: 38; radius: 12
                    color: "#330f172a"; border.color: "#14ffffff"; border.width: 1
                    width: viewRow.width + 4; Layout.alignment: Qt.AlignVCenter
                    Row {
                        id: viewRow
                        x: 2; y: 2; spacing: 4
                        PillTab { label: "应用"; active: panel.viewTab === 0; onClicked: panel.viewTab = 0 }
                        PillTab { label: "分类"; active: panel.viewTab === 1; onClicked: panel.viewTab = 1 }
                    }
                }
                Item { Layout.fillWidth: true }
                // 分段控件：深色圆角容器（bg rgba(15,23,42,.45) + border-white/10），三格相连无分隔线；
                // 高亮用逐角圆角跟随容器圆角（QML clip 只裁矩形，会让首/末格露出方角，故端格 cellPos 圆角）
                Rectangle {
                    height: 38; radius: 10
                    color: "#730f172a"; border.color: "#1affffff"; border.width: 1
                    width: segRow.width + 2; Layout.alignment: Qt.AlignVCenter
                    Row {
                        id: segRow
                        x: 1; y: 1
                        SegCell { cellPos: "first"; label: "日"; active: panel.periodTab === 0; onClicked: panel.periodTab = 0 }
                        SegCell { cellPos: "mid";   label: "周"; active: panel.periodTab === 1; onClicked: panel.periodTab = 1 }
                        SegCell { cellPos: "last";  label: "月"; active: panel.periodTab === 2; onClicked: panel.periodTab = 2 }
                    }
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: "#1affffff" }

            // ── 甜甜圈 + 汇总 ──
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 8
                Layout.topMargin: 4
                Layout.bottomMargin: 4
                spacing: 24
                Item {
                    Layout.preferredWidth: 216    // web md:w-52=208，略放大
                    Layout.preferredHeight: 216
                    DoughnutChart {
                        id: pie
                        anchors.fill: parent
                        model: panel.bridge.pieModel
                        highlightName: panel.highlightKey
                        onHovered: function(name) { panel.highlight(name); }
                        onClicked: function(key, isCategory) { panel.scrollToKey(key); }
                    }
                    Column {
                        anchors.centerIn: parent; spacing: 1
                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: panel.bridge.totalText; color: "#ebffffff"; font.pixelSize: 18; font.bold: true }
                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: "总时长"; color: "#94a3b8"; font.pixelSize: 11 }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 3
                    Text { text: panel.bridge.summaryTitle; color: "#f1f5f9"; font.pixelSize: 17; font.bold: true }
                    Text { text: panel.bridge.totalText; color: panel.primary; font.pixelSize: 22; font.bold: true; Layout.bottomMargin: 4 }
                    Repeater {
                        model: panel.bridge.topLines
                        delegate: Row {
                            required property var modelData
                            spacing: 6
                            Rectangle { width: 8; height: 8; radius: 4; color: panel.solidOf(modelData); anchors.verticalCenter: parent.verticalCenter }
                            Text {
                                color: "#e6ffffff"; font.pixelSize: 13
                                text: modelData.name + " - " + modelData.dur + " " + modelData.pct + "%"
                            }
                        }
                    }
                }
            }

            // ── 可滚动应用列表（.app-list-row grid 三段式）──
            ListView {
                id: list
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 6
                // 用**数量**做 model（非绑数组）：数据刷新但条数不变时 ListView 不重置，
                // 行内 modelData 绑定原地更新，避免整列拆建导致的"重绘数据闪一下消失"。
                model: panel.bridge ? panel.bridge.appCount : 0
                ScrollBar.vertical: ThemedScrollBar {}

                delegate: Rectangle {
                    required property int index
                    readonly property var modelData: (panel.bridge && index >= 0 && index < panel.bridge.appList.length)
                        ? panel.bridge.appList[index]
                        : ({ name: "", key: "", isCategory: false, dur: "", pct: 0, sec: 0, r: 0, g: 0, b: 0, icon: "" })
                    // 联动高亮：本卡 app 名 == 当前高亮 key（饼图/柱状图 hover 也会点亮它，复刻 web .card-focus）
                    readonly property bool hl: modelData.name === panel.highlightKey && panel.highlightKey !== ""
                    // 右侧留出 8px 滚动条 + 4px 间距，避免条压住卡片（web pr-1 同理）
                    width: list.width - 16
                    x: 2
                    height: 52
                    radius: 6
                    // .panel-inner 扁平单色（去掉纵向渐变的凹凸感）；hover bg-dark-300/80；高亮 .card-focus 蓝调
                    border.color: hl ? "#803b82f6" : "#0dffffff"; border.width: 1
                    color: hl ? "#263b82f6" : (rowMa.containsMouse ? "#cc0b1120" : "#bf162032")
                    MouseArea {
                        id: rowMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onContainsMouseChanged: panel.highlight(containsMouse ? modelData.name : "")
                        onClicked: panel.appActivated(modelData.key, modelData.isCategory === true)
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12; anchors.rightMargin: 12
                        spacing: 14
                        // 名称区：图标 + 名/时长竖排
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            Rectangle {
                                width: 32; height: 32; radius: 6
                                color: panel.dimOf(modelData, 0.20)
                                readonly property bool hasIcon: (modelData.icon !== undefined) && (modelData.icon !== "")
                                // 真实应用图标（data:image/png;base64，由 bridge 经 ConfigService.get_icon 提供）
                                Image {
                                    anchors.fill: parent; anchors.margins: 4
                                    visible: parent.hasIcon
                                    source: parent.hasIcon ? modelData.icon : ""
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true; asynchronous: true; cache: true
                                }
                                // 兜底：无图标（分类/取不到）用首字母
                                Text {
                                    anchors.centerIn: parent
                                    visible: !parent.hasIcon
                                    text: modelData.name.charAt(0).toUpperCase()
                                    color: panel.solidOf(modelData); font.pixelSize: 15; font.bold: true
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1
                                Text { text: modelData.name; color: "#f5ffffff"; font.pixelSize: 14; font.weight: Font.Medium; elide: Text.ElideRight; Layout.fillWidth: true }
                                Text { text: modelData.dur; color: "#9ca3af"; font.pixelSize: 12 }
                            }
                        }
                        // meter（固定 86px，全圆角 6px 高，深底 #0B1120）
                        Rectangle {
                            Layout.preferredWidth: 86
                            height: 6; radius: 999; color: "#0B1120"; clip: true
                            Rectangle {
                                height: parent.height; radius: 999
                                width: parent.width * (modelData.pct / 100.0)
                                color: panel.solidOf(modelData)
                            }
                        }
                        // 百分比（44px 右对齐）
                        Text {
                            Layout.preferredWidth: 44
                            text: modelData.pct + "%"
                            color: "#b3ffffff"; font.pixelSize: 12; horizontalAlignment: Text.AlignRight
                        }
                    }
                }
            }
        }
    }

    // ── 内联小组件 ──

    // .btn-ghost：透明底 / hover bg-white/10 / 圆角
    component GhostBtn: Rectangle {
        property string glyph: ""
        property string tip: ""
        property bool small: false
        signal clicked()
        width: small ? 24 : 32
        height: small ? 24 : 32
        radius: 6
        color: gbMa.containsMouse ? "#1affffff" : "transparent"
        Text {
            anchors.centerIn: parent; text: parent.glyph
            color: gbMa.containsMouse ? "#ffffff" : "#cbd5e1"
            font.pixelSize: parent.small ? 12 : 13
        }
        MouseArea { id: gbMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.clicked() }
    }

    // 日历按钮（.btn-ghost 外观 + 矢量线框日历图标，复刻 fa-calendar-o；不赌 woff 字体）
    component CalBtn: Rectangle {
        id: calBtn
        property string tip: ""
        signal clicked()
        width: 28; height: 28; radius: 6
        color: cbMa.containsMouse ? "#1affffff" : "transparent"
        readonly property color line: cbMa.containsMouse ? "#ffffff" : "#e6ffffff"
        Item {
            width: 14; height: 14; anchors.centerIn: parent; scale: 1.18   // 矢量放大，跟随日/周/月变大
            // 顶部两个装订脚
            Rectangle { x: 3.2; y: 0; width: 1.4; height: 3; radius: 0.7; color: calBtn.line }
            Rectangle { x: 9.4; y: 0; width: 1.4; height: 3; radius: 0.7; color: calBtn.line }
            // 日历主体轮廓
            Rectangle { x: 0.5; y: 1.8; width: 13; height: 11.7; radius: 2; color: "transparent"; border.color: calBtn.line; border.width: 1.2 }
            // 表头分隔线
            Rectangle { x: 0.5; y: 5; width: 13; height: 1.1; color: calBtn.line }
        }
        MouseArea { id: cbMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: calBtn.clicked() }
    }

    // 应用/分类（.view-tabs .tab-active）：选中=浅蓝底 pill(radius10)+白字+顶部 2px 蓝条(inset top)；
    // 未选中=透明、rgba(255,255,255,.7) 字，hover 微亮。web px-4 py-2 text-sm。
    component PillTab: Rectangle {
        id: pt
        property string label: ""
        property bool active: false
        signal clicked()
        implicitWidth: ptTxt.implicitWidth + 32   // px-4=16/侧
        implicitHeight: 34
        radius: 10
        color: pt.active ? "#1f3b82f6" : (ptMa.containsMouse ? "#0affffff" : "transparent")
        Behavior on color { ColorAnimation { duration: 150 } }
        // 顶部 2px 蓝条（inset 0 2px 0 0 rgba(59,130,246,.5)）——顶角圆角跟随 pill
        Rectangle {
            visible: pt.active
            anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
            height: 3; color: "#803b82f6"
            radius: 0; topLeftRadius: 10; topRightRadius: 10
        }
        Text {
            id: ptTxt
            anchors.centerIn: parent; text: pt.label
            font.pixelSize: 14; font.weight: Font.Medium
            color: pt.active ? "#ffffff" : (ptMa.containsMouse ? "#d9ffffff" : "#b3ffffff")
        }
        MouseArea { id: ptMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: pt.clicked() }
    }

    // 日/周/月 分段格（.period-tabs .tab-active）：选中=浅蓝底 rgba(59,130,246,.18)+#60A5FA 字+底部 2px 蓝条；
    // 未选中=rgba(255,255,255,.62) 字。容器已是深色圆角，故格子无独立圆角/边框。web padding .45rem .875rem。
    component SegCell: Item {
        id: sc
        property string label: ""
        property bool active: false
        property string cellPos: "mid"          // first|mid|last → 端格高亮跟随容器圆角
        signal clicked()
        readonly property real rr: 9             // 容器 radius10 - border1
        implicitWidth: Math.max(48, scTxt.implicitWidth + 28)   // min-width 3rem
        implicitHeight: 36
        // 高亮底：端格用逐角圆角，避免方角露出容器圆角外
        Rectangle {
            anchors.fill: parent
            color: sc.active ? "#2e3b82f6" : (scMa.containsMouse ? "#0dffffff" : "transparent")
            Behavior on color { ColorAnimation { duration: 150 } }
            radius: 0
            topLeftRadius: sc.cellPos === "first" ? sc.rr : 0
            bottomLeftRadius: sc.cellPos === "first" ? sc.rr : 0
            topRightRadius: sc.cellPos === "last" ? sc.rr : 0
            bottomRightRadius: sc.cellPos === "last" ? sc.rr : 0
        }
        Text {
            id: scTxt
            anchors.centerIn: parent; text: sc.label
            font.pixelSize: 14; font.weight: sc.active ? Font.Medium : Font.Normal
            color: sc.active ? "#60A5FA" : (scMa.containsMouse ? "#d1ffffff" : "#9effffff")
        }
        // 底部 2px 蓝条（inset 0 -2px 0 rgba(59,130,246,.95)）——端格底角圆角
        Rectangle {
            visible: sc.active
            anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right
            height: 2; color: "#f23b82f6"
            radius: 0
            bottomLeftRadius: sc.cellPos === "first" ? sc.rr : 0
            bottomRightRadius: sc.cellPos === "last" ? sc.rr : 0
        }
        MouseArea { id: scMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: sc.clicked() }
    }

    // 列表滚动条：复刻 web .scrollbar-theme（8px 细、蓝半透明 thumb、深底 track、hover/active 加深）。
    component ThemedScrollBar: ScrollBar {
        id: sb
        policy: ScrollBar.AsNeeded
        implicitWidth: 8
        padding: 0
        contentItem: Rectangle {
            implicitWidth: 8
            radius: 4
            // rgba(59,130,246,.45)=#733b82f6 / hover .7=#b3 / active(96,165,250,.85)=#d960a5fa
            color: sb.pressed ? "#d960a5fa" : (sb.hovered ? "#b33b82f6" : "#733b82f6")
        }
        background: Rectangle {
            implicitWidth: 8
            radius: 4
            color: "#660f172a"          // rgba(15,23,42,.4)
        }
    }
}
