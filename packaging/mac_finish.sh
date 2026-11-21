#!/bin/bash
# Ritocchi a AllDownload.app dopo PyInstaller (usato sia da build_mac.sh sia da GitHub Actions).
# Uso: packaging/mac_finish.sh dist/AllDownload.app 0.2.0
set -e
APPDIR="$1"; VER="$2"
PLIST="$APPDIR/Contents/Info.plist"
PB=/usr/libexec/PlistBuddy
$PB -c "Set :CFBundleShortVersionString $VER" "$PLIST" 2>/dev/null || $PB -c "Add :CFBundleShortVersionString string $VER" "$PLIST"
$PB -c "Set :CFBundleVersion $VER" "$PLIST" 2>/dev/null || $PB -c "Add :CFBundleVersion string $VER" "$PLIST"
$PB -c "Add :NSHighResolutionCapable bool true" "$PLIST" 2>/dev/null || true
$PB -c "Add :LSApplicationCategoryType string public.app-category.utilities" "$PLIST" 2>/dev/null || true
# link alldownload:// (segnalibro ed estensione del browser)
$PB -c "Delete :CFBundleURLTypes" "$PLIST" 2>/dev/null || true
$PB -c "Add :CFBundleURLTypes array" \
    -c "Add :CFBundleURLTypes:0 dict" \
    -c "Add :CFBundleURLTypes:0:CFBundleURLName string com.alldownload.app" \
    -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes array" \
    -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string alldownload" "$PLIST"
# passkey/chiavi di sicurezza nei login del browser interno
$PB -c "Add :NSBluetoothAlwaysUsageDescription string 'Per usare passkey e chiavi di sicurezza nei login del browser interno.'" "$PLIST" 2>/dev/null || true
xattr -cr "$APPDIR" 2>/dev/null || true
codesign --force --deep --sign - "$APPDIR"
