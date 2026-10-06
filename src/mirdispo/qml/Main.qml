// Mirdispo — share a Plasma desktop on a wireless display
// Copyright (C) 2026 Mirdispo contributors
//
// This program is free software: you can redistribute it and/or modify it
// under the terms of the GNU General Public License as published by the Free
// Software Foundation, either version 3 of the License, or (at your option)
// any later version.
//
// This program is distributed in the hope that it will be useful, but WITHOUT
// ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
// FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
// more details.
//
// You should have received a copy of the GNU General Public License along
// with this program. If not, see <https://www.gnu.org/licenses/>.
//
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    width: 780
    height: 560
    minimumWidth: 560
    minimumHeight: 420
    visible: true
    title: "Mirdispo"

    // With a system tray, closing the window keeps Mirdispo running there,
    // so a cast can go on while the window is out of the way.
    onClosing: (close) => {
        if (tray && tray.available) {
            close.accepted = false
            root.hide()
            tray.windowHidden()
        }
    }

    function openPage(component) {
        pageStack.replace(component.createObject(root))
    }

    globalDrawer: Kirigami.GlobalDrawer {
        title: "Network Displays"
        titleIcon: "io.github.hencyber.Mirdispo"
        actions: [
            Kirigami.Action {
                text: "Displays"
                icon.name: "video-display"
                onTriggered: root.openPage(displaysPage)
            },
            Kirigami.Action {
                text: "Diagnostics"
                icon.name: "tools-report-bug"
                onTriggered: {
                    displayBackend.refreshDiagnostics()
                    root.openPage(diagnosticsPage)
                }
            },
            Kirigami.Action {
                text: "About"
                icon.name: "help-about"
                onTriggered: root.openPage(aboutPage)
            }
        ]
    }

    Component.onCompleted: pageStack.push(displaysPage.createObject(root))

    Component {
        id: displaysPage
        Kirigami.Page {
            id: displaysRoot
            title: "Nearby displays"

            // Every card ends in an action button. Left to size themselves,
            // "Connect" and "Disconnect" come out different widths and the
            // column of buttons looks ragged, so they share one width wide
            // enough for the longest label.
            readonly property int actionWidth: Kirigami.Units.gridUnit * 8
            actions: [
                Kirigami.Action {
                    text: displayBackend.scanning ? "Searching…" : "Search again"
                    icon.name: "view-refresh"
                    enabled: !displayBackend.scanning
                    onTriggered: displayBackend.scan()
                }
            ]

            contentItem: ColumnLayout {
                spacing: Kirigami.Units.largeSpacing

                Kirigami.InlineMessage {
                    Layout.fillWidth: true
                    visible: displayBackend.demoMode
                    type: Kirigami.MessageType.Information
                    text: "Demo mode uses virtual displays and does not send media."
                }

                Kirigami.InlineMessage {
                    Layout.fillWidth: true
                    visible: displayBackend.errorText.length > 0
                    type: Kirigami.MessageType.Error
                    text: displayBackend.errorText
                    showCloseButton: true
                }

                // What band the receiver put this cast on, shown only when it
                // is worth knowing. A group owner chooses the channel and a
                // television that leaves the group on a social channel puts
                // the cast on 2.4 GHz, where the full picture will not fit.
                // Red while that is unanswered, green once it has been, gone
                // entirely when the link is good.
                Controls.Button {
                    id: linkButton
                    Layout.fillWidth: true
                    visible: displayBackend.linkTooSlow || displayBackend.linkMatched
                    enabled: displayBackend.linkTooSlow
                    icon.name: displayBackend.linkTooSlow ? "network-wireless-signal-weak" : "network-wireless"
                    text: displayBackend.linkTooSlow
                          ? "The receiver put this cast on " + displayBackend.linkBand
                            + " — send what it can carry"
                          : displayBackend.linkBand + " — sending what this link carries"
                    onClicked: displayBackend.matchLinkFormat()

                    // Attention while there is something to do, and none once
                    // it is done: a control that keeps asking for an answer
                    // already given is noise.
                    property color attention: displayBackend.linkTooSlow
                                              ? Kirigami.Theme.negativeTextColor
                                              : Kirigami.Theme.positiveTextColor
                    palette.buttonText: attention
                    opacity: 1.0
                    SequentialAnimation on opacity {
                        running: displayBackend.linkTooSlow
                        loops: Animation.Infinite
                        alwaysRunToEnd: true
                        NumberAnimation { to: 0.45; duration: 700; easing.type: Easing.InOutQuad }
                        NumberAnimation { to: 1.0;  duration: 700; easing.type: Easing.InOutQuad }
                    }
                }

                Kirigami.AbstractCard {
                    Layout.fillWidth: true
                    visible: displayBackend.status === "connecting" || displayBackend.status === "streaming"
                    contentItem: Item {
                    implicitHeight: statusRow.implicitHeight
                    RowLayout {
                        id: statusRow
                        anchors.fill: parent
                        Kirigami.Icon {
                            source: displayBackend.status === "streaming" ? "media-playback-start" : "view-refresh"
                            Layout.preferredWidth: Kirigami.Units.iconSizes.large
                            Layout.preferredHeight: width
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Controls.Label {
                                text: displayBackend.status === "streaming" ? "Screen sharing active" : "Connecting"
                                font.bold: true
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Controls.Label {
                                text: displayBackend.statusText
                                opacity: 0.75
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Controls.Label {
                                id: pictureLine
                                // The line is the control: a separate button would widen
                                // this column and carry the action button out of the one
                                // column every card's button shares.
                                property bool open: false
                                visible: displayBackend.pictureText !== ""
                                text: (open ? "\u25BE  " : "\u25B8  ") + displayBackend.pictureText
                                // Nothing here may change the width of this column, so the
                                // hint that it can be clicked is the pointer and a little
                                // more ink, neither of which takes any room.
                                opacity: pictureHover.hovered ? 0.9 : 0.6
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                                HoverHandler {
                                    id: pictureHover
                                    cursorShape: Qt.PointingHandCursor
                                }
                                TapHandler {
                                    onTapped: {
                                        pictureLine.open = !pictureLine.open
                                        displayBackend.setReporting(pictureLine.open)
                                    }
                                }
                            }
                            ColumnLayout {
                                visible: pictureLine.open && pictureLine.visible
                                spacing: 0
                                Layout.topMargin: Kirigami.Units.smallSpacing
                                Layout.fillWidth: true

                                Repeater {
                                    model: [
                                        { caption: "Sending",  slot: 0, unit: " fps" },
                                        { caption: "Carrying", slot: 1, unit: " Mbit/s" },
                                        { caption: "Dropped",  slot: 2, unit: "" },
                                        { caption: "Lately",   slot: 3, unit: "" },
                                        { caption: "Spacing",  slot: 4, unit: " ms" }
                                    ]
                                    delegate: RowLayout {
                                        required property var modelData
                                        spacing: Kirigami.Units.largeSpacing
                                        Controls.Label {
                                            text: modelData.caption
                                            opacity: 0.6
                                            Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                                        }
                                        Controls.Label {
                                            // Proportional digits make a changing number shuffle
                                            // sideways on every update. A fixed width and even
                                            // digits keep the column still when 9.9 becomes 10.1.
                                            text: displayBackend
                                                  ? (displayBackend.figures[modelData.slot] || "\u2014") + modelData.unit
                                                  : "\u2014"
                                            font.family: "monospace"
                                            horizontalAlignment: Text.AlignRight
                                            opacity: 0.75
                                            Layout.preferredWidth: Kirigami.Units.gridUnit * 6
                                        }
                                    }
                                }
                            }
                        }
                        // What can be done to this connection, kept in a column of
                        // its own so that more than one thing can be offered without
                        // the text beside it deciding where any of them sit. Every
                        // card's column is the same width, which is what keeps the
                        // buttons in one line down the window.
                        ColumnLayout {
                            Layout.preferredWidth: displaysRoot.actionWidth
                            Layout.minimumWidth: displaysRoot.actionWidth
                            Layout.maximumWidth: displaysRoot.actionWidth
                            Layout.alignment: Qt.AlignVCenter | Qt.AlignRight
                            spacing: Kirigami.Units.smallSpacing
                            Controls.Button {
                                text: "Disconnect"
                                icon.name: "network-disconnect"
                                Layout.fillWidth: true
                                onClicked: displayBackend.disconnect()
                            }
                        }
                    }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    // The card above already carries the status while a
                    // session is being set up, so this line stays out of
                    // its way rather than repeating it.
                    visible: displayBackend.status !== "connecting" && displayBackend.status !== "streaming"
                    Controls.BusyIndicator {
                        running: displayBackend.scanning
                        visible: running
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: width
                    }
                    Controls.Label {
                        text: displayBackend.statusText
                        opacity: 0.75
                    }
                    Item { Layout.fillWidth: true }
                }

                ListView {
                    id: displayList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: displayBackend.devicesModel
                    spacing: Kirigami.Units.smallSpacing
                    clip: true

                    delegate: Kirigami.AbstractCard {
                        required property string deviceId
                        required property string name
                        required property string description
                        required property int strength
                        width: displayList.width
                        contentItem: Item {
                        implicitHeight: displayRow.implicitHeight
                        RowLayout {
                            id: displayRow
                            anchors.fill: parent
                            Kirigami.Icon {
                                source: "video-display"
                                Layout.preferredWidth: Kirigami.Units.iconSizes.large
                                Layout.preferredHeight: width
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Controls.Label {
                                    text: name
                                    font.bold: true
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                                Controls.Label {
                                    text: description
                                    opacity: 0.7
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                            }
                            ColumnLayout {
                                Layout.preferredWidth: displaysRoot.actionWidth
                                Layout.minimumWidth: displaysRoot.actionWidth
                                Layout.maximumWidth: displaysRoot.actionWidth
                                Layout.alignment: Qt.AlignVCenter | Qt.AlignRight
                                spacing: Kirigami.Units.smallSpacing
                                Controls.Button {
                                    // "Connect" the first time, when there is nothing
                                    // to come back to. Afterwards it is a return to what
                                    // was being shared, and says so.
                                    text: displayBackend.canReuseSource ? "Reconnect" : "Connect"
                                    icon.name: "network-connect"
                                    Layout.fillWidth: true
                                    onClicked: displayBackend.connectToDevice(deviceId)
                                }
                                // Connecting shares whatever was shared last time, which
                                // is wanted until it is not. Only offered when there is
                                // something to be handed back: with nothing remembered,
                                // connecting asks anyway and this would do the same.
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Kirigami.Units.smallSpacing
                                    // Connecting shares whatever was shared last time, which
                                    // is wanted until it is not. Only offered when there is
                                    // something to be handed back: with nothing remembered,
                                    // connecting asks anyway and this would do the same.
                                    Controls.Button {
                                        text: "Switch source"
                                        icon.name: "exchange-positions-zorder"
                                        visible: displayBackend.canReuseSource
                                        Layout.fillWidth: true
                                        onClicked: displayBackend.connectAndChoose(deviceId)
                                    }
                                    // Casting the only screen there is leaves nowhere to
                                    // work, so one is made to cast instead. Square and
                                    // beside the others rather than a third full line,
                                    // because it is the rarer thing to want.
                                    Controls.Button {
                                        icon.name: "video-display"
                                        display: Controls.AbstractButton.IconOnly
                                        Layout.preferredWidth: height
                                        Layout.alignment: Qt.AlignRight
                                        Controls.ToolTip.visible: hovered
                                        Controls.ToolTip.text: "V-screen — make a screen to cast"
                                        onClicked: displayBackend.makeVirtualScreen(deviceId)
                                    }
                                }
                            }
                        }
                        }
                    }
                }

                    Kirigami.PlaceholderMessage {
                        Layout.fillWidth: true
                        visible: !displayBackend.scanning && displayList.count === 0
                        text: "No compatible display found"
                        explanation: "Make sure the display has Miracast enabled, then search again."
                        icon.name: "video-display"
                        helpfulAction: Kirigami.Action {
                            text: "Open diagnostics"
                            onTriggered: {
                                displayBackend.refreshDiagnostics()
                                root.openPage(diagnosticsPage)
                            }
                        }
                    }
            }
        }
    }

    Component {
        id: diagnosticsPage
        Kirigami.ScrollablePage {
            title: "Diagnostics"
            actions: Kirigami.Action {
                text: "Refresh"
                icon.name: "view-refresh"
                onTriggered: displayBackend.refreshDiagnostics()
            }
            ListView {
                id: diagnosticList
                model: displayBackend.diagnosticsModel
                spacing: Kirigami.Units.smallSpacing
                delegate: Kirigami.AbstractCard {
                    required property string label
                    required property bool ok
                    required property string detail
                    width: diagnosticList.width
                    contentItem: RowLayout {
                        Kirigami.Icon {
                            source: ok ? "dialog-ok-apply" : "dialog-cancel"
                            Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                            Layout.preferredHeight: width
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Controls.Label { text: label; font.bold: true }
                            Controls.Label { text: detail; wrapMode: Text.Wrap; Layout.fillWidth: true; opacity: 0.75 }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: aboutPage
        Kirigami.Page {
            title: "About"
            actions: [
                Kirigami.Action {
                    text: "Licence"
                    icon.name: "license"
                    onTriggered: root.openPage(licensePage)
                }
            ]
            contentItem: ColumnLayout {
                spacing: Kirigami.Units.largeSpacing

                Item { Layout.fillHeight: true }

                Kirigami.Icon {
                    source: "video-display"
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: Kirigami.Units.iconSizes.enormous
                    Layout.preferredHeight: width
                }
                Kirigami.Heading {
                    text: "Mirdispo"
                    level: 1
                    horizontalAlignment: Text.AlignHCenter
                    Layout.fillWidth: true
                }
                Controls.Label {
                    text: "Version " + displayBackend.appVersion
                    horizontalAlignment: Text.AlignHCenter
                    opacity: 0.7
                    Layout.fillWidth: true
                }
                Controls.Label {
                    text: "Share your Plasma desktop with Miracast displays"
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                Controls.Label {
                    // The engine that does the casting is someone else's work,
                    // so the credit belongs on the first page, not behind a menu.
                    text: "Built on GNOME Network Displays by Benjamin Berg, "
                        + "Christian Glombek and contributors"
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    opacity: 0.7
                    Layout.fillWidth: true
                }

                Item { Layout.fillHeight: true }

                // GPL-3 section 5d accepts a prominent item in a menu as the
                // way to reach the legal notices, so they live on their own
                // page instead of filling this one.
                Controls.Label {
                    text: "© 2026 Mirdispo contributors · GPL-3.0-or-later"
                    horizontalAlignment: Text.AlignHCenter
                    opacity: 0.6
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
        }
    }

    Component {
        id: licensePage
        Kirigami.ScrollablePage {
            title: "Licence"
            ColumnLayout {
                spacing: Kirigami.Units.largeSpacing

                Kirigami.Heading {
                    text: "No warranty"
                    level: 3
                    Layout.fillWidth: true
                }
                Controls.Label {
                    text: "This program is distributed in the hope that it will be useful, but "
                        + "WITHOUT ANY WARRANTY, without even the implied warranty of "
                        + "merchantability or fitness for a particular purpose."
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }

                Kirigami.Heading {
                    text: "Your rights"
                    level: 3
                    Layout.fillWidth: true
                }
                Controls.Label {
                    text: "This is free software. You may redistribute and modify it under the "
                        + "terms of the GNU General Public License, version 3 or any later "
                        + "version."
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                Controls.Button {
                    id: licenceToggle
                    // The licence is looked up where this system keeps it and shown
                    // here, rather than naming a path that exists on some
                    // distributions and not on others.
                    text: licenceBody.visible ? "Hide the licence" : "Read the licence"
                    icon.name: "license"
                    onClicked: licenceBody.visible = !licenceBody.visible
                }
                Controls.TextArea {
                    id: licenceBody
                    visible: false
                    readOnly: true
                    wrapMode: Text.Wrap
                    font.family: "monospace"
                    text: displayBackend.licenceText
                    Layout.fillWidth: true
                }

                Kirigami.Heading {
                    text: "Built on GNOME Network Displays"
                    level: 3
                    Layout.fillWidth: true
                }
                Controls.Label {
                    text: "The streaming engine is GNOME Network Displays 0.99.0, maintained "
                        + "by Benjamin Berg and Christian Glombek with Anupam Kumar, Pedro "
                        + "Sader Azevedo and many other contributors. It is used here under "
                        + "the same licence and was modified in September 2026. "
                        + (displayBackend.sourceLocation.length > 0
                           ? "Its source and every change made to it are in "
                             + displayBackend.sourceLocation + "."
                           : "Its source and every change made to it are distributed "
                             + "with the source of this program.")
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }

                Kirigami.Heading {
                    text: "Names"
                    level: 3
                    Layout.fillWidth: true
                }
                Controls.Label {
                    text: "Miracast and Wi-Fi Display are trademarks of Wi-Fi Alliance, "
                        + "Chromecast of Google LLC, GNOME of the GNOME Foundation, and "
                        + "KDE and Plasma of KDE e.V. They are used only to say what this "
                        + "program works with. It is not certified, endorsed by or "
                        + "affiliated with any of them."
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }

                Item { Layout.fillHeight: true }
            }
        }
    }

    // Between making the screen and sharing it. The screen exists by the time
    // this is shown, and Plasma has already put it somewhere, so this says
    // where it went and offers the one place that can be changed before the
    // desktop asks what to share.
    Kirigami.PromptDialog {
        id: virtualScreenDialog
        title: "Virtual display created"
        // Set when the dialog is left by the button rather than dismissed, so
        // that going on to share it is not mistaken for changing one's mind
        // and does not take the screen away again.
        property bool goingOn: false
        subtitle: "A 1080p screen is placed to the right of your other screens.\n\n"
                + "To change resolution or position, open the display settings. "
                + "Continue to pick it as the screen to share."
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Open display settings"
                icon.name: "preferences-desktop-display"
                onTriggered: displayBackend.openDisplaySettings()
            },
            Kirigami.Action {
                text: "Continue"
                icon.name: "dialog-ok"
                onTriggered: {
                    virtualScreenDialog.goingOn = true
                    virtualScreenDialog.close()
                    displayBackend.shareVirtualScreen()
                }
            }
        ]
        // Dismissed rather than gone on with: the screen was made for a cast
        // that is not going to happen, so it goes away again.
        onRejected: if (!goingOn) displayBackend.dropVirtualScreen()
        onClosed: if (!goingOn && displayBackend.virtualScreenReady) displayBackend.dropVirtualScreen()
    }

    Connections {
        target: displayBackend
        function onVirtualScreenChanged() {
            if (displayBackend.virtualScreenReady) {
                virtualScreenDialog.goingOn = false
                virtualScreenDialog.open()
            } else {
                virtualScreenDialog.close()
            }
        }
    }
}
