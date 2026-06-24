import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Shapes

// 设置页（step3，复刻 web #settingsModal）：全屏变暗 + 居中卡片(dark-200 rounded-xl p-8 max-w-md)。
// 控件全自定义绘制以贴合 .input-primary/.btn-*/checkbox/select 暗色主题（不赌原生样式）。
// 数据：打开时 load() 从 settingsBridge.config 填充本地编辑态；【应用】收集 payload 调 bridge.apply。
// 用法：放在 AppShell 顶层，`open=true` 显示；点【应用】/【取消】/X / 背景 → closed()。
Item {
    id: page
    anchors.fill: parent
    // 渐入渐出
    visible: opacity > 0.01
    opacity: open ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    z: 100

    required property var bridge          // SettingsBridge
    property bool open: false
    signal closed()
    signal showOnboardingRequested()     // 点「立即显示引导」→ AppShell 响应

    // ── 本地编辑态（从 bridge.config 载入，应用时回写）──
    property bool launchAtLogin: false
    property bool startupDnd: false
    property bool startupShow: true
    property int  idleThreshold: 60
    property string closeAction: "ask"
    property bool notifyEnabled: true
    property int  workMinutes: 20
    property int  restDuration: 20        // 显示值（按 restUnit 解释）
    property string restUnit: "sec"
    property int  notifyHide: 20
    property bool notifySound: true
    property bool restEndSound: true
    property bool fullscreenDnd: false   // 前台全屏时自动勿扰
    property bool showOnboarding: true   // true=启动显示引导

    // 引导用矩形：未勾选休息提醒时的紧凑卡片（约 600px 高，无休息设置组）
    function cardCompactRect() {
        var sh = Math.min(parent.height - 48, 600);
        var sy = Math.max(8, (parent.height - sh) / 2);
        return Qt.rect((parent.width - 460) / 2, sy, 460, sh);
    }
    // 引导用矩形：从第三条分割线（关闭行为↔启用休息提醒之间）向下到卡片底部
    // 偏移量 450 ≈ 卡片页边距(32) + 标题行(40) + 行距(16) + body 上半各项（含分割线）之和
    function notifySectionGlobalRect() {
        var sh = parent.height - 48;
        var sy = Math.max(8, (parent.height - sh) / 2);
        var offset = 450;
        return Qt.rect((parent.width - 460) / 2, sy + offset, 460, Math.max(40, sh - offset));
    }
    // 引导用：把 Flickable 滚到顶部 / 底部，让用户看到对应设置分区
    function scrollToTop()   { bodyFlick.contentY = 0; }
    function scrollToBottom() {
        bodyFlick.contentY = Math.max(0, bodyFlick.contentHeight - bodyFlick.height);
    }

    function load() {
        var c = page.bridge ? page.bridge.config : null;
        if (!c) return;
        launchAtLogin  = !!c.startup_launch_at_login;
        startupDnd     = !!c.startup_dnd;
        startupShow    = c.startup_show_main !== false;
        idleThreshold  = Math.max(3, Math.min(300, c.idle_threshold_s || 60));
        closeAction    = c.close_action || "ask";
        notifyEnabled  = c.notify_enabled !== false;
        workMinutes    = Math.max(1, Math.min(600, c.reminder_work_minutes || 20));
        restUnit       = (c.reminder_rest_unit === "min") ? "min" : "sec";
        var rs = c.reminder_rest_seconds || 20;
        restDuration   = (restUnit === "min") ? Math.max(1, Math.round(rs / 60)) : Math.max(5, rs);
        notifyHide     = (c.notify_auto_hide_seconds !== undefined) ? c.notify_auto_hide_seconds : 20;
        notifySound    = c.notify_sound_enabled !== false;
        restEndSound   = c.rest_end_sound_enabled !== false;
        fullscreenDnd  = !!c.fullscreen_dnd;
        showOnboarding = c.show_onboarding !== false;
    }
    function _buildPayload() {
        var restSec = (restUnit === "min") ? restDuration * 60 : restDuration;
        return {
            "startup_launch_at_login": launchAtLogin,
            "startup_dnd": startupDnd,
            "startup_show_main": startupShow,
            "idle_threshold_s": idleThreshold,
            "close_action": closeAction,
            "notify_enabled": notifyEnabled,
            "reminder_work_minutes": workMinutes,
            "reminder_rest_seconds": restSec,
            "reminder_rest_unit": restUnit,
            "notify_auto_hide_seconds": notifyHide,
            "notify_sound_enabled": notifySound,
            "rest_end_sound_enabled": restEndSound,
            "fullscreen_dnd": fullscreenDnd,
            "show_onboarding": showOnboarding
        };
    }
    function applyAndClose() {
        page.bridge.apply(page._buildPayload());
        page.closed();
    }
    // 引导用：保存设置但不关闭页面
    function applyOnly() {
        page.bridge.apply(page._buildPayload());
    }
    // 打开时载入；bridge 数据变化（如 reload 后）也同步。
    // 注意：open 的「初始值=true」不会触发 onOpenChanged，故 Component.onCompleted 兜底首帧载入。
    onOpenChanged: if (open) load()
    Component.onCompleted: if (open) load()
    Connections { target: page.bridge; function onConfigChanged() { if (page.open) page.load() } }

    // 背景变暗（bg-black/70）；点击背景关闭
    Rectangle {
        anchors.fill: parent
        color: "#b3000000"
        MouseArea { anchors.fill: parent; onClicked: page.closed(); onWheel: function(wheel){ wheel.accepted = true } }
    }

    // 卡片（dark-200 #0F172A，rounded-xl 12，p-8）
    Rectangle {
        id: card
        anchors.centerIn: parent
        width: 460
        // 高度跟随正文（body）自适应，并以窗口高封顶；超出则正文区滚动。
        // +196 ≈ 外边距64 + 标题行40 + 底部按钮40 + 行距与余量。
        height: Math.min(parent.height - 48, body.implicitHeight + 196)
        radius: 12
        color: "#0F172A"
        border.color: "#1affffff"; border.width: 1
        // 吞掉卡片内点击，避免穿透到背景关闭
        MouseArea { anchors.fill: parent }

        ColumnLayout {
            id: contentCol
            anchors.fill: parent
            anchors.margins: 32
            spacing: 16

            // 标题栏
            RowLayout {
                Layout.fillWidth: true
                Text { text: "设置"; color: "#ffffff"; font.pixelSize: 24; font.bold: true }
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

            // 可滚动正文（设置项较多时不溢出）
            Flickable {
                id: bodyFlick
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: width
                contentHeight: body.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ThemedSB {}

                ColumnLayout {
                    id: body
                    width: parent.width
                    spacing: 16

                    // 启动引导
                    RowLayout {
                        Layout.fillWidth: true
                        Check {
                            text: "关闭启动引导"
                            checked: !page.showOnboarding
                            onToggled: page.showOnboarding = !v
                        }
                        Item { Layout.fillWidth: true }
                        // 立即显示引导：关闭设置页、触发引导
                        Text {
                            text: "立即显示引导 ›"
                            color: showLinkMa.containsMouse ? "#93C5FD" : "#60A5FA"
                            font.pixelSize: 13
                            MouseArea {
                                id: showLinkMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    page.showOnboarding = true;   // 同时把开关拨回「开」
                                    page.closed();
                                    page.showOnboardingRequested();
                                }
                            }
                        }
                    }

                    Divider {}

                    // 无操作多久暂停计时
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 6
                        FieldLabel { text: "无操作多久暂停计时" }
                        HelpText { text: "无操作超过此时长后暂停计时；恢复操作后继续。" }
                        RowLayout {
                            spacing: 8
                            NumField { value: page.idleThreshold; min: 3; max: 300; onCommitted: page.idleThreshold = v }
                            Text { text: "秒"; color: "#9CA3AF"; font.pixelSize: 14 }
                        }
                    }

                    // 启动相关
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 10
                        Check { text: "开机自启动";       checked: page.launchAtLogin; onToggled: page.launchAtLogin = v }
                        Check { text: "启动时默认勿扰";   checked: page.startupDnd;    onToggled: page.startupDnd = v }
                        Check { text: "启动时显示主界面"; checked: page.startupShow;   onToggled: page.startupShow = v }
                    }

                    Divider {}

                    // 关闭行为
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 6
                        FieldLabel { text: "关闭主窗口时的行为" }
                        HelpText { text: "选择点击关闭按钮后的默认操作。" }
                        Select {
                            value: page.closeAction
                            model: [
                                { v: "ask",      t: "每次询问" },
                                { v: "minimize", t: "最小化到托盘" },
                                { v: "quit",     t: "退出程序" }
                            ]
                            onPicked: page.closeAction = v
                        }
                    }

                    Divider {}

                    // 全屏勿扰
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 6
                        Check { text: "全屏时自动勿扰"; checked: page.fullscreenDnd; onToggled: page.fullscreenDnd = v }
                        HelpText { text: "检测到前台应用进入全屏（如游戏 / 全屏视频）时自动切换到勿扰模式，退出全屏后自动恢复。" }
                    }

                    Divider {}

                    // 启用休息提醒功能
                    Check { text: "启用休息提醒功能"; checked: page.notifyEnabled; onToggled: page.notifyEnabled = v }

                    // 休息设置组（仅启用时显示）
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 16
                        visible: page.notifyEnabled

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2; columnSpacing: 16; rowSpacing: 6
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 6
                                FieldLabel { text: "休息提醒间隔" }
                                RowLayout {
                                    spacing: 8
                                    NumField { value: page.workMinutes; min: 1; max: 600; onCommitted: page.workMinutes = v }
                                    Text { text: "分钟"; color: "#9CA3AF"; font.pixelSize: 14 }
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 6
                                FieldLabel { text: "休息时长" }
                                RowLayout {
                                    spacing: 8
                                    NumField { value: page.restDuration; min: 1; max: 3600; onCommitted: page.restDuration = v }
                                    Select {
                                        compact: true
                                        value: page.restUnit
                                        model: [ { v: "sec", t: "秒" }, { v: "min", t: "分" } ]
                                        onPicked: page.restUnit = v
                                    }
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 6
                            FieldLabel { text: "通知显示时长" }
                            RowLayout {
                                spacing: 8
                                NumField { value: page.notifyHide; min: 0; max: 600; onCommitted: page.notifyHide = v }
                                Text { text: "秒（0 表示不自动隐藏）"; color: "#9CA3AF"; font.pixelSize: 14 }
                            }
                        }

                        Check { text: "启用通知提示音";     checked: page.notifySound;  onToggled: page.notifySound = v }
                        Check { text: "启用休息结束提示音"; checked: page.restEndSound; onToggled: page.restEndSound = v }
                    }
                }
            }

            // 底部按钮
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                FooterBtn { Layout.fillWidth: true; text: "应用"; primary: true; onClicked: page.applyAndClose() }
                FooterBtn { Layout.fillWidth: true; text: "取消"; primary: false; onClicked: page.closed() }
            }
        }
    }

    // ── 内联组件 ──

    component FieldLabel: Text { color: "#D1D5DB"; font.pixelSize: 14; font.weight: Font.Medium }
    component HelpText: Text {
        property bool dim: false
        color: dim ? "#6B7280" : "#9CA3AF"; font.pixelSize: 12
        wrapMode: Text.WordWrap; Layout.fillWidth: true
    }
    component Divider: Rectangle { Layout.fillWidth: true; height: 1; color: "#1affffff" }

    // 数字输入（.input-primary：bg #1E293B / border white/10 / radius8 / 居中），失焦/回车 clamp 提交
    component NumField: Rectangle {
        id: nf
        property int value: 0
        property int min: 0
        property int max: 999
        property int v: value           // committed 时携带
        signal committed()
        implicitWidth: 84; implicitHeight: 38; radius: 8
        color: "#1E293B"
        border.color: tf.activeFocus ? "#803b82f6" : "#1affffff"; border.width: tf.activeFocus ? 2 : 1
        TextField {
            id: tf
            anchors.fill: parent
            text: nf.value.toString()
            horizontalAlignment: TextInput.AlignHCenter
            verticalAlignment: TextInput.AlignVCenter
            color: "#ffffff"; font.pixelSize: 14
            selectByMouse: true
            inputMethodHints: Qt.ImhDigitsOnly
            validator: IntValidator { bottom: nf.min; top: nf.max }
            background: Item {}
            // 输入即提交：避免「点应用时输入框没失焦→editingFinished 不触发→送旧值」的坑。
            onTextChanged: {
                var n = parseInt(text, 10);
                if (!isNaN(n)) { nf.v = Math.max(nf.min, Math.min(nf.max, n)); nf.committed(); }
            }
            onEditingFinished: {
                var n = parseInt(text, 10);
                if (isNaN(n)) n = nf.min;
                n = Math.max(nf.min, Math.min(nf.max, n));
                nf.v = n; nf.committed();
                text = n.toString();
            }
        }
    }

    // 复选框（rounded border-white/20 bg-dark-300；选中 primary + 勾）。
    // 用 Item（非 Layout）承载，便于内部 Row/MouseArea 用 anchors，不与外层 Layout 冲突。
    component Check: Item {
        id: ck
        property string text: ""
        property bool checked: false
        property bool v: false
        signal toggled()
        implicitWidth: ckRow.implicitWidth
        implicitHeight: ckRow.implicitHeight
        Row {
            id: ckRow
            spacing: 12
            Rectangle {
                width: 18; height: 18; radius: 4
                anchors.verticalCenter: parent.verticalCenter
                color: ck.checked ? "#3B82F6" : "#0B1120"
                border.color: ck.checked ? "#3B82F6" : "#33ffffff"; border.width: 1
                Shape {
                    anchors.centerIn: parent; width: 12; height: 12; visible: ck.checked
                    antialiasing: true; preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: "#ffffff"; strokeWidth: 1.8; fillColor: "transparent"
                        capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                        startX: 2.5; startY: 6.2
                        PathLine { x: 5; y: 9 }
                        PathLine { x: 9.5; y: 3.2 }
                    }
                }
            }
            Text { text: ck.text; color: "#e5e7eb"; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter }
        }
        MouseArea {
            anchors.fill: parent; cursorShape: Qt.PointingHandCursor
            onClicked: { ck.v = !ck.checked; ck.toggled(); }
        }
    }

    // 下拉选择（.input-primary 外观 + 自绘弹出列表）
    component Select: Rectangle {
        id: sel
        property string value: ""
        property var model: []           // [{v,t}]
        property bool compact: false
        signal picked()
        property string v: ""            // picked 携带
        function _label(val) {
            for (var i = 0; i < model.length; i++) if (model[i].v === val) return model[i].t;
            return "";
        }
        implicitWidth: compact ? 78 : 160; implicitHeight: 38; radius: 8
        color: "#1E293B"
        border.color: selMa.containsMouse || pop.visible ? "#803b82f6" : "#1affffff"; border.width: 1
        Text {
            anchors.left: parent.left; anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: sel._label(sel.value); color: "#e5e7eb"; font.pixelSize: 14
        }
        // 下拉箭头
        Shape {
            anchors.right: parent.right; anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            width: 10; height: 6; antialiasing: true
            ShapePath {
                strokeColor: "#9CA3AF"; strokeWidth: 1.5; fillColor: "transparent"
                capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                startX: 0.5; startY: 0.8
                PathLine { x: 5; y: 5 }
                PathLine { x: 9.5; y: 0.8 }
            }
        }
        MouseArea { id: selMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: pop.open() }
        Popup {
            id: pop
            y: sel.height + 4; x: 0
            width: sel.width
            padding: 4
            background: Rectangle { color: "#1E293B"; radius: 8; border.color: "#1affffff"; border.width: 1 }
            contentItem: ColumnLayout {
                spacing: 2
                Repeater {
                    model: sel.model
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: 32; radius: 6
                        readonly property bool on: modelData.v === sel.value
                        color: itMa.containsMouse ? "#1f3b82f6" : (on ? "#142f6fd6" : "transparent")
                        Text {
                            anchors.left: parent.left; anchors.leftMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.t; font.pixelSize: 14
                            color: on ? "#60A5FA" : "#e5e7eb"
                        }
                        MouseArea {
                            id: itMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: { sel.v = modelData.v; sel.picked(); pop.close(); }
                        }
                    }
                }
            }
        }
    }

    // 底部按钮（btn-primary / btn-secondary）
    component FooterBtn: Rectangle {
        id: fb
        property string text: ""
        property bool primary: true
        signal clicked()
        implicitHeight: 40; radius: 8
        color: primary
               ? (fbMa.containsMouse ? "#1E40AF" : "#3B82F6")
               : (fbMa.containsMouse ? "#0F172A" : "#1E293B")
        border.color: primary ? "transparent" : "#1affffff"
        border.width: primary ? 0 : 1
        Text { anchors.centerIn: parent; text: fb.text; color: "#ffffff"; font.pixelSize: 14; font.weight: Font.Medium }
        MouseArea { id: fbMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: fb.clicked() }
    }

    // 设置页内滚动条（同 .scrollbar-theme）
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
