#!/bin/sh
# Builds KeystoneCalendar.app into ~/Applications (read-only calendar helper for the Plan panel).
set -e
D="$(cd "$(dirname "$0")" && pwd)"; A="$HOME/Applications/KeystoneCalendar.app"
rm -rf "$A"; mkdir -p "$A/Contents/MacOS"
cp "$D/Info.plist" "$A/Contents/"
DEVELOPER_DIR=/Library/Developer/CommandLineTools swiftc -O -target arm64-apple-macos14 "$D/main.swift" -o "$A/Contents/MacOS/KeystoneCalendar"
codesign -s - --force "$A"
echo "built $A"
