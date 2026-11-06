#!/bin/sh
# Copies Keystone.app to ~/Applications. Does not touch the Dock.
S="$(cd "$(dirname "$0")/.." && pwd)/macos/Keystone.app"
mkdir -p "$HOME/Applications"
rm -rf "$HOME/Applications/Keystone.app"
cp -R "$S" "$HOME/Applications/" && touch "$HOME/Applications/Keystone.app"
echo "Drag Keystone from ~/Applications to your Dock"
