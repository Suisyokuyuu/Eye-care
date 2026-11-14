import QtQuick
import QtQuick.Effects

// Sample the background alone, so foreground text and charts remain sharp.
Rectangle {
    id: surface
    property var backdrop: null
    property real tintOpacity: 0.68
    readonly property bool glassActive: backdrop !== null
    radius: 8
    border.color: "#1affffff"; border.width: 1
    color: "transparent"
    gradient: glassActive ? null : fallbackGradient
    Gradient {
        id: fallbackGradient
        GradientStop { position: 0.00; color: "#26344b" }
        GradientStop { position: 0.25; color: "#1c2637" }
        GradientStop { position: 0.55; color: "#121a28" }
        GradientStop { position: 1.00; color: "#141e2d" }
    }
    ShaderEffectSource {
        id: sample
        anchors.fill: parent
        sourceItem: surface.backdrop
        sourceRect: {
            if (!surface.backdrop) return Qt.rect(0, 0, 1, 1);
            var refresh = surface.backdrop.width + surface.backdrop.height + surface.width + surface.height
                + surface.parent.x + surface.parent.y;
            var p = surface.mapToItem(surface.backdrop, 0, 0);
            return Qt.rect(p.x, p.y, surface.width, surface.height);
        }
        visible: false; live: surface.glassActive
    }
    Rectangle {
        id: mask; anchors.fill: parent; radius: surface.radius
        color: "white"; visible: false
    }
    ShaderEffectSource {
        id: maskTexture; sourceItem: mask; anchors.fill: parent
        visible: false; live: surface.glassActive
    }
    MultiEffect {
        anchors.fill: parent; visible: surface.glassActive
        source: sample; blurEnabled: true; blurMax: 32; blur: 0.65
        autoPaddingEnabled: false; maskEnabled: true; maskSource: maskTexture
    }
    Rectangle {
        anchors.fill: parent; radius: surface.radius; visible: surface.glassActive
        color: Qt.rgba(0.035, 0.055, 0.095, surface.tintOpacity)
        border.color: surface.border.color; border.width: surface.border.width
    }
}
