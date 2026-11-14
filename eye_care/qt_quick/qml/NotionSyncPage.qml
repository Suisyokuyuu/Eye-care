import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

// Reuse the original settings' controls, colors, spacing and overlay behavior.
Item {
    id: page
    objectName: "notionSyncPage"
    anchors.fill: parent
    property var bridge: null
    property bool open: false
    property bool includeSites: false
    property bool onStartup: false
    property bool daily: false
    property string days: "7"
    signal closed()
    visible: opacity > 0.01
    opacity: open ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    z: 125

    function load() {
        if (!bridge) return;
        var c = bridge.config;
        parentField.text = c.parent_page || "";
        dashboardField.text = c.dashboard_page || "";
        deviceField.text = c.device_name || "";
        tokenField.text = "";
        page.days = String(c.days || 7);
        page.includeSites = c.include_sites === true;
        page.onStartup = c.on_startup === true;
        page.daily = c.daily === true;
        timeField.text = c.time || "23:00";
    }
    function save() {
        if (!bridge) return false;
        var ok = bridge.saveSettings({parent_page: parentField.text, days: Number(page.days),
            include_sites: includeSites, on_startup: onStartup, daily: daily, time: timeField.text,
            device_name: deviceField.text, dashboard_page: dashboardField.text}, tokenField.text);
        if (ok) tokenField.text = "";
        return ok;
    }
    onOpenChanged: {
        if (open) { load(); bodyFlick.contentY = 0; }
        else { tokenField.text = ""; hoverTip.hide(); }
    }
    Component.onCompleted: if (open) load()

    Rectangle {
        anchors.fill: parent; color: "#b3000000"
        MouseArea { anchors.fill: parent; onClicked: page.closed(); onWheel: function(wheel) { wheel.accepted = true } }
    }
    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 560)
        height: Math.min(parent.height - 48, body.implicitHeight + 152)
        radius: 12; color: "#0F172A"; border.color: "#1affffff"; border.width: 1
        MouseArea { anchors.fill: parent }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 24; spacing: 16
            RowLayout {
                Layout.fillWidth: true
                Text { text: "数据同步"; color: "#ffffff"; font.pixelSize: 24; font.bold: true }
                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 30; height: 30; radius: 6; color: closeMa.containsMouse ? "#1affffff" : "transparent"
                    Text { anchors.centerIn: parent; text: "×"; color: "#9CA3AF"; font.pixelSize: 24 }
                    MouseArea { id: closeMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.closed() }
                }
            }
            Flickable {
                id: bodyFlick
                objectName: "syncBody"
                Layout.fillWidth: true; Layout.fillHeight: true
                contentWidth: width; contentHeight: body.implicitHeight
                clip: true; boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: SettingsPage.ThemedSB {}
                ColumnLayout {
                    id: body; width: parent.width - 12; spacing: 14
                    enabled: page.bridge && !page.bridge.busy
                    opacity: enabled ? 1 : 0.65
                    SettingsPage.HelpText { text: "同步每日汇总到 Notion 日历与表格，供你和 AI 查看；同设备同一天更新原记录。" }
                    SettingsPage.FieldLabel { text: "Notion 数据仓库链接" }
                    SyncField { id: parentField; placeholderText: "粘贴正式数据仓库链接（旧版页面链接也可沿用）" }
                    SettingsPage.FieldLabel { text: "展示页链接（可选）" }
                    SyncField { id: dashboardField; placeholderText: "打开统计页时使用；留空则打开数据仓库" }
                    SettingsPage.FieldLabel { text: "Notion API 密钥" }
                    SyncField {
                        id: tokenField
                        echoMode: TextInput.Password
                        placeholderText: page.bridge && page.bridge.config.has_token ? "已安全保存，留空沿用" : "粘贴密钥后保存"
                        inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        SettingsPage.HelpText { text: "密钥使用 Windows 当前用户加密保存，不包含在导出文件中。" }
                        Text {
                            text: "清除密钥"; color: "#60A5FA"; font.pixelSize: 12
                            visible: page.bridge && page.bridge.config.has_token
                            enabled: page.bridge && !page.bridge.busy
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: page.bridge.clearToken() }
                        }
                    }
                    SettingsPage.Divider {}
                    SettingsPage.FieldLabel { text: "本机名称" }
                    SyncField { id: deviceField; placeholderText: "例如：家里电脑（留空自动命名）"; maximumLength: 60 }
                    SettingsPage.HelpText { text: "不同设备分行保存，互不覆盖。改名称不会新建设备；复制历史数据后请按设备筛选，避免重复相加。" }
                    RowLayout {
                        Layout.fillWidth: true
                        SettingsPage.FieldLabel { text: "导出范围" }
                        Item { Layout.fillWidth: true }
                        SettingsPage.Select {
                            value: page.days
                            model: [{v:"1", t:"今天"}, {v:"7", t:"最近 7 天"}, {v:"30", t:"最近 30 天"}]
                            onPicked: page.days = v
                        }
                    }
                    SettingsPage.Check { text: "包含网站统计"; checked: page.includeSites; onToggled: page.includeSites = v }
                    SettingsPage.HelpText { text: "仅含每日总时长、应用/分类汇总和休息次数，不含逐分钟记录或单次休息时间。网站统计默认关闭。" }
                    SettingsPage.Divider {}
                    SettingsPage.Check {
                        id: startupCheck
                        objectName: "startupCheck"
                        text: "启动后同步一次"; checked: page.onStartup; onToggled: page.onStartup = v
                        tip: "每次打开软件约 15 秒后同步一次。不是每 15 秒同步；关闭主窗口但仍在托盘运行，也不会再次触发。若该次失败，可手动重试；每日定时同步独立执行。"
                        onTipRequested: function(mx, my) { hoverTip.show(tip, startupCheck.mapToItem(page, mx, my)); }
                        onTipDismissed: hoverTip.hide()
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        SettingsPage.Check {
                            id: dailyCheck
                            text: "每天定时同步"; checked: page.daily; onToggled: page.daily = v
                            tip: "按电脑本地时间每天同步一次，需软件保持运行（托盘运行也可以）。首次开启从下一个设定时间开始；关机或休眠错过时，在下次启动或恢复后补一次。失败后至少间隔 15 分钟再重试。"
                            onTipRequested: function(mx, my) { hoverTip.show(tip, dailyCheck.mapToItem(page, mx, my)); }
                            onTipDismissed: hoverTip.hide()
                        }
                        Item { Layout.fillWidth: true }
                        SyncField { id: timeField; enabled: page.daily; opacity: enabled ? 1 : 0.5; Layout.fillWidth: false; Layout.preferredWidth: 90; placeholderText: "23:00"; horizontalAlignment: TextInput.AlignHCenter; maximumLength: 5 }
                    }
                    SettingsPage.HelpText { text: "启动同步：每次打开约 15 秒后，仅一次。定时同步：每天所设时间；悬停选项可看说明。" }
                    SettingsPage.Divider {}
                    Text {
                        Layout.fillWidth: true; text: page.bridge ? page.bridge.message : ""
                        color: page.bridge && page.bridge.error ? "#F87171" : "#D1D5DB"
                        font.pixelSize: 13; wrapMode: Text.WordWrap
                    }

                }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                SettingsPage.HelpText { text: "最近成功：" + (page.bridge ? page.bridge.lastSuccess : "尚未同步") }
                SettingsPage.FooterBtn {
                    objectName: "openNotionButton"; text: "打开统计页"; primary: false
                    Layout.preferredWidth: 104; implicitHeight: 30
                    onClicked: page.bridge.openPage(dashboardField.text || parentField.text)
                }
                SettingsPage.FooterBtn {
                    text: "复制链接"; primary: false; Layout.preferredWidth: 80; implicitHeight: 30
                    onClicked: page.bridge.copyPageLink(dashboardField.text || parentField.text)
                }
            }
            SettingsPage.HelpText { text: page.bridge ? page.bridge.linkMessage : ""; visible: text !== "" }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                SettingsPage.FooterBtn { Layout.fillWidth: true; text: "保存设置"; primary: false; enabled: page.bridge && !page.bridge.busy; opacity: enabled ? 1 : 0.5; onClicked: page.save() }
                SettingsPage.FooterBtn { Layout.fillWidth: true; text: page.bridge && page.bridge.busy ? "处理中…" : "立即同步"; enabled: page.bridge && !page.bridge.busy; opacity: enabled ? 1 : 0.5; onClicked: { if (page.save()) page.bridge.syncNow() } }
                SettingsPage.FooterBtn { Layout.fillWidth: true; text: "导出 JSON"; primary: false; enabled: page.bridge && !page.bridge.busy; opacity: enabled ? 1 : 0.5; onClicked: { if (page.save()) page.bridge.exportJson() } }
            }
        }
    }
    HoverHint { id: hoverTip; objectName: "syncHoverHint" }
    component SyncField: TextField {
        Layout.fillWidth: true; implicitHeight: 38
        color: "#ffffff"; placeholderTextColor: "#6B7280"; font.pixelSize: 14
        leftPadding: 12; rightPadding: 12; selectByMouse: true
        background: Rectangle { radius: 8; color: "#1E293B"; border.color: parent.activeFocus ? "#803b82f6" : "#1affffff"; border.width: parent.activeFocus ? 2 : 1 }
    }
}
