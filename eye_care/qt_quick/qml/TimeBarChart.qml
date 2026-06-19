import QtQuick

// 时段堆叠柱状图（复刻 web timeBarsChart：stacked bar，按 app 堆叠，颜色同饼图）。
// 用矢量 Rectangle（HiDPI 锐利，非 Canvas），每段圆角 2 + 竖向渐变；Y 轴网格线 + 刻度；
// 入场从底部生长（progress 0→1）。数据来自 RightPanelBridge：
//   labels: ["0时".."23时"] / ["周一"..] / ["1日"..]
//   series: [{ name, r, g, b, values:[与 labels 对齐的秒] }]（每个 app 一组堆叠）
//   yMax: Y 轴顶刻度秒；yTicks: [{sec,label}]；useHours: 单位是否小时（仅影响刻度文字，已在 bridge 算好）
Item {
    id: root

    property var labels: []
    property var series: []
    property real yMax: 1
    property var yTicks: []
    property real progress: 0.0
    property int enterDuration: 560
    property string highlightName: ""   // 外部联动高亮（饼图/卡片 hover 传入的 app 名）→ 非该系列变暗
    property bool useHours: false        // 单位：true=小时刻度，false=分钟刻度（由 bridge 决定）
    signal hovered(string name)         // 鼠标 hover 某段时外发（""=离开）
    signal clicked(string key)          // 点击某段外发（key = app_short；"其他"时不导航）

    // 绘图区边距
    readonly property real axisW: 42      // 左侧刻度文字宽（含「分钟/小时」单位）
    readonly property real labelH: 20     // 底部 x 标签高
    readonly property real padTop: 24     // 顶部留白：让最高刻度线不贴上边缘
    // 窗口压缩时刻度间距变小：数字(12px)+单位(10px)+间距(-1px)≈21px；低于 26px 时隐藏单位行防重叠
    readonly property bool showUnitLabel: yTicks.length <= 1
        || (plotH / (yTicks.length - 1)) >= 26
    readonly property real plotLeft: axisW
    readonly property real plotRight: width - 6
    readonly property real plotTop: padTop
    readonly property real plotBottom: height - labelH
    readonly property real plotW: Math.max(1, plotRight - plotLeft)
    readonly property real plotH: Math.max(1, plotBottom - plotTop)
    readonly property int n: labels.length

    // x 标签密度：超过 ~10 个时抽稀，避免拥挤（Chart.js 自动跳标签的近似）
    readonly property int labelStep: n > 10 ? Math.ceil(n / 8) : 1

    function valAt(li, si) {
        var s = series[si];
        if (!s || !s.values) return 0;
        var v = s.values[li];
        return v ? v : 0;
    }
    function belowAt(li, si) {           // 该段下方已堆叠的秒数
        var acc = 0;
        for (var k = 0; k < si; k++) acc += valAt(li, k);
        return acc;
    }
    // 命中测试：由鼠标 (mx,my) 找出所在柱段的 app 名（""=空）。
    // 用单一 MouseArea 统一命中，避免逐段 MouseArea 在同一柱内纵向滑过相邻段时
    // 「离开旧段(发"") 晚于 进入新段(发name)」导致高亮被清空的闪断。
    function segAt(mx, my) {
        if (n <= 0) return "";
        var rel = mx - plotLeft;
        if (rel < 0 || rel > plotW) return "";
        var sw = plotW / Math.max(1, n);
        var li = Math.floor(rel / sw);
        if (li < 0 || li >= n) return "";
        var bw = sw * 0.9 * 0.78;
        var within = rel - li * sw;
        var barX0 = (sw - bw) / 2;
        if (within < barX0 || within > barX0 + bw) return "";
        for (var si = 0; si < series.length; si++) {
            var v = valAt(li, si);
            if (v <= 0) continue;
            var below = belowAt(li, si);
            var segTop = plotBottom - (below + v) / yMax * plotH * progress;
            var segBot = plotBottom - below / yMax * plotH * progress;
            if (my >= segTop && my <= segBot) return series[si].name;
        }
        return "";
    }
    // 命中测试返回 key（app_short）：找到 name 对应的 series.key
    function keyAt(mx, my) {
        var nm = segAt(mx, my);
        if (!nm) return "";
        for (var si = 0; si < series.length; si++) {
            if (series[si].name === nm) return series[si].key || nm;
        }
        return nm;
    }

    NumberAnimation {
        id: enterAnim
        target: root; property: "progress"
        from: 0; to: 1; duration: root.enterDuration
        easing.type: Easing.InOutCubic
    }
    function playEnter() { root.progress = 0; enterAnim.restart(); }
    Component.onCompleted: playEnter()

    // ── Y 轴网格线 + 刻度文字 ──
    Repeater {
        model: root.yTicks
        delegate: Item {
            required property var modelData
            anchors.fill: parent
            readonly property real yy: root.plotBottom - (root.yMax > 0 ? (modelData.sec / root.yMax) : 0) * root.plotH
            Rectangle {
                x: root.plotLeft; y: parent.yy
                width: root.plotW; height: 1
                color: "#14ffffff"          // rgba(255,255,255,0.08)
            }
            // 每个刻度「数值 + 单位」两行（复刻 web ticks.callback 返回 [String(m),'分钟']）
            Column {
                x: 0; width: root.axisW - 5
                y: parent.yy - height / 2
                spacing: -1
                Text {
                    width: parent.width; horizontalAlignment: Text.AlignRight
                    text: modelData.label; color: "#cfffffff"; font.pixelSize: 12; font.weight: Font.Medium
                }
                Text {
                    visible: root.showUnitLabel
                    width: parent.width; horizontalAlignment: Text.AlignRight
                    text: root.useHours ? "小时" : "分钟"; color: "#8cffffff"; font.pixelSize: 10
                }
            }
        }
    }

    // ── 堆叠柱 + x 标签 ──
    Repeater {
        model: root.n
        delegate: Item {
            id: slot
            required property int index
            readonly property real slotW: root.plotW / Math.max(1, root.n)
            readonly property real barW: slotW * 0.9 * 0.78    // categoryPercentage*barPercentage 近似
            x: root.plotLeft + index * slotW
            y: 0
            width: slotW
            height: root.height

            // 每个 app 一段（自底向上堆叠，progress 控制生长）
            Repeater {
                model: root.series.length
                delegate: Rectangle {
                    id: segRect
                    required property int index
                    readonly property string segName: root.series[index].name
                    readonly property real v: root.valAt(slot.index, index)
                    readonly property real below: root.belowAt(slot.index, index)
                    readonly property real segH: (root.yMax > 0 ? v / root.yMax : 0) * root.plotH * root.progress
                    readonly property real belowH: (root.yMax > 0 ? below / root.yMax : 0) * root.plotH * root.progress
                    visible: v > 0 && segH > 0.3
                    width: slot.barW
                    x: (slot.slotW - slot.barW) / 2
                    height: segH
                    y: root.plotBottom - belowH - segH
                    radius: 2
                    antialiasing: true
                    border.color: "#1fffffff"   // rgba(255,255,255,0.12)
                    border.width: 0.7
                    // 联动：有高亮且非本系列 → 变暗
                    opacity: (root.highlightName === "" || root.highlightName === segName) ? 1.0 : 0.3
                    Behavior on opacity { NumberAnimation { duration: 120 } }
                    gradient: Gradient {
                        orientation: Gradient.Vertical
                        GradientStop { position: 0.0; color: Qt.rgba(root.series[index].r/255, root.series[index].g/255, root.series[index].b/255, 0.85) }
                        GradientStop { position: 1.0; color: Qt.rgba(root.series[index].r/255, root.series[index].g/255, root.series[index].b/255, 0.50) }
                    }
                }
            }

            // x 标签（抽稀）
            Text {
                visible: (slot.index % root.labelStep) === 0
                anchors.horizontalCenter: parent.horizontalCenter
                y: root.plotBottom + 4
                text: root.n > slot.index ? root.labels[slot.index] : ""
                color: "#99ffffff"; font.pixelSize: 11
            }
        }
    }

    // 统一命中 MouseArea（盖在所有柱段之上）：纵向滑过同一柱内相邻段也连续报告正确 app，无闪断。
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton
        cursorShape: root.segAt(mouseX, mouseY) !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor
        onPositionChanged: root.hovered(root.segAt(mouseX, mouseY))
        onExited: root.hovered("")
        onClicked: function(mouse) {
            var key = root.keyAt(mouse.x, mouse.y);
            // "其他" 或空 key 不导航
            if (!key || key === "其他") return;
            root.clicked(key);
        }
    }
}
