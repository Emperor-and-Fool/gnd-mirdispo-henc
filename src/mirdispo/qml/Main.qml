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
                                text: displayBackend.pictureText
                                visible: text !== ""
                                opacity: 0.6
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                        Controls.Button {
                            text: "Disconnect"
                            icon.name: "network-disconnect"
                            Layout.preferredWidth: displaysRoot.actionWidth
                            Layout.alignment: Qt.AlignVCenter | Qt.AlignRight
                            onClicked: displayBackend.disconnect()
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
                            Controls.Button {
                                text: "Connect"
                                icon.name: "network-connect"
                                Layout.preferredWidth: displaysRoot.actionWidth
                                Layout.alignment: Qt.AlignVCenter | Qt.AlignRight
                                onClicked: displayBackend.connectToDevice(deviceId)
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
}
