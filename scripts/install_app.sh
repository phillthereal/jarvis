#!/bin/sh
# Copies Jarvis.app to ~/Applications. Does not touch the Dock.
S="$(cd "$(dirname "$0")/.." && pwd)/macos/Jarvis.app"
mkdir -p "$HOME/Applications"
rm -rf "$HOME/Applications/Jarvis.app"
cp -R "$S" "$HOME/Applications/" && touch "$HOME/Applications/Jarvis.app"
echo "Drag Jarvis from ~/Applications to your Dock"
