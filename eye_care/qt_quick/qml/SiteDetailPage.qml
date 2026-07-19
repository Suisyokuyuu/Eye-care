import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

// 站点详情（浏览器站点归并）：站点图标+名称、显示名编辑、子站点列表（近 90 天原始 host + 独立统计勾选框）。
// 数据走 contextProperty sitesBridge.detail（openSite 后填充）。变更即时生效并回溯（展示层合并）。
Item {
    id: page
    anchors.fill: parent
    visible: opacity > 0.01
    opacity: open ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    z: 120                        // 比 AppSettingsPage(100)/AppDetailPage(110) 高
    clip: true

    required property var bridge          // SitesBridge
    property bool open: false
    signal closed()

    property string dispName: ""

    function load() {
        var d = page.bridge ? page.bridge.detail : null;
        if (!d) return;
        dispName = d.displayNameOverride || "";
    }
    onOpenChanged: if (open) load()
    Connections { target: page.bridge; function onDetailChanged() { if (page.open) page.load() } }

    function _d() { return page.bridge ? page.bridge.detail : ({}); }
    function _applyName() {
        if (page.bridge) page.bridge.setDisplayName(page._d().siteKey || "", page.dispName);
    }

    Rectangle {
        anchors.fill: parent; color: "#b3000000"
        MouseArea { anchors.fill: parent; onClicked: page.closed(); onWheel: function(wheel){ wheel.accepted = true } }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 64, 620)
        height: Math.min(parent.height - 80, 560)
        radius: 12; color: "#0F172A"; border.color: "#1affffff"; border.width: 1
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
                    readonly property string iconUrl: page._d().icon || ""
                    readonly property bool hasIcon: iconUrl !== ""
                    Image {
                        anchors.fill: parent; anchors.margins: 4
                        visible: parent.hasIcon
                        source: parent.hasIcon ? parent.iconUrl : ""
                        fillMode: Image.PreserveAspectFit; smooth: true; asynchronous: true; cache: true
                    }
                    Text {
                        anchors.centerIn: parent; visible: !parent.hasIcon
                        text: (page._d().title || page._d().siteKey || "?").charAt(0).toUpperCase()
                        color: "#60A5FA"; font.pixelSize: 17; font.bold: true
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 1
                    Text {
                        text: page._d().title || page._d().siteKey || "站点详情"
                        color: "#ffffff"; font.pixelSize: 19; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true
                    }
                    Text {
                        text: page._d().siteKey || ""; color: "#6B7280"; font.pixelSize: 11; elide: Text.ElideMiddle; Layout.fillWidth: true
                    }
                }
                CloseX { onClicked: page.closed() }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: "#1affffff" }

            ColumnLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.margins: 16; spacing: 14

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
                            placeholderText: "留空则显示域名（如 mail.google.com → Gmail）"; placeholderTextColor: "#6B7280"
                            background: Item {}
                            text: page.dispName
                            onTextChanged: page.dispName = text
                            onEditingFinished: page._applyName()
                        }
                    }
                }

                // 子站点列表
                Text { text: "子站点（近 90 天）"; color: "#cbd5e1"; font.pixelSize: 13; font.weight: Font.DemiBold }
                Text {
                    Layout.fillWidth: true
                    text: "勾选「独立统计」可把子站点拆成单独的站点；取消则并回主域名。"
                    color: "#6B7280"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }

                Text {
                    visible: (page._d().hosts || []).length === 0
                    text: "暂无子站点记录"; color: "#6B7280"; font.pixelSize: 13
                }
                ListView {
                    id: hostList
                    visible: (page._d().hosts || []).length > 0
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; spacing: 6
                    model: page._d().hosts || []
                    ScrollBar.vertical: ThemedSB {}

                    delegate: Rectangle {
                        required property var modelData
                        width: hostList.width - 12; height: 48; radius: 6
                        color: "#bf162032"; border.color: "#0dffffff"; border.width: 1
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14; spacing: 12
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 1
                                Text { text: modelData.host; color: "#f1f5f9"; font.pixelSize: 13; font.weight: Font.Medium; elide: Text.ElideRight; Layout.fillWidth: true }
                                Text { text: modelData.dur || ""; color: "#9CA3AF"; font.pixelSize: 11 }
                            }
                            // 裸主域名行不给勾选框；其余行给「独立统计」勾选框
                            Text {
                                visible: modelData.checkable !== true
                                text: "主域名"; color: "#6B7280"; font.pixelSize: 11
                            }
                            Row {
                                visible: modelData.checkable === true
                                spacing: 8
                                Rectangle {
                                    width: 18; height: 18; radius: 4
                                    anchors.verticalCenter: parent.verticalCenter
                                    readonly property bool on: modelData.independent === true
                                    color: on ? "#3B82F6" : "#0B1120"
                                    border.color: on ? "#3B82F6" : "#33ffffff"; border.width: 1
                                    Text { anchors.centerIn: parent; visible: parent.on; text: "✓"; color: "#fff"; font.pixelSize: 12 }
                                    MouseArea {
                                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                        onClicked: page.bridge.setIndependent(modelData.host, modelData.independent !== true)
                                    }
                                }
                                Text {
                                    text: "独立统计"; color: "#cbd5e1"; font.pixelSize: 12
                                    anchors.verticalCenter: parent.verticalCenter
                                    MouseArea {
                                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                        onClicked: page.bridge.setIndependent(modelData.host, modelData.independent !== true)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: "#1affffff" }
            RowLayout {
                Layout.fillWidth: true; Layout.margins: 16; spacing: 8
                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 96; height: 38; radius: 8; color: closeMa.containsMouse ? "#0F172A" : "#1E293B"; border.color: "#1affffff"; border.width: 1
                    Text { anchors.centerIn: parent; text: "关闭"; color: "#fff"; font.pixelSize: 14; font.weight: Font.Medium }
                    MouseArea { id: closeMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { page._applyName(); page.closed(); } }
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
}
