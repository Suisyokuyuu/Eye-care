import QtQuick
import QtQuick.Shapes

// 工具栏矢量小图标（复刻 FontAwesome：cog/download/upload/th-large/ban/refresh）。
// 纯矢量(Rectangle + Shapes)，不赌 woff 字体、不用 emoji；HiDPI 锐利。14px 画布。
Item {
    id: ic
    property string kind: ""
    property color tint: "#cbd5e1"
    width: 14; height: 14

    // 设置：齿轮（8 齿绕中心 + 外环 + 中心点）
    Item {
        anchors.fill: parent; visible: ic.kind === "cog"
        Repeater {
            model: 8
            delegate: Rectangle {
                required property int index
                width: 2.2; height: 4; radius: 1; color: ic.tint
                x: ic.width / 2 - width / 2; y: 0          // 顶部中心，向下 4px
                // 绕图标中心(7,7) 旋转——在本矩形局部坐标即 (width/2, ic.height/2)
                transform: Rotation { origin.x: width / 2; origin.y: ic.height / 2; angle: index * 45 }
            }
        }
        Rectangle {   // 外环
            anchors.centerIn: parent; width: 9.5; height: 9.5; radius: 4.75
            color: "transparent"; border.color: ic.tint; border.width: 1.6
        }
        Rectangle { anchors.centerIn: parent; width: 3.4; height: 3.4; radius: 1.7; color: ic.tint }  // 中心点
    }

    // 导入：下箭头（竖杆 + V 形箭头）+ 托盘底线（fa-download）
    Shape {
        anchors.fill: parent; visible: ic.kind === "download"
        antialiasing: true; preferredRendererType: Shape.CurveRenderer
        ShapePath {                                  // 竖杆 + 向下箭头
            strokeColor: ic.tint; strokeWidth: 1.4; fillColor: "transparent"
            capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            startX: 7; startY: 1.5
            PathLine { x: 7; y: 8.6 }
        }
        ShapePath {
            strokeColor: ic.tint; strokeWidth: 1.4; fillColor: "transparent"
            capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            startX: 4; startY: 5.6
            PathLine { x: 7; y: 8.8 }
            PathLine { x: 10; y: 5.6 }
        }
        ShapePath {                                  // 托盘底线
            strokeColor: ic.tint; strokeWidth: 1.4; fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            startX: 2.6; startY: 12.2
            PathLine { x: 11.4; y: 12.2 }
        }
    }

    // 导出：上箭头（竖杆 + ^ 形箭头）+ 托盘底线（fa-upload）
    Shape {
        anchors.fill: parent; visible: ic.kind === "upload"
        antialiasing: true; preferredRendererType: Shape.CurveRenderer
        ShapePath {                                  // 竖杆 + 向上箭头
            strokeColor: ic.tint; strokeWidth: 1.4; fillColor: "transparent"
            capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            startX: 7; startY: 9.4
            PathLine { x: 7; y: 2.4 }
        }
        ShapePath {
            strokeColor: ic.tint; strokeWidth: 1.4; fillColor: "transparent"
            capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            startX: 4; startY: 5.4
            PathLine { x: 7; y: 2.2 }
            PathLine { x: 10; y: 5.4 }
        }
        ShapePath {                                  // 托盘底线
            strokeColor: ic.tint; strokeWidth: 1.4; fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            startX: 2.6; startY: 12.2
            PathLine { x: 11.4; y: 12.2 }
        }
    }

    // 应用设置：2x2 网格（th-large）
    Item {
        anchors.fill: parent; visible: ic.kind === "grid"
        Rectangle { x: 1.5; y: 1.5; width: 4.6; height: 4.6; radius: 1; color: ic.tint }
        Rectangle { x: 7.9; y: 1.5; width: 4.6; height: 4.6; radius: 1; color: ic.tint }
        Rectangle { x: 1.5; y: 7.9; width: 4.6; height: 4.6; radius: 1; color: ic.tint }
        Rectangle { x: 7.9; y: 7.9; width: 4.6; height: 4.6; radius: 1; color: ic.tint }
    }

    // 黑名单：禁止（圆 + 斜杠）
    Item {
        anchors.fill: parent; visible: ic.kind === "ban"
        Rectangle { anchors.centerIn: parent; width: 12; height: 12; radius: 6; color: "transparent"; border.color: ic.tint; border.width: 1.5 }
        Rectangle { anchors.centerIn: parent; width: 1.5; height: 12; radius: 0.75; color: ic.tint; rotation: 45 }
    }

    // 检查更新：循环箭头（~300° 弧 + 箭头）
    Shape {
        anchors.fill: parent; visible: ic.kind === "refresh"
        antialiasing: true; preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: ic.tint; strokeWidth: 1.5; fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            startX: 11.5; startY: 4
            PathAngleArc { centerX: 7; centerY: 7; radiusX: 5; radiusY: 5; startAngle: -55; sweepAngle: 290; moveToStart: false }
        }
        // 箭头（弧起点处的小三角）
        ShapePath {
            strokeColor: "transparent"; fillColor: ic.tint
            startX: 11.5; startY: 4
            PathLine { x: 9.2; y: 4.2 }
            PathLine { x: 11.8; y: 6.6 }
            PathLine { x: 11.5; y: 4 }
        }
    }
}
