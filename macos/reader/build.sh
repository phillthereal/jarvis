#!/bin/sh
# Builds the KeystoneReader command-line helper into ~/agentic-os/bin (gitignored). Plain executable: Vision and
# PDFKit need no TCC permission.
set -e
D="$(cd "$(dirname "$0")" && pwd)"; B="$D/../../bin"
mkdir -p "$B"
DEVELOPER_DIR=/Library/Developer/CommandLineTools swiftc -O -target arm64-apple-macos14 "$D/main.swift" -o "$B/KeystoneReader"
codesign -s - --force "$B/KeystoneReader"
echo "built $(cd "$B" && pwd)/KeystoneReader"
