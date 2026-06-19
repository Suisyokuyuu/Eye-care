import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic

// 分类详情（复刻 web #categoryDetailModal）：列出该分类下的应用卡片，点卡片→应用详情。
// 数据走 appsBridge.appsList（客户端按 category 过滤）；title=分类名。
Item {
    id: page
    anchors.fill: parent
    // 渐入渐出
    visible: opacity > 0.01
    opacity: open ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    z: 105                          // 在应用设置(100)之上、应用详情(110)之下

    required property var bridge          // AppsBridge
    property bool open: false
    property string category: ""
    property string searchText: ""
    signal closed()
    signal openApp(string appShort)

    onOpenChanged: if (open) { searchText = ""; bridge.reload(); }

    function _match(a) {
        if ((a.category || "") !== page.category) return false;
        if (searchText === "") return true;
        var s = searchText.toLowerCase();
        return (a.display_name || "").toLowerCase().indexOf(s) >= 0
            || (a.app_short || "").toLowerCase().indexOf(s) >= 0;
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
                Text { text: "分类详情 · " + page.category; color: "#ffffff"; font.pixelSize: 22; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
                CloseX { onClicked: page.closed() }
            }
            Text {
                Layout.fillWidth: true
                text: "点击应用卡片进入详情并编辑该应用的分类、显示名等。"
                color: "#9CA3AF"; font.pixelSize: 13; wrapMode: Text.WordWrap
            }

            Rectangle {
                Layout.fillWidth: true; height: 38; radius: 8
                color: "#1E293B"; border.color: searchTf.activeFocus ? "#803b82f6" : "#1affffff"; border.width: searchTf.activeFocus ? 2 : 1
                TextField {
                    id: searchTf
                    anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                    verticalAlignment: TextInput.AlignVCenter
                    color: "#ffffff"; font.pixelSize: 14; selectByMouse: true
                    placeholderText: "按应用名搜索…"; placeholderTextColor: "#6B7280"
                    background: Item {}
                    onTextChanged: page.searchText = text
                }
            }

            Text {
                visible: page._filtered().length === 0
                Layout.fillWidth: true; Layout.topMargin: 4
                text: "该分类下暂无应用"; color: "#6B7280"; font.pixelSize: 13
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
                    border.color: rowMa.containsMouse ? "#4d3b82f6" : "#0dffffff"; border.width: 1
                    color: rowMa.containsMouse ? "#cc0b1120" : "#bf162032"
                    MouseArea {
                        id: rowMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: page.openApp(modelData.app_short)
                    }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14; spacing: 12
                        Rectangle {
                            Layout.alignment: Qt.AlignVCenter
                            width: 34; height: 34; radius: 6; color: "#1f3b82f6"
                            readonly property bool hasIcon: modelData.icon && modelData.icon !== ""
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
        width: 30; height: 30; radius: 6; Layout.alignment: Qt.AlignVCenter
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
