import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

// 应用设置列表（step3，复刻 web #appSettingsModal）：搜索 + 已记录应用卡片，点卡片→详情。
// 数据走 contextProperty appsBridge：appsList=[{app_short,display_name,category}]。
// 点某应用发 openApp(appShort)，由外壳打开 AppDetailPage。
Item {
    id: page
    anchors.fill: parent
    // 渐入渐出
    visible: opacity > 0.01
    opacity: open ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    z: 100

    required property var bridge          // AppsBridge
    property bool open: false
    property string searchText: ""
    signal closed()
    signal openApp(string appShort)

    onOpenChanged: if (open) { searchText = ""; bridge.reload(); }

    function _match(a) {
        if (searchText === "") return true;
        var s = searchText.toLowerCase();
        return (a.display_name || "").toLowerCase().indexOf(s) >= 0
            || (a.app_short || "").toLowerCase().indexOf(s) >= 0
            || (a.category || "").toLowerCase().indexOf(s) >= 0;
    }
    function _filtered() {
        var src = page.bridge ? page.bridge.appsList : [];
        var out = [];
        for (var i = 0; i < src.length; i++) if (_match(src[i])) out.push(src[i]);
        return out;
    }

    Rectangle {
        anchors.fill: parent; color: "#b3000000"
        MouseArea { anchors.fill: parent; onClicked: page.closed(); onWheel: function(wheel){ wheel.accepted = true } }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 672)
        height: Math.min(parent.height - 48, 620)
        radius: 12; color: "#0F172A"; border.color: "#1affffff"; border.width: 1
        MouseArea { anchors.fill: parent }

        ColumnLayout {
            anchors.fill: parent; anchors.margins: 32; spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Text { text: "应用设置"; color: "#ffffff"; font.pixelSize: 24; font.bold: true }
                Item { Layout.fillWidth: true }
                CloseX { onClicked: page.closed() }
            }
            Text {
                Layout.fillWidth: true
                text: "点击应用卡片进入详情并编辑该应用的分类、显示名、前台自动勿扰等。"
                color: "#9CA3AF"; font.pixelSize: 13; wrapMode: Text.WordWrap
            }

            // 搜索框
            Rectangle {
                Layout.fillWidth: true; height: 38; radius: 8
                color: "#1E293B"; border.color: searchTf.activeFocus ? "#803b82f6" : "#1affffff"; border.width: searchTf.activeFocus ? 2 : 1
                TextField {
                    id: searchTf
                    anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                    verticalAlignment: TextInput.AlignVCenter
                    color: "#ffffff"; font.pixelSize: 14; selectByMouse: true
                    placeholderText: "按应用名或分类搜索…"
                    placeholderTextColor: "#6B7280"
                    background: Item {}
                    onTextChanged: page.searchText = text
                }
            }

            // 列表
            Text {
                visible: page._filtered().length === 0
                Layout.fillWidth: true; Layout.topMargin: 4
                text: (page.bridge && page.bridge.appsList.length === 0) ? "暂无已记录应用" : "无匹配结果"
                color: "#6B7280"; font.pixelSize: 13
            }
            ListView {
                id: list
                visible: page._filtered().length > 0
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true; spacing: 8
                model: page._filtered()
                ScrollBar.vertical: ThemedSB {}

                delegate: Rectangle {
                    required property var modelData
                    width: list.width - 12; height: 56; radius: 6
                    // 扁平单色（去掉纵向渐变凹凸感），hover 加深 + 蓝边
                    border.color: rowMa.containsMouse ? "#4d3b82f6" : "#0dffffff"; border.width: 1
                    color: rowMa.containsMouse ? "#cc0b1120" : "#bf162032"
                    MouseArea {
                        id: rowMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: page.openApp(modelData.app_short)
                    }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14; spacing: 12
                        // 应用图标（真实 exe 图标 data_url）+ 首字母兜底
                        Rectangle {
                            Layout.alignment: Qt.AlignVCenter
                            width: 34; height: 34; radius: 6; color: "#1f3b82f6"
                            readonly property bool hasIcon: (modelData.icon !== undefined) && (modelData.icon !== "")
                            Image {
                                anchors.fill: parent; anchors.margins: 4
                                visible: parent.hasIcon
                                source: parent.hasIcon ? modelData.icon : ""
                                fillMode: Image.PreserveAspectFit; smooth: true; asynchronous: true; cache: true
                            }
                            Text {
                                anchors.centerIn: parent; visible: !parent.hasIcon
                                text: (modelData.display_name || modelData.app_short).charAt(0).toUpperCase()
                                color: "#60A5FA"; font.pixelSize: 15; font.bold: true
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; Layout.alignment: Qt.AlignVCenter; spacing: 2
                            Text { text: modelData.display_name || modelData.app_short; color: "#f1f5f9"; font.pixelSize: 14; font.weight: Font.Medium; elide: Text.ElideRight; Layout.fillWidth: true }
                            Text { text: modelData.app_short; color: "#9CA3AF"; font.pixelSize: 12; elide: Text.ElideRight; Layout.fillWidth: true }
                        }
                        // 分类胶囊
                        Rectangle {
                            Layout.alignment: Qt.AlignVCenter
                            visible: (modelData.category || "") !== ""
                            radius: 10; height: 22; width: catTxt.implicitWidth + 18
                            color: "#14ffffff"
                            Text { id: catTxt; anchors.centerIn: parent; text: modelData.category || ""; color: "#cbd5e1"; font.pixelSize: 11 }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                FooterBtn { Layout.fillWidth: true; text: "关闭"; onClicked: page.closed() }
            }
        }
    }

    // ── 内联组件 ──
    component CloseX: Rectangle {
        signal clicked()
        width: 30; height: 30; radius: 6
        color: xMa.containsMouse ? "#1affffff" : "transparent"
        Item {
            anchors.centerIn: parent; width: 14; height: 14
            Rectangle { anchors.centerIn: parent; width: 15; height: 1.5; radius: 0.75; color: xMa.containsMouse ? "#ffffff" : "#9CA3AF"; rotation: 45 }
            Rectangle { anchors.centerIn: parent; width: 15; height: 1.5; radius: 0.75; color: xMa.containsMouse ? "#ffffff" : "#9CA3AF"; rotation: -45 }
        }
        MouseArea { id: xMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.clicked() }
    }
    component FooterBtn: Rectangle {
        property string text: ""
        signal clicked()
        implicitHeight: 40; radius: 8
        color: fbMa.containsMouse ? "#0F172A" : "#1E293B"
        border.color: "#1affffff"; border.width: 1
        Text { anchors.centerIn: parent; text: parent.text; color: "#ffffff"; font.pixelSize: 14; font.weight: Font.Medium }
        MouseArea { id: fbMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.clicked() }
    }
    component ThemedSB: ScrollBar {
        id: sb
        policy: ScrollBar.AsNeeded; implicitWidth: 8; padding: 0
        contentItem: Rectangle { implicitWidth: 8; radius: 4; color: sb.pressed ? "#d960a5fa" : (sb.hovered ? "#b33b82f6" : "#733b82f6") }
        background: Rectangle { implicitWidth: 8; radius: 4; color: "#660f172a" }
    }
}
