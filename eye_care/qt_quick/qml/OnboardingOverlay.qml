import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

// 启动引导覆盖层：聚光灯遮罩 + 悬浮说明卡片。
// 由 AppShell 放置（z:500），只在 active=true 时可见；steps 列表由 AppShell 动态计算并注入。
// 每个 step：{ rect（Qt.rect 值或返回 Qt.rect 的函数）, title, body, side, onEnter?, onLeave? }
Item {
    id: root
    anchors.fill: parent
    z: 500
    visible: active && steps.length > 0

    property var  steps: []        // 引导步骤列表
    property int  currentStep: 0
    property bool active: false
    property int  _prevStep: -1   // 上一步索引，用于触发 onLeave
    signal finished()              // 用户完成所有步骤
    signal skipped()               // 用户点「跳过引导」

    readonly property var    step: (active && currentStep < steps.length) ? steps[currentStep] : null
    // rect 支持 Qt.rect 值或函数（函数在每次 step 变化时立即调用）
    readonly property var    tgt:  {
        if (!step) return Qt.rect(0, 0, 0, 0);
        var r = step.rect;
        return (typeof r === "function") ? r() : r;
    }
    readonly property string side:      step ? (step.side      || "bottom") : "bottom"
    // cardAlign 覆盖卡片定位，支持 "bottomRight"（展示窗关闭时把卡片固定到右下角）
    readonly property string cardAlign: step ? (step.cardAlign || "")       : ""
    readonly property bool   isLast: currentStep >= steps.length - 1
    readonly property int    pad: 12   // 高亮区外扩边距

    // 步骤切换：依次调用上一步 onLeave、当前步 onEnter
    onCurrentStepChanged: {
        if (!root.active) return;
        if (root._prevStep >= 0 && root._prevStep < root.steps.length) {
            var prev = root.steps[root._prevStep];
            if (prev && prev.onLeave) prev.onLeave();
        }
        root._prevStep = root.currentStep;
        var cur = root.steps[root.currentStep];
        if (cur && cur.onEnter) cur.onEnter();
    }
    // 引导开启：触发首步 onEnter；引导关闭：触发当前步 onLeave
    onActiveChanged: {
        if (active) {
            root._prevStep = root.currentStep;
            var s = root.steps[root.currentStep];
            if (s && s.onEnter) s.onEnter();
        } else {
            var cs = root._prevStep;
            if (cs >= 0 && cs < root.steps.length && root.steps[cs] && root.steps[cs].onLeave) {
                root.steps[cs].onLeave();
            }
            root._prevStep = -1;
        }
    }

    // 高亮框的实际屏幕坐标（含 pad）
    readonly property real tx: tgt.x - pad
    readonly property real ty: tgt.y - pad
    readonly property real tw: tgt.width  + 2 * pad
    readonly property real th: tgt.height + 2 * pad

    // ── 聚光灯：四块半透明遮罩围出高亮窗口 ──────────────────────
    Rectangle { color: "#cc000000"; x: 0; y: 0; width: parent.width; height: Math.max(0, ty) }
    Rectangle { color: "#cc000000"; x: 0; y: Math.max(0, ty + th); width: parent.width; height: Math.max(0, parent.height - ty - th) }
    Rectangle { color: "#cc000000"; x: 0; y: ty; width: Math.max(0, tx); height: Math.max(0, th) }
    Rectangle { color: "#cc000000"; x: Math.max(0, tx + tw); y: ty; width: Math.max(0, parent.width - tx - tw); height: Math.max(0, th) }

    // 高亮框蓝色边框
    Rectangle {
        x: tx; y: ty; width: Math.max(0, tw); height: Math.max(0, th)
        color: "transparent"; border.color: "#803b82f6"; border.width: 2; radius: 10
        visible: tw > 0 && th > 0
    }

    // ── 说明卡片 ──────────────────────────────────────────────────
    Rectangle {
        id: card
        // 宽度：最多 340px，至少保留 16px 两侧边距
        readonly property real cw: Math.min(340, root.width - 32)
        // 卡片高度由内容决定
        readonly property real ch: inner.implicitHeight + 32

        width: cw
        height: ch
        radius: 12
        color: "#0F172A"
        border.color: "#1affffff"; border.width: 1

        // 卡片 x 定位
        x: {
            // 右移 450px 预留空间，避免与屏幕右下角的通知气泡窗口重叠
            if (root.cardAlign === "bottomRight") return Math.max(8, root.width  - cw - 450);
            if (side === "left")  return Math.max(8, root.tx - cw - 16);
            if (side === "right") return Math.min(root.width - cw - 8, root.tx + root.tw + 16);
            // top / bottom：水平居中于高亮区，整体夹在窗口内
            var cx = root.tx + root.tw / 2 - cw / 2;
            return Math.max(8, Math.min(root.width - cw - 8, cx));
        }
        // 卡片 y 定位
        y: {
            if (root.cardAlign === "bottomRight") return Math.max(8, root.height - ch - 16);
            if (side === "top")    return Math.max(8, root.ty - ch - 16);
            if (side === "bottom") return Math.min(root.height - ch - 8, root.ty + root.th + 16);
            // left / right：垂直居中于高亮区，整体夹在窗口内
            var cy = root.ty + root.th / 2 - ch / 2;
            return Math.max(8, Math.min(root.height - ch - 8, cy));
        }

        // 切步骤时淡出淡入
        Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

        ColumnLayout {
            id: inner
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: 16 }
            spacing: 8

            // 步骤计数
            Text {
                text: (root.currentStep + 1) + " / " + root.steps.length
                color: "#60A5FA"; font.pixelSize: 12; font.weight: Font.Medium
            }
            // 标题
            Text {
                text: step ? step.title : ""
                color: "#f1f5f9"; font.pixelSize: 15; font.bold: true
                wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            // 正文
            Text {
                text: step ? step.body : ""
                color: "#9ca3af"; font.pixelSize: 13
                wrapMode: Text.WordWrap; Layout.fillWidth: true; lineHeight: 1.45
            }

            // 按钮行
            RowLayout {
                Layout.fillWidth: true; Layout.topMargin: 4; spacing: 6

                // 跳过引导
                Rectangle {
                    height: 32; radius: 6
                    color: skipMa.containsMouse ? "#1affffff" : "transparent"
                    border.color: "#1affffff"; border.width: 1
                    implicitWidth: skipTxt.implicitWidth + 24
                    Text { id: skipTxt; anchors.centerIn: parent; text: "跳过引导"; color: "#9ca3af"; font.pixelSize: 13 }
                    MouseArea { id: skipMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: { root.active = false; root.skipped(); }
                    }
                }

                Item { Layout.fillWidth: true }

                // 上一步（第一步时隐藏）
                Rectangle {
                    visible: root.currentStep > 0
                    height: 32; radius: 6
                    color: prevMa.containsMouse ? "#1affffff" : "transparent"
                    border.color: "#1affffff"; border.width: 1
                    implicitWidth: prevTxt.implicitWidth + 24
                    Text { id: prevTxt; anchors.centerIn: parent; text: "上一步"; color: "#cbd5e1"; font.pixelSize: 13 }
                    MouseArea { id: prevMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: root.currentStep--
                    }
                }

                // 下一步 / 完成
                Rectangle {
                    height: 32; radius: 6
                    color: nextMa.containsMouse ? "#1e40af" : "#3b82f6"
                    implicitWidth: nextTxt.implicitWidth + 28
                    Text { id: nextTxt; anchors.centerIn: parent
                        text: root.isLast ? "完成" : "下一步"
                        color: "#ffffff"; font.pixelSize: 13; font.weight: Font.Medium
                    }
                    MouseArea { id: nextMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (root.isLast) { root.active = false; root.finished(); }
                            else root.currentStep++;
                        }
                    }
                }
            }
        }

        // 阻止卡片内的点击穿透到下层 MouseArea
        MouseArea { anchors.fill: parent; z: -1 }
    }

    // 全屏点击拦截器（置于卡片下方；吃掉背景暗区的所有鼠标事件）
    MouseArea {
        anchors.fill: parent
        z: -1
        acceptedButtons: Qt.AllButtons
        onClicked: {}
        onWheel: function(wheel) { wheel.accepted = true }
    }
}
