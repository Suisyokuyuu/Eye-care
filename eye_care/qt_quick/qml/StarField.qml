import QtQuick

// 星空背景——复刻 web createStars()：大星45(亮、带辉光、闪烁) + 中星180 + 小星320(淡、静态)。
// 用轻量 Rectangle 圆点；仅大星做 twinkle(SequentialAnimation，~45 个，省性能)，中小星静态。
Item {
    id: sf
    clip: true

    property var stars: []
    Component.onCompleted: stars = _build()

    function _build() {
        var out = [];
        function add(n, szMin, szRange, opMin, opRange, glow) {
            for (var i = 0; i < n; i++) {
                out.push({
                    x: Math.random(), y: Math.random(),
                    size: szMin + Math.random() * szRange,
                    op: opMin + Math.random() * opRange,
                    glow: glow,
                    dur: 1100 + Math.random() * 2600   // 闪烁半周期
                });
            }
        }
        add(45, 1.2, 2.0, 0.5, 0.4, true);    // 大星：亮 + 闪烁
        add(180, 0.4, 1.2, 0.25, 0.45, false); // 中星
        add(320, 0.3, 0.8, 0.1, 0.35, false);  // 小星：很多、淡
        return out;
    }

    Repeater {
        model: sf.stars
        delegate: Rectangle {
            id: st
            required property var modelData
            x: modelData.x * sf.width
            y: modelData.y * sf.height
            width: modelData.size
            height: modelData.size
            radius: width / 2
            color: "#ffffff"
            opacity: modelData.op
            antialiasing: true

            // 大星闪烁：op ↔ op*0.45（仅 glow 星启动，约 45 个，省性能）
            SequentialAnimation {
                id: tw
                loops: Animation.Infinite
                running: false
                NumberAnimation { target: st; property: "opacity"; to: st.modelData.op * 0.45; duration: st.modelData.dur; easing.type: Easing.InOutSine }
                NumberAnimation { target: st; property: "opacity"; to: st.modelData.op; duration: st.modelData.dur; easing.type: Easing.InOutSine }
            }
            Component.onCompleted: if (modelData.glow) tw.start()
        }
    }
}
