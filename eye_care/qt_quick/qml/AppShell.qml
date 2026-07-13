import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Effects

// 主窗口外壳：无边框窗口 + 自定义标题栏（复刻 .app-titlebar）+ 工具栏（设置/导入/导出/应用设置/黑名单/检查更新）
// + 内嵌仪表盘（复用 LeftPanel/RightPanel）。这是 step4「接外壳」最终要装进 runtime_shell 的窗口骨架；
// 现阶段工具栏按钮只发信号（toolbarAction），窗口控制（最小化/最大化/关闭）直接操作本 Window。
// 数据走 contextProperty leftPanelBridge/rightPanelBridge；version 由宿主注入 appVersion。
Window {
    id: root
    width: 1320
    height: 820
    minimumWidth: 980
    minimumHeight: 620
    visible: true
    color: "#070D19"
    flags: Qt.Window | Qt.FramelessWindowHint
    title: "EyE Care"

    property string appVersion: ""
    signal toolbarAction(string name)   // settings/import/export/appSettings/blacklist/checkUpdate（预览用；运行时优先 shellHost）
    signal restRequested()              // 右栏「立刻休息」（预览用；运行时优先 shellHost.requestRest）

    // 运行时由宿主注入的 shellHost 上下文属性（QObject，含 doToolbarAction/requestRest/quitApp）。
    // 预览无此属性 → hostReady=false → 回退到上面的信号，保持预览可用。
    readonly property bool hostReady: (typeof shellHost !== "undefined") && (shellHost !== null)

    // 统一出口：有宿主走 shellHost（可靠），否则发信号（预览）
    function fireToolbar(name) { if (hostReady) shellHost.doToolbarAction(name); else root.toolbarAction(name); }
    function fireRest() { if (hostReady) shellHost.requestRest(); else root.restRequested(); }
    function fireQuit() { if (hostReady) shellHost.quitApp(); else root.close(); }

    // 供宿主（托盘）回调打开对应页面（QMetaObject.invokeMethod 调用）
    function openSettings() { settingsPage.open = true }
    function openAppSettings() { appSettingsPage.open = true }
    function openBlacklist() { blacklistPage.open = true }
    function openUpdate() { updatePage.open = true }

    // 关闭主窗口：按设置里的 close_action 决定（ask→弹确认 / minimize→最小化 / quit→退出）
    function requestClose() {
        var ca = (settingsBridge && settingsBridge.config && settingsBridge.config.close_action)
                 ? settingsBridge.config.close_action : "ask";
        if (ca === "quit") root.quitWithFade();
        else if (ca === "minimize") root.minimizeWithFade();
        else closeConfirmPage.open = true;
    }

    // ── 渐出动画：最小化/关闭到托盘/退出前先淡出，避免突兀 ──
    property var _pendingAction: null
    NumberAnimation {
        id: fadeOutAnim
        target: root
        property: "opacity"
        from: 1.0; to: 0.0
        duration: 150
        easing.type: Easing.InQuad
        onFinished: {
            var act = root._pendingAction;
            root._pendingAction = null;
            if (act) act();
        }
    }
    function _fadeOutThen(action) {
        root._pendingAction = action;
        fadeOutAnim.restart();
    }
    // 最小化=收进托盘：用 hide() 而非 showMinimized()，否则任务栏仍残留 EyE Care 按钮
    // （用户反馈：关闭→最小化后任务栏没同步关掉）。从托盘点「显示主界面」再 show() 唤回。
    function minimizeWithFade() { root._fadeOutThen(function(){ root.hide(); }); }
    function quitWithFade() { root._fadeOutThen(function(){ root.fireQuit(); }); }

    // 还原显示时复位透明度（托盘/任务栏唤回后不能停在透明态），并轻微淡入
    onVisibilityChanged: {
        if (visibility === Window.Windowed || visibility === Window.Maximized || visibility === Window.FullScreen) {
            fadeOutAnim.stop();
            root._pendingAction = null;
            if (root.opacity < 1.0) fadeInAnim.restart();
            else root.opacity = 1.0;
        }
    }
    NumberAnimation {
        id: fadeInAnim
        target: root
        property: "opacity"
        to: 1.0
        duration: 150
        easing.type: Easing.OutQuad
    }

    // 跨栏联动高亮（左右栏 hover 互相点亮）
    property string hlKey: ""

    // 背景：渐变蓝 + 顶部蓝辉光 + 星空（复刻 web body 背景）
    AppBackground { anchors.fill: parent }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── 自定义标题栏（h36，可拖拽）──
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 36
            color: "#b30B1120"      // dark-300 半透明，让星空透出（整条顶栏也有星空）
            // 底边
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#1affffff" }

            // 拖拽区（铺底，按钮在其上且自带 MouseArea 不穿透）
            MouseArea {
                anchors.fill: parent
                onPressed: root.startSystemMove()
                onDoubleClicked: root.visibility === Window.Maximized ? root.showNormal() : root.showMaximized()
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10; anchors.rightMargin: 0
                spacing: 0
                // 左：logo + 标题 + 版本
                Row {
                    spacing: 8
                    Layout.alignment: Qt.AlignVCenter
                    Rectangle {   // logo 渐变方块 + 矢量眼睛
                        width: 20; height: 20; radius: 5
                        anchors.verticalCenter: parent.verticalCenter
                        gradient: Gradient {
                            orientation: Gradient.Vertical
                            GradientStop { position: 0.0; color: "#3b82f6" }
                            GradientStop { position: 1.0; color: "#1e40af" }
                        }
                        // 眼睛：外椭圆 + 瞳孔
                        Rectangle {
                            anchors.centerIn: parent; width: 12; height: 8; radius: 4
                            color: "transparent"; border.color: "#ffffff"; border.width: 1.2
                        }
                        Rectangle { anchors.centerIn: parent; width: 3.4; height: 3.4; radius: 1.7; color: "#ffffff" }
                    }
                    Text { text: "EyE Care"; color: "#ffffff"; font.pixelSize: 14; font.weight: Font.Medium; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: "护眼应用"; color: "#9ca3af"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: root.appVersion; color: "#6b7280"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; visible: root.appVersion !== "" }
                }
                Item { Layout.fillWidth: true }
                // 右：窗口控制 — ▢ ✕（矢量绘制，尺寸统一锐利，不赌字体字形）
                Row {
                    Layout.fillHeight: true
                    WinBtn { kind: "min"; onClicked: root.minimizeWithFade() }
                    WinBtn {
                        kind: root.visibility === Window.Maximized ? "restore" : "max"
                        onClicked: root.visibility === Window.Maximized ? root.showNormal() : root.showMaximized()
                    }
                    WinBtn { kind: "close"; danger: true; onClicked: root.requestClose() }
                }
            }
        }

        // ── 工具栏（设置/导入/导出/应用设置/黑名单/检查更新）──
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            color: "#730B1120"     // dark-300/~45% 半透明，工具栏透出星空
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#0dffffff" }
            Row {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left; anchors.leftMargin: 12
                spacing: 4
                ToolBtn { id: tbSettings;    icon: "cog";      label: "设置";     onClicked: settingsPage.open = true }
                ToolBtn { id: tbImport;      icon: "download"; label: "导入";     onClicked: { choicePage.mode = "import"; choicePage.title = "请选择导入类型"; choicePage.label1 = "导入数据"; choicePage.label2 = "导入设置"; choicePage.open = true } }
                ToolBtn { id: tbExport;      icon: "upload";   label: "导出";     onClicked: { choicePage.mode = "export"; choicePage.title = "请选择导出类型"; choicePage.label1 = "导出数据"; choicePage.label2 = "导出设置"; choicePage.open = true } }
                ToolBtn { id: tbAppSettings; icon: "grid";     label: "应用设置"; onClicked: appSettingsPage.open = true }
                ToolBtn { id: tbBlacklist;   icon: "ban";      label: "黑名单";   onClicked: blacklistPage.open = true }
                ToolBtn { icon: "refresh";   label: "检查更新"; onClicked: updatePage.open = true }
            }
        }

        // ── 内容：仪表盘（左右栏）──
        RowLayout {
            id: dashRow
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 12
            spacing: 12

            LeftPanel {
                id: leftPanelItem
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 110
                bridge: leftPanelBridge
                highlightKey: root.hlKey
                onHighlight: function(key) { root.hlKey = key; }
                onPeriodSelected: function(period) { rightPanelBridge.setPeriod(period); }
                onCalendarRequested: calendarPage.open = true
                onStepDay: function(delta) { leftPanelBridge.stepDay(delta); rightPanelBridge.stepDay(delta); }
                // 点应用卡片→应用详情；点分类卡片→分类详情
                onAppActivated: function(key, isCategory) {
                    if (isCategory) { categoryDetailPage.category = key; categoryDetailPage.open = true; }
                    else { appsBridge.openDetail(key); appDetailPage.open = true; }
                }
            }
            RightPanel {
                id: rightPanelItem
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 100
                bridge: rightPanelBridge
                highlightKey: root.hlKey
                onHighlight: function(key) { root.hlKey = key; }
                onRestRequested: root.fireRest()
                // 点击柱状图 app 段 → 左栏列表滚动到对应条目（点卡片才进详情）
                onAppActivated: function(key, isCategory) { leftPanelItem.scrollToKey(key); }
            }
        }
    }

    // ── 设置页覆盖层（复用 settingsBridge contextProperty）──
    SettingsPage {
        id: settingsPage
        anchors.fill: parent
        bridge: settingsBridge
        onClosed: open = false
        onShowOnboardingRequested: {
            // 把开关保存为 true，然后直接触发引导（无需重启）
            if (root._settingsBridgeReady) settingsBridge.setShowOnboarding(true);
            Qt.callLater(root._startOnboarding);
        }
    }

    // ── 黑名单页覆盖层（复用 blacklistBridge contextProperty）──
    BlacklistPage {
        id: blacklistPage
        anchors.fill: parent
        bridge: blacklistBridge
        onClosed: open = false
    }

    // ── 应用设置列表 + 应用详情（复用 appsBridge）──
    AppSettingsPage {
        id: appSettingsPage
        anchors.fill: parent
        bridge: appsBridge
        onClosed: open = false
        onOpenApp: function(appShort) { appsBridge.openDetail(appShort); appDetailPage.open = true; }
    }
    AppDetailPage {
        id: appDetailPage
        anchors.fill: parent
        bridge: appsBridge
        onClosed: open = false
    }

    // ── 检查更新（复用 updateBridge）──
    UpdatePage {
        id: updatePage
        anchors.fill: parent
        bridge: updateBridge
        onClosed: open = false
    }

    // ── 导入/导出类型选择（无 bridge；选择后 toolbarAction 通知 host 执行实际文件 IO）──
    ChoicePage {
        id: choicePage
        anchors.fill: parent
        property string mode: "export"      // import | export
        onClosed: open = false
        onChosen: function(which) {
            // mode+which → 动作名（与 web desktopHostCall 对齐）
            var act = mode === "export"
                ? (which === 1 ? "exportAll" : "exportSettings")
                : (which === 1 ? "importAll" : "importSettings");
            root.fireToolbar(act);
        }
    }

    // ── 日期选择器（复用 calendarBridge；确定后 setDate 两栏）──
    CalendarPage {
        id: calendarPage
        anchors.fill: parent
        bridge: calendarBridge
        onClosed: open = false
        onPickedRange: function(start, end) {
            if (start === end || end === "") {
                leftPanelBridge.setDate(start); rightPanelBridge.setDate(start);
            } else {
                leftPanelBridge.setRange(start, end); rightPanelBridge.setRange(start, end);
            }
        }
    }

    // ── 分类详情（点左栏分类卡片打开；复用 appsBridge 客户端过滤）──
    CategoryDetailPage {
        id: categoryDetailPage
        anchors.fill: parent
        bridge: appsBridge
        onClosed: open = false
        onOpenApp: function(appShort) { appsBridge.openDetail(appShort); appDetailPage.open = true; }
    }

    // ── 关闭主窗口确认（无 bridge；记住选择则通知 host 持久化 close_action）──
    CloseConfirmPage {
        id: closeConfirmPage
        anchors.fill: parent
        onClosed: open = false
        onChosen: function(action, remember) {
            if (remember) root.fireToolbar("closeAction:" + action);
            if (action === "quit") root.quitWithFade();
            else root.minimizeWithFade();
        }
    }

    // ── 无边框拖边缩放热区（QML 原生 startSystemResize；置顶 z 保证任何页面下都能缩放）──
    // 顶边/右上角避开窗口控制按钮区（右侧 ~150px），与旧 web 主窗 nativeEvent 的处理一致。
    Item {
        anchors.fill: parent
        z: 200
        readonly property int gw: 6      // 边热区厚度
        readonly property int cw: 12     // 角热区
        readonly property int ctrlW: 150 // 右上角让位窗口控制按钮

        // 四边
        ResizeZone { edges: Qt.LeftEdge;   cur: Qt.SizeHorCursor; anchors { left: parent.left; top: parent.top; bottom: parent.bottom } width: parent.gw }
        ResizeZone { edges: Qt.RightEdge;  cur: Qt.SizeHorCursor; anchors { right: parent.right; top: parent.top; bottom: parent.bottom; topMargin: 36 } width: parent.gw }  // 顶部 36px 让位关闭按钮
        ResizeZone { edges: Qt.BottomEdge; cur: Qt.SizeVerCursor; anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: parent.gw }
        ResizeZone {
            edges: Qt.TopEdge; cur: Qt.SizeVerCursor
            anchors { left: parent.left; top: parent.top }
            width: parent.width - parent.ctrlW; height: parent.gw   // 顶边让出右侧按钮区
        }
        // 四角
        ResizeZone { edges: Qt.LeftEdge | Qt.TopEdge;     cur: Qt.SizeFDiagCursor; anchors { left: parent.left; top: parent.top } width: parent.cw; height: parent.cw }
        ResizeZone { edges: Qt.LeftEdge | Qt.BottomEdge;  cur: Qt.SizeBDiagCursor; anchors { left: parent.left; bottom: parent.bottom } width: parent.cw; height: parent.cw }
        ResizeZone { edges: Qt.RightEdge | Qt.BottomEdge; cur: Qt.SizeFDiagCursor; anchors { right: parent.right; bottom: parent.bottom } width: parent.cw; height: parent.cw }
        // 右上角不放（与窗口控制按钮冲突）
    }

    // ── 启动引导 ──────────────────────────────────────────────────────
    readonly property bool _settingsBridgeReady:
        (typeof settingsBridge !== "undefined") && (settingsBridge !== null)

    // 延时启动：等 layout 完成后坐标才准确
    Timer {
        id: onboardingTimer
        interval: 400
        onTriggered: root._startOnboarding()
    }

    // 启动时检查是否需要显示引导
    Component.onCompleted: {
        if (root._settingsBridgeReady
                && settingsBridge.config
                && settingsBridge.config.show_onboarding !== false) {
            onboardingTimer.start();
        }
    }

    // 计算各步骤的聚光灯矩形（窗口坐标），注入 OnboardingOverlay
    function _globalRect(item) {
        var p = item.mapToItem(null, 0, 0);
        return Qt.rect(p.x, p.y, item.width, item.height);
    }
    function _unionRect(a, b) {
        var x1 = Math.min(a.x, b.x),     y1 = Math.min(a.y, b.y);
        var x2 = Math.max(a.x+a.width, b.x+b.width),
            y2 = Math.max(a.y+a.height, b.y+b.height);
        return Qt.rect(x1, y1, x2-x1, y2-y1);
    }
    // 引导演示：触发通知气泡 / 休息界面（不影响业务状态）
    function _demoNotify() {
        if (hostReady && typeof shellHost.demoNotify === "function") shellHost.demoNotify();
    }
    function _demoRest() {
        if (hostReady && typeof shellHost.demoRest === "function") shellHost.demoRest();
    }

    function _startOnboarding() {
        var gr = root._globalRect;
        var ur = root._unionRect;
        onboarding.steps = [
            {
                rect: gr(leftPanelItem),
                title: "应用统计总览",
                body: "左栏展示各应用的使用时间与占比。点击条目可查看详情。",
                side: "right"
            },
            {
                rect: leftPanelItem.dateNavGlobalRect(),
                title: "日期导航",
                body: "◀ ▶ 切换日期；日历图标可选择任意日期或时间范围。",
                side: "bottom"
            },
            {
                rect: rightPanelItem.barChartGlobalRect(),
                title: "时段分析",
                body: "右栏柱状图展示每个时段的用眼分布，鼠标悬停高亮对应应用。",
                side: "left"
            },
            {
                rect: rightPanelItem.restBtnGlobalRect(),
                title: "休息倒计时界面",
                body: "点此按钮进入全屏休息倒计时。倒计时结束或点「跳过本轮」后自动退出。",
                side: "top"
            },
            {
                // onEnter 用 Qt.callLater 延迟执行，确保在 open=true→load() 之后再设 notifyEnabled=false
                // 否则 load() 会读 config 把 notifyEnabled 重置回 true
                rect: settingsPage.cardCompactRect(),
                title: "设置 · 常规",
                body: "无操作暂停时长、开机自启、启动勿扰、窗口关闭行为。",
                side: "right",
                settingsStep: true,
                onEnter: function() {
                    Qt.callLater(function() {
                        settingsPage.notifyEnabled = false;
                        settingsPage.scrollToTop();
                    });
                }
            },
            {
                // 进入时设置页已打开（从步骤5延续），load() 不再重跑，notifyEnabled=true 安全
                // callLater 等 notifyEnabled=true 引起的布局更新完成后再滚动
                // 离开时自动保存（applyOnly），页面由 Connections 负责关闭
                rect: settingsPage.notifySectionGlobalRect(),
                title: "设置 · 休息提醒",
                body: "设置间隔、时长和声音。点「下一步」自动保存。",
                side: "right",
                settingsStep: true,
                onEnter: function() {
                    settingsPage.notifyEnabled = true;
                    Qt.callLater(function() { settingsPage.scrollToBottom(); });
                },
                onLeave: function() { settingsPage.applyOnly(); }
            },
            {
                // 通知气泡是独立的系统级窗口（屏幕右下角），不在主窗口内
                // 用 cardAlign:"bottomRight" 让说明卡片固定到右下角，无聚光灯
                rect: Qt.rect(-100, -100, 1, 1),
                title: "休息提醒通知",
                body: "到达设定间隔后，屏幕右下角弹出提醒气泡（已触发，请看屏幕右下角）。点「跳过本轮」可停止本轮提醒，或点「立刻休息」立即开始。",
                side: "bottom",
                cardAlign: "bottomRight",
                onEnter: function() { root._demoNotify(); }
            },
            {
                rect: ur(gr(tbAppSettings), gr(tbBlacklist)),
                title: "应用管理",
                body: "「应用设置」改名、归类、设前台勿扰；「黑名单」排除不想统计的程序。",
                side: "bottom"
            },
            {
                rect: leftPanelItem.viewTabsGlobalRect(),
                title: "分类视图",
                body: "切到「分类」查看各类别汇总时长，把握各类活动的使用习惯。",
                side: "right"
            },
            {
                rect: ur(gr(tbImport), gr(tbExport)),
                title: "数据备份",
                body: "定期「导出」备份数据；更换设备时「导入」恢复。",
                side: "bottom"
            }
        ];
        onboarding.currentStep = 0;
        onboarding.active = true;
    }

    // 引导中自动开/关设置页：标有 settingsStep:true 的步骤自动打开设置，其余步骤自动关闭
    Connections {
        target: onboarding
        function onCurrentStepChanged() {
            var s = onboarding.steps[onboarding.currentStep];
            settingsPage.open = !!(s && s.settingsStep);
        }
        function onActiveChanged() {
            if (!onboarding.active) settingsPage.open = false;
        }
    }

    OnboardingOverlay {
        id: onboarding
        onFinished: { if (root._settingsBridgeReady) settingsBridge.setShowOnboarding(false); }
        onSkipped:  { if (root._settingsBridgeReady) settingsBridge.setShowOnboarding(false); }
    }

    // ── 内联组件 ──

    // 缩放热区：按下即交给系统做无边框缩放（startSystemResize）。
    component ResizeZone: MouseArea {
        property int edges: 0
        property int cur: Qt.ArrowCursor
        hoverEnabled: true
        cursorShape: cur
        acceptedButtons: Qt.LeftButton
        onPressed: root.startSystemResize(edges)
    }

    // 窗口控制按钮（46x36，hover 白底/关闭红底）。图标全部矢量绘制（min/max/restore/close）。
    component WinBtn: Rectangle {
        id: wb
        property string kind: ""        // min|max|restore|close
        property bool danger: false
        signal clicked()
        width: 46; height: 36
        color: wbMa.containsMouse ? (danger ? "#e81123" : "#1affffff") : "transparent"
        readonly property color ink: wbMa.containsMouse && danger ? "#ffffff" : "#cbd5e1"

        Item {
            anchors.centerIn: parent
            width: 11; height: 11
            // 最小化：底部横线
            Rectangle { visible: wb.kind === "min"; anchors.verticalCenter: parent.verticalCenter; width: 11; height: 1.3; color: wb.ink }
            // 最大化：方框
            Rectangle { visible: wb.kind === "max"; anchors.fill: parent; color: "transparent"; border.color: wb.ink; border.width: 1.3; radius: 0.5 }
            // 还原：双层方框（后框在上、前框最后画压住交叠处）
            Item {
                visible: wb.kind === "restore"; anchors.fill: parent
                Rectangle { x: 2.5; y: 0; width: 8.5; height: 8.5; color: "transparent"; border.color: wb.ink; border.width: 1.3; radius: 0.5 }
                Rectangle { x: 0; y: 2.5; width: 8.5; height: 8.5; color: wb.color; border.color: wb.ink; border.width: 1.3; radius: 0.5 }
            }
            // 关闭：X（两条斜线）
            Item {
                visible: wb.kind === "close"; anchors.fill: parent
                Rectangle { anchors.centerIn: parent; width: 14.5; height: 1.3; color: wb.ink; rotation: 45 }
                Rectangle { anchors.centerIn: parent; width: 14.5; height: 1.3; color: wb.ink; rotation: -45 }
            }
        }
        MouseArea { id: wbMa; anchors.fill: parent; hoverEnabled: true; onClicked: wb.clicked() }
    }

    // 工具栏 ghost 按钮（.btn-ghost：透明 / hover bg-white/10 / 圆角 / 图标 + 文字，web px-3 py-1.5 text-xs，icon mr-1.5）
    component ToolBtn: Rectangle {
        id: tb
        property string icon: ""
        property string label: ""
        signal clicked()
        implicitWidth: tbRow.implicitWidth + 30   // px-3 略宽
        height: 40; radius: 7
        color: tbMa.containsMouse ? "#1affffff" : "transparent"
        Row {
            id: tbRow
            anchors.centerIn: parent
            spacing: 9                              // icon mr-1.5
            ToolIcon { kind: tb.icon; tint: "#ffffff"; scale: 1.28; anchors.verticalCenter: parent.verticalCenter }
            Text { text: tb.label; color: "#ffffff"; font.pixelSize: 15; font.bold: true; anchors.verticalCenter: parent.verticalCenter }
        }
        MouseArea { id: tbMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: tb.clicked() }
    }
}
