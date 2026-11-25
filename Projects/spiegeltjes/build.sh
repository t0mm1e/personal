#!/bin/bash
# Bouwt Spiegeltjes.app naast deze map-inhoud. Oude build blijft bewaard als Spiegeltjes.app.<tijdstempel>.
set -e
cd "$(dirname "$0")"
swiftc -O -swift-version 5 main.swift -o Spiegeltjes.bin -framework AppKit -framework AVFoundation -framework CoreMediaIO
[ -d Spiegeltjes.app ] && mv Spiegeltjes.app "Spiegeltjes.app.$(date +%Y%m%d-%H%M%S)"
mkdir -p Spiegeltjes.app/Contents/MacOS
mv Spiegeltjes.bin Spiegeltjes.app/Contents/MacOS/Spiegeltjes
cat > Spiegeltjes.app/Contents/Info.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>nl.vangulick.spiegeltjes</string>
<key>CFBundleName</key><string>Spiegeltjes</string>
<key>CFBundleExecutable</key><string>Spiegeltjes</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>LSUIElement</key><true/>
<key>NSCameraUsageDescription</key><string>Spiegeltjes toont je camera's als zwevende vensters.</string>
</dict></plist>
EOF
codesign --force -s - Spiegeltjes.app
echo "klaar: $(pwd)/Spiegeltjes.app"
