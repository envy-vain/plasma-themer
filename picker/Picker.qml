// plasma-themer overlay picker.
//   ←/→ or h/l  theme      ↑/↓ or k/j  wallpaper      Enter  apply      Esc  close      1-9  jump
//
// Deliberately effect-free: rounded cards and the blurred backdrop are pre-baked images (see picker.py),
// so this runs on weak GPUs and on the software renderer. `lite` additionally drops animations and
// translucency.
import QtQuick
import QtQuick.Window
import Qt.labs.folderlistmodel

Window {
    id: win
    // --resident: stay loaded but hidden and show when the hotkey drops a file into trigger/ (see picker.py).
    // Opening is then ~instant instead of a cold Qt start.
    readonly property bool resident: Qt.application.arguments.indexOf("--resident") >= 0
    readonly property string dataPath: Qt.application.arguments[Qt.application.arguments.length - 1]
    visible: !resident
    visibility: resident ? Window.Hidden : Window.FullScreen
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: lite ? (col.darker_background || "#000") : "transparent"
    title: "Themer"

    property var themes: []
    property int idx: 0
    property bool applying: false
    property bool lite: false
    readonly property var cur: themes.length ? themes[idx] : null
    readonly property var col: cur ? cur.colors : ({})
    // wallpaper choice per theme lives here, NOT in `themes`: replacing the model array rebuilt every card
    property var bgSel: []
    function wp(t, i) { return t && t.wallpapers.length ? t.wallpapers[bgSel[i] ?? t.bg] : null }
    function ms(n) { return lite ? 0 : n }

    property string lastData: ""
    function loadData() {
        const xhr = new XMLHttpRequest()
        xhr.open("GET", "file://" + dataPath, false)
        xhr.send()
        const data = JSON.parse(xhr.responseText)
        lite = !!data.lite
        bgSel = data.themes.map(t => t.bg)
        // Only replace the model when the data really changed: re-assigning it rebuilds every card and
        // backdrop (and re-uploads their textures), which made the resident picker fade in half-drawn.
        const themesJson = JSON.stringify(data.themes)
        if (themesJson !== lastData) { lastData = themesJson; themes = data.themes }
        idx = Math.max(0, themes.findIndex(t => t.slug === data.current))
        list.positionViewAtIndex(idx, PathView.Center)
    }
    function showPicker() {
        loadData()  // re-read: theme/wallpaper may have changed since the last open
        applying = false
        root.opacity = 0
        win.visibility = Window.FullScreen
        win.requestActivate()
        root.forceActiveFocus()
        root.opacity = 1
    }

    Component.onCompleted: {
        loadData()
        if (!resident) root.opacity = 1
    }

    FolderListModel {
        // inotify-backed (no polling): a new show.* file means "open"; the wrapper clears them on HIDDEN
        folder: resident ? "file://" + dataPath.substring(0, dataPath.lastIndexOf("/")) + "/trigger" : ""
        nameFilters: ["show.*"]
        showDirs: false
        onCountChanged: if (resident && count > 0 && !win.visible) showPicker()
    }

    function move(d) { if (!applying) idx = (idx + d + themes.length) % themes.length }
    function moveBg(d) {
        if (applying || !cur || cur.wallpapers.length < 2) return
        const b = bgSel.slice()
        b[idx] = (b[idx] + d + cur.wallpapers.length) % cur.wallpapers.length
        bgSel = b
    }
    function apply() {
        if (applying) return
        applying = true
        console.log("APPLY:" + cur.slug + ":" + (wp(cur, idx) ? wp(cur, idx).file : ""))
        quitTimer.start()
    }
    function close() { root.opacity = 0; closeTimer.start() }

    Timer { id: quitTimer; interval: lite ? 900 : 1700; onTriggered: win.close() }
    Timer {
        id: closeTimer; interval: ms(120) + 1
        onTriggered: {
            if (!resident) { Qt.quit(); return }
            win.visible = false
            console.log("HIDDEN")  // wrapper clears trigger/ so the next hotkey press counts as a change
        }
    }

    Item {
        id: root
        anchors.fill: parent
        opacity: 0
        focus: true
        Behavior on opacity { NumberAnimation { duration: ms(120); easing.type: Easing.OutCubic } }

        Keys.onPressed: (e) => {
            switch (e.key) {
            case Qt.Key_Left: case Qt.Key_H: case Qt.Key_Backtab: move(-1); break
            case Qt.Key_Right: case Qt.Key_L: case Qt.Key_Tab: move(1); break
            case Qt.Key_Up: case Qt.Key_K: moveBg(-1); break
            case Qt.Key_Down: case Qt.Key_J: moveBg(1); break
            case Qt.Key_Return: case Qt.Key_Enter: case Qt.Key_Space: apply(); break
            case Qt.Key_Escape: case Qt.Key_Q: if (!applying) close(); break
            default:
                const n = e.key - Qt.Key_1
                if (n >= 0 && n < themes.length && !applying) idx = n
            }
            e.accepted = true
        }

        // ---- backdrop: tiny pre-blurred images, upscaled (cheap) and crossfaded
        Repeater {
            model: themes
            Image {
                required property var modelData
                required property int index
                anchors.fill: parent
                // only the focused backdrop (and the one still fading out) is loaded: 1 image at startup, not 12
                readonly property bool live: index === idx || opacity > 0
                source: live && wp(modelData, index) ? "file://" + wp(modelData, index).blur : ""
                sourceSize: Qt.size(320, 180)
                fillMode: Image.PreserveAspectCrop
                smooth: true
                cache: false
                opacity: index === idx ? 1 : 0
                visible: opacity > 0
                Behavior on opacity { NumberAnimation { duration: ms(400); easing.type: Easing.InOutQuad } }
            }
        }
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0; color: Qt.alpha(col.darker_background || "#000", 0.45) }
                GradientStop { position: 1; color: Qt.alpha(col.darker_background || "#000", 0.8) }
            }
        }
        MouseArea { anchors.fill: parent; onClicked: if (!applying) win.close() }

        // ---- header
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height * 0.12
            spacing: 6
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: applying ? "Applying" : "Themes"
                color: col.bright_foreground || "white"
                font.pixelSize: 15; font.letterSpacing: 6; font.weight: Font.DemiBold
                font.capitalization: Font.AllUppercase
                opacity: 0.7
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: cur ? cur.name : ""
                color: col.bright_foreground || "white"
                font.pixelSize: 54; font.weight: Font.Light
            }
        }

        // ---- cards
        PathView {
            id: list
            readonly property real step: 460 * 0.82 + 84
            anchors.centerIn: parent
            width: parent.width
            height: 420
            model: themes
            currentIndex: idx
            pathItemCount: Math.min(themes.length, lite ? 3 : 5)
            preferredHighlightBegin: 0.5
            preferredHighlightEnd: 0.5
            highlightRangeMode: PathView.StrictlyEnforceRange
            highlightMoveDuration: ms(380)
            interactive: false
            path: Path {
                startX: list.width / 2 - list.step * list.pathItemCount / 2; startY: list.height / 2
                PathLine { x: list.width / 2 + list.step * list.pathItemCount / 2; y: list.height / 2 }
            }

            delegate: Item {
                id: card
                required property var modelData
                required property int index
                readonly property bool sel: index === idx
                width: 460; height: 380
                scale: sel ? (applying && !lite ? 1.08 : 1.0) : 0.82
                opacity: applying ? (sel ? 1 : 0) : (sel ? 1 : 0.45)
                Behavior on scale { NumberAnimation { duration: ms(380); easing.type: Easing.OutBack; easing.overshoot: 1.4 } }
                Behavior on opacity { NumberAnimation { duration: ms(300) } }

                Rectangle {  // accent ring
                    anchors.fill: frame; anchors.margins: -3; radius: 23
                    color: "transparent"
                    visible: card.sel
                    border.width: 2
                    border.color: card.modelData.colors.accent
                }
                Rectangle {
                    id: frame
                    width: parent.width; height: 300; radius: 20
                    color: card.modelData.colors.background
                    Image {  // pre-rounded PNG: no mask effect needed
                        anchors.fill: parent
                        source: wp(card.modelData, card.index) ? "file://" + wp(card.modelData, card.index).card : ""
                        sourceSize: Qt.size(460, 300)
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true  // decode off the UI thread: the window appears before the PNGs
                        cache: false
                    }
                    // fake terminal snippet in the theme's colors
                    Rectangle {
                        anchors { left: parent.left; bottom: parent.bottom; margins: 16 }
                        width: 210; height: 92; radius: 10
                        color: Qt.alpha(card.modelData.colors.background, 0.88)
                        border.color: Qt.alpha(card.modelData.colors.accent, 0.5)
                        Column {
                            anchors { fill: parent; margins: 10 }
                            spacing: 3
                            Row { spacing: 6
                                Text { text: "~/proj"; color: card.modelData.colors.accent; font.family: "monospace"; font.pixelSize: 12 }
                                Text { text: "main*"; color: card.modelData.colors.dark_foreground; font.family: "monospace"; font.pixelSize: 12 } }
                            Row { spacing: 6
                                Text { text: "❯"; color: card.modelData.colors.magenta; font.family: "monospace"; font.pixelSize: 12 }
                                Text { text: "git commit"; color: card.modelData.colors.blue; font.family: "monospace"; font.pixelSize: 12 }
                                Text { text: "-m \"ship\""; color: card.modelData.colors.green; font.family: "monospace"; font.pixelSize: 12 } }
                            Text { text: "✓ 3 files changed"; color: card.modelData.colors.green; font.family: "monospace"; font.pixelSize: 12 }
                            Text { text: "✗ 1 warning"; color: card.modelData.colors.yellow; font.family: "monospace"; font.pixelSize: 12 }
                        }
                    }
                    // wallpaper dots
                    Row {
                        anchors { right: parent.right; bottom: parent.bottom; margins: 14 }
                        spacing: 5
                        visible: card.sel && card.modelData.wallpapers.length > 1
                        Repeater {
                            model: card.sel ? card.modelData.wallpapers.length : 0
                            Rectangle {
                                required property int index
                                width: index === bgSel[card.index] ? 18 : 7; height: 7; radius: 4
                                color: index === bgSel[card.index] ? card.modelData.colors.accent : Qt.alpha("white", 0.5)
                                Behavior on width { NumberAnimation { duration: ms(200) } }
                            }
                        }
                    }
                }
                // swatches
                Row {
                    anchors { top: frame.bottom; topMargin: 22; horizontalCenter: parent.horizontalCenter }
                    spacing: 10
                    Repeater {
                        model: ["accent", "red", "orange", "yellow", "green", "cyan", "blue", "magenta"]
                        Rectangle {
                            required property string modelData
                            width: 26; height: 26; radius: 13
                            color: card.modelData.colors[modelData] || "transparent"
                            border.color: Qt.alpha("white", 0.15)
                        }
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: card.sel ? apply() : (idx = card.index)
                }
            }
        }

        // ---- footer hints / progress
        Item {
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: parent.height * 0.1 }
            width: 600; height: 40
            Text {
                anchors.centerIn: parent
                visible: !applying
                text: "←  →  theme      ↑  ↓  wallpaper      ⏎  apply      esc  close"
                color: col.dark_foreground || "#aaa"
                font.pixelSize: 14; font.letterSpacing: 1
            }
            Rectangle {
                visible: applying
                anchors.centerIn: parent
                width: 320; height: 4; radius: 2
                color: Qt.alpha(col.foreground || "white", 0.15)
                Rectangle {
                    height: parent.height; radius: 2
                    color: col.accent || "white"
                    width: lite ? parent.width : 0
                    NumberAnimation on width { running: applying && !lite; from: 0; to: 320; duration: 1500; easing.type: Easing.OutCubic }
                }
            }
        }
    }
}
