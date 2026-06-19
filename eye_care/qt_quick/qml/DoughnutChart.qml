import QtQuick
import QtQuick.Shapes

// QML 甜甜圈——用 Qt Quick Shapes（矢量 GPU 渲染）1:1 复刻 web Chart.js doughnut 质感。
// 为什么不是 Canvas：Canvas 在 HiDPI 屏(dpr 1.25/2)默认不按设备像素放大渲染，边缘发糊 =
// "塑料/tk 感"主因；Shapes 是矢量、天然锐利，RadialGradient 原生支持径向渐变，动画走属性
// 绑定（progress 驱动 sweep）天然丝滑，无需手动重绘。
// 复刻点（对照 charts.js）：
//   - 径向渐变 makeRadialGradient：focal(rO*0.07,.95) → 0.7处(.8 原色) → 外缘(.55)
//   - cutout 72% = holeRatio 0.72；细白描边 rgba(255,255,255,.30) 1px；spacing 角度间隙
//   - hoverOffset 18：hover 扇区沿角平分线外弹（带 Behavior 缓动）
//   - hover 高亮描边 rgba(255,255,255,.85) 2px（近似 hoverGlow，Shapes 无 shadow 故用亮描边）
//   - 入场：progress 0→1 扫出(animateRotate) + 整体 scale 0.92→1 + 淡入(animateScale)，easeOutCubic
//
// 用法：model = [{ name, value, r, g, b }]；hover 由内部 MouseArea 命中检测驱动。
Item {
    id: root

    property var model: []
    property real holeRatio: 0.72
    property real hoverOffset: 14
    property real gapDeg: 0.8           // 扇区间隙（web spacing:2≈1.15°，矢量锐利下收小更精致）
    property int enterDuration: 620
    property int hoveredIndex: -1      // 鼠标命中的扇区（-1=无）
    property string highlightName: ""  // 外部联动高亮（柱状图/卡片 hover 传入的 app 名）
    property real progress: 0.0        // 入场进度 0→1

    signal hovered(string name)        // 鼠标 hover 扇区变化时外发（""=离开）
    signal clicked(string key, bool isCategory)  // 点击扇区时外发（key=""或"__other__"时不导航）

    // 实际高亮扇区：鼠标优先，否则用外部 highlightName 匹配（联动时让对应扇区也弹出+发光）
    readonly property int effectiveIndex: hoveredIndex >= 0 ? hoveredIndex : indexOfName(highlightName)
    function indexOfName(nm) {
        if (!nm) return -1;
        for (var i = 0; i < segments.length; i++) if (segments[i].name === nm) return i;
        return -1;
    }
    onHoveredIndexChanged: root.hovered(hoveredIndex >= 0 && hoveredIndex < segments.length ? segments[hoveredIndex].name : "")

    readonly property real cx: width / 2
    readonly property real cy: height / 2
    // 半径只留 4px 抗锯齿余量（接近 web Chart.js radius 95%）；hover 外弹靠 Item 不裁剪、弹进周边留白，
    // 不再为 hoverOffset 预留→环径明显变大（之前 -hoverOffset-2 把环砍小了一圈）。
    readonly property real rOuter: Math.min(width, height) / 2 - 4
    readonly property real rInner: rOuter * holeRatio

    function total() {
        var t = 0;
        for (var i = 0; i < model.length; i++) t += Math.max(0, model[i].value || 0);
        return t;
    }
    // 段数据：累积起始比例 fracStart + 本片占比 frac + 颜色 + 导航 key
    function buildSegments() {
        var t = total(); var out = []; var acc = 0;
        for (var i = 0; i < model.length; i++) {
            var v = Math.max(0, model[i].value || 0);
            var frac = t > 0 ? v / t : 0;
            out.push({ fracStart: acc, frac: frac, name: model[i].name,
                       key: model[i].key || "", isCategory: model[i].isCategory || false,
                       r: model[i].r, g: model[i].g, b: model[i].b });
            acc += frac;
        }
        return out;
    }
    // 按角度命中段，返回段下标（-1=未命中）
    function hitTestAt(px, py) {
        var dx = px - root.cx, dy = py - root.cy;
        var dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < root.rInner || dist > root.rOuter + root.hoverOffset) return -1;
        var deg = Math.atan2(dy, dx) * 180 / Math.PI;
        for (var i = 0; i < root.segments.length; i++) {
            var s = root.segments[i];
            var a0 = -90 + s.fracStart * 360;
            var a1 = a0 + s.frac * 360;
            var d = deg; while (d < a0) d += 360; while (d >= a0 + 360) d -= 360;
            if (d >= a0 && d <= a1) return i;
        }
        return -1;
    }
    property var segments: buildSegments()
    onModelChanged: segments = buildSegments()

    // 入场动画：progress 扫出
    NumberAnimation {
        id: enterAnim
        target: root; property: "progress"
        from: 0; to: 1; duration: root.enterDuration
        easing.type: Easing.InOutCubic    // 加速渐入渐出：开头慢→中段加速→结尾缓收
    }
    function playEnter() { root.progress = 0; enterAnim.restart(); }
    Component.onCompleted: playEnter()

    // 整体入场：scale + 淡入（配合 sweep）
    transform: Scale {
        origin.x: root.cx; origin.y: root.cy
        xScale: 0.92 + 0.08 * root.progress
        yScale: 0.92 + 0.08 * root.progress
    }
    opacity: 0.25 + 0.75 * Math.min(1, root.progress * 1.6)

    // 按**数量**计（非绑数组）：扇区数不变时，root.segments 换新数组只会让下面的 modelData 绑定
    // 原地重算（角度/颜色更新），不销毁重建 Shape——等价 Chart.js .update()，消除"饼图一下消失"的闪烁。
    Repeater {
        model: root.segments.length
        delegate: Shape {
            id: seg
            required property int index
            readonly property var modelData: (index >= 0 && index < root.segments.length)
                ? root.segments[index]
                : ({ fracStart: 0, frac: 0, name: "", r: 0, g: 0, b: 0 })
            anchors.fill: parent
            antialiasing: true
            preferredRendererType: Shape.CurveRenderer

            // 本片完整角度（12 点 = -90° 起，顺时针）
            readonly property real fullA0: -90 + modelData.fracStart * 360
            readonly property real fullA1: fullA0 + modelData.frac * 360
            // 入场扫出：整圈只画到 -90 + 360*progress
            readonly property real limitDeg: -90 + 360 * root.progress
            readonly property real a0: fullA0
            readonly property real a1: Math.min(fullA1, limitDeg)
            readonly property real span: a1 - a0
            // 自适应间隙：细碎扇区不能被固定 gapDeg 整片吃掉（否则尾部小片集体消失→外圈缺口→饼图不圆）。
            // 间隙最多取扇区张角的 45%，保证任何 >0.12° 的小片都能画出贴外圆的薄片。
            readonly property real effGap: Math.min(root.gapDeg, span * 0.45)
            readonly property bool drawable: span > 0.12
            readonly property real drawA0: a0
            readonly property real drawA1: a1 - effGap                // 留间隙（自适应）
            readonly property real midRad: ((drawA0 + drawA1) / 2) * Math.PI / 180
            readonly property bool hovered: index === root.effectiveIndex

            visible: drawable

            // 端点坐标
            readonly property real rad0: drawA0 * Math.PI / 180
            readonly property real rad1: drawA1 * Math.PI / 180
            readonly property real p0x: root.cx + root.rOuter * Math.cos(rad0)
            readonly property real p0y: root.cy + root.rOuter * Math.sin(rad0)
            readonly property real p2x: root.cx + root.rInner * Math.cos(rad1)
            readonly property real p2y: root.cy + root.rInner * Math.sin(rad1)

            // hoverOffset：沿角平分线外弹（带缓动）
            transform: Translate {
                x: seg.hovered ? Math.cos(seg.midRad) * root.hoverOffset : 0
                y: seg.hovered ? Math.sin(seg.midRad) * root.hoverOffset : 0
                Behavior on x { NumberAnimation { duration: 140; easing.type: Easing.OutQuad } }
                Behavior on y { NumberAnimation { duration: 140; easing.type: Easing.OutQuad } }
            }

            ShapePath {
                fillColor: "transparent"        // 用 fillGradient
                // 常态无描边——矢量锐利渲染下整圈白边=丑白框；扇区靠 gapDeg 间隙分隔即可。
                // hover 只做轻微提亮（近似 web hoverGlow 的 rgba(255,255,255,0.28)，Shapes 无 shadow）。
                strokeColor: seg.hovered ? "#47ffffff" : "transparent"
                strokeWidth: seg.hovered ? 1.5 : 0
                joinStyle: ShapePath.RoundJoin
                capStyle: ShapePath.RoundCap

                fillGradient: RadialGradient {
                    centerX: root.cx; centerY: root.cy; centerRadius: root.rOuter
                    focalX: root.cx; focalY: root.cy; focalRadius: root.rOuter * 0.07
                    GradientStop { position: 0.0; color: Qt.rgba(modelData.r/255, modelData.g/255, modelData.b/255, 0.95) }
                    GradientStop { position: 0.7; color: Qt.rgba(modelData.r/255, modelData.g/255, modelData.b/255, 0.80) }
                    GradientStop { position: 1.0; color: Qt.rgba(modelData.r/255, modelData.g/255, modelData.b/255, 0.55) }
                }

                // 外弧 → 内弧终点 → 内弧反扫 → 闭合
                startX: seg.p0x; startY: seg.p0y
                PathAngleArc {
                    centerX: root.cx; centerY: root.cy
                    radiusX: root.rOuter; radiusY: root.rOuter
                    startAngle: seg.drawA0; sweepAngle: seg.drawA1 - seg.drawA0
                    moveToStart: false
                }
                PathLine { x: seg.p2x; y: seg.p2y }
                PathAngleArc {
                    centerX: root.cx; centerY: root.cy
                    radiusX: root.rInner; radiusY: root.rInner
                    startAngle: seg.drawA1; sweepAngle: seg.drawA0 - seg.drawA1
                    moveToStart: false
                }
                PathLine { x: seg.p0x; y: seg.p0y }
            }
        }
    }

    // hover + click 命中检测
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton
        cursorShape: root.hoveredIndex >= 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
        onPositionChanged: function(mouse) {
            root.hoveredIndex = root.hitTestAt(mouse.x, mouse.y);
        }
        onExited: root.hoveredIndex = -1
        onClicked: function(mouse) {
            var idx = root.hitTestAt(mouse.x, mouse.y);
            if (idx < 0 || idx >= root.segments.length) return;
            var seg = root.segments[idx];
            // "__other__" 或空 key 不导航
            if (!seg.key || seg.key === "__other__") return;
            root.clicked(seg.key, seg.isCategory);
        }
    }
}
