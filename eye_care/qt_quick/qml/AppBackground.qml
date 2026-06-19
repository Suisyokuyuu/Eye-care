import QtQuick
import QtQuick.Shapes

// 应用背景——复刻 web：bg-dark-400(#070D19) + 竖向渐变(slate-900→dark-400→#050a12)
// + 顶部中央蓝色径向辉光(#1e3a5f) + 星空。之前做成纯黑漏了渐变蓝。
Rectangle {
    id: bg
    // 竖向渐变（from-slate-900/80 via-dark-400 to-[#050a12]）
    gradient: Gradient {
        orientation: Gradient.Vertical
        GradientStop { position: 0.0; color: "#0f172a" }   // slate-900
        GradientStop { position: 0.5; color: "#070D19" }   // dark-400
        GradientStop { position: 1.0; color: "#050a12" }
    }

    // 顶部中央蓝色径向辉光（radial ellipse 80% 50% at 50% 0%, #1e3a5f → transparent, opacity~.6）
    Shape {
        anchors.fill: parent
        antialiasing: true
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: bg.width * 0.5; centerY: 0
                centerRadius: Math.max(bg.width, bg.height) * 0.62
                focalX: bg.width * 0.5; focalY: 0; focalRadius: 0
                GradientStop { position: 0.0; color: "#9a1e3a5f" }   // #1e3a5f @ ~0.6
                GradientStop { position: 1.0; color: "#001e3a5f" }   // 透明
            }
            startX: 0; startY: 0
            PathLine { x: bg.width; y: 0 }
            PathLine { x: bg.width; y: bg.height }
            PathLine { x: 0; y: bg.height }
            PathLine { x: 0; y: 0 }
        }
    }

    StarField { anchors.fill: parent }
}
