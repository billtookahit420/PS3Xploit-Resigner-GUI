#!/bin/bash
# Build PS3XploitResignerGUI-x86_64.AppImage from src/.
# Bundles the system Python 3.12 + PySide6 (from the family
# build venv), following the family AppImage pattern.
# appimagetool is a build tool only -- the extracted copy
# from the sibling XBOX Video Partition Remover build is
# reused (it is not shipped).
set -euo pipefail
PROJ="$(cd "$(dirname "$0")" && pwd)"
BUILD="$PROJ/proof/appimage-build"
APPDIR="$BUILD/PS3XploitResignerGUI.AppDir"
OUT="$PROJ/PS3XploitResignerGUI-x86_64.AppImage"
TOOLSDIR="$HOME/workspace/xbox-video-partition-remover/proof/appimage-build/tools"
VENV_SP="$HOME/workspace/recomp-tools-gui/.venv/lib/python3.12/site-packages"

mkdir -p "$BUILD"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/python3.12/site-packages" \
         "$APPDIR/usr/share/ps3resigner"

# Python binary + stdlib (no test suite, no pyc caches)
cp -L /usr/bin/python3.12 "$APPDIR/usr/bin/python3.12"
chmod +x "$APPDIR/usr/bin/python3.12"
cp -r /usr/lib/python3.12 "$APPDIR/usr/lib/"
rm -rf "$APPDIR/usr/lib/python3.12/test" \
       "$APPDIR/usr/lib/python3.12/idlelib" \
       "$APPDIR/usr/lib/python3.12/turtledemo"
# the copied stdlib tree has its own site-packages placeholder;
# replace it with the real target dir
rm -rf "$APPDIR/usr/lib/python3.12/site-packages"
mkdir -p "$APPDIR/usr/lib/python3.12/site-packages"

# PySide6 + shiboken6 from the build venv
cp -r "$VENV_SP/PySide6" "$VENV_SP/shiboken6" \
      "$APPDIR/usr/lib/python3.12/site-packages/"
cp -r "$VENV_SP"/PySide6-*.dist-info "$VENV_SP"/shiboken6-*.dist-info \
      "$APPDIR/usr/lib/python3.12/site-packages/" 2>/dev/null || true

# Prune the Qt modules this app never touches (it imports
# QtCore/QtGui/QtWidgets only): WebEngine, Quick/QML, 3D,
# Charts, Multimedia and friends are most of the wheel's
# weight. The packaged smoke (offscreen AND Xvfb/xcb)
# verifies the pruned tree still runs the whole flow.
PS6="$APPDIR/usr/lib/python3.12/site-packages/PySide6"
rm -rf "$PS6/Qt/translations" "$PS6/Qt/qml" "$PS6/Qt/resources"
for pat in WebEngine 3D Charts DataVisualization Graphs \
           Multimedia Pdf TextToSpeech SpatialAudio WebView \
           Quick Qml RemoteObjects Scxml Sensors SerialBus \
           SerialPort Bluetooth Nfc Positioning Sql Test \
           Help Designer UiTools PrintSupport Wayland; do
    rm -f "$PS6"/Qt${pat}*.abi3.so "$PS6"/Qt${pat}*.pyi
    rm -f "$PS6"/Qt/lib/libQt6${pat}*.so*
done
rm -rf "$PS6/Qt/plugins/wayland"* "$PS6/Qt/plugins/sqldrivers" \
       "$PS6/Qt/plugins/qmltooling" \
       "$PS6/Qt/plugins/platforminputcontexts"
find "$APPDIR/usr/lib/python3.12" -name __pycache__ -type d \
    -exec rm -rf {} + 2>/dev/null || true

# Shared libraries: ldd closure of python + every bundled
# PySide6 .so, minus the core glibc set every host provides.
EXCLUDE='^(libc|libm|libdl|libpthread|librt|libresolv|libutil|ld-linux)'
{
    ldd /usr/bin/python3.12
    find "$APPDIR/usr/lib/python3.12/site-packages/PySide6" \
         "$APPDIR/usr/lib/python3.12/site-packages/shiboken6" \
         -name "*.so*" -type f -exec ldd {} + 2>/dev/null
} | grep -oE '/[^ ]+\.so[^ ]*' | sort -u | while read -r lib; do
    base="$(basename "$lib")"
    case "$lib" in
        */site-packages/*) continue ;;  # already bundled in place
    esac
    if echo "$base" | grep -qE "$EXCLUDE"; then
        continue
    fi
    cp -L "$lib" "$APPDIR/usr/lib/$base"
done

# The app itself
cp -r "$PROJ/src/PS3XploitResignerGUI/app" \
      "$APPDIR/usr/share/ps3resigner/app"
cp "$PROJ/src/PS3XploitResignerGUI/README.md" \
   "$APPDIR/usr/share/ps3resigner/"
# The carried engine payload (bare-machine rule): the
# pinned V3.0.0 source tarball + the ready-built, fully
# static rifgen. The app hash-verifies both at first run
# and just unpacks them -- no download, no build on the
# user's machine.
cp -r "$PROJ/src/PS3XploitResignerGUI/engine-payload" \
      "$APPDIR/usr/share/ps3resigner/engine-payload"
find "$APPDIR/usr/share/ps3resigner" -name __pycache__ -type d \
    -exec rm -rf {} + 2>/dev/null || true

# Icon: a gold key over a dark rounded square, drawn
# pixel-wise -- no image tooling needed.
python3 - "$APPDIR/ps3resigner.png" <<'PYEOF'
import math, struct, sys, zlib

S = 256
rows = []
for y in range(S):
    row = bytearray()
    for x in range(S):
        # rounded-square background
        cx, cy = min(x, S - 1 - x), min(y, S - 1 - y)
        inside = not (cx < 24 and cy < 24
                      and math.hypot(24 - cx, 24 - cy) > 24)
        px = (38, 42, 50, 255) if inside else (0, 0, 0, 0)
        if inside:
            # key: bow (ring) at upper-left, shaft diagonal
            # down-right, two teeth near the end.
            d_bow = math.hypot(x - 92, y - 92)
            on_bow = 26 <= d_bow <= 44
            # shaft: distance to the line y=x from bow edge
            # to (196,196)
            t = (x + y) / 2.0
            perp = abs(x - y) / math.sqrt(2)
            on_shaft = 120 <= t <= 205 and perp <= 11
            # teeth: short perpendicular bars near the tip
            tooth1 = 178 <= t <= 190 and 11 < (y - x) / math.sqrt(2) <= 34
            tooth2 = 196 <= t <= 208 and 11 < (y - x) / math.sqrt(2) <= 30
            if on_bow or on_shaft or tooth1 or tooth2:
                px = (240, 190, 60, 255)   # gold key
        row += bytes(px)
    rows.append(b"\x00" + bytes(row))
raw = b"".join(rows)

def chunk(tag, data):
    c = struct.pack(">I", len(data)) + tag + data
    return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

png = (b"\x89PNG\r\n\x1a\n"
       + chunk(b"IHDR", struct.pack(">IIBBBBB", S, S, 8, 6, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(raw, 9))
       + chunk(b"IEND", b""))
open(sys.argv[1], "wb").write(png)
print("icon written")
PYEOF

cat > "$APPDIR/ps3xploit-resigner-gui.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=PS3Xploit Resigner GUI
Comment=Add games to your PS3 act.dat (RAP -> RIF installer)
Exec=ps3xploit-resigner-gui
Icon=ps3resigner
Categories=Utility;
Terminal=false
EOF

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PYTHONHOME="$HERE/usr"
export PYTHONPATH="$HERE/usr/lib/python3.12/site-packages:$HERE/usr/share/ps3resigner${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if [ -z "$PS3RESIGN_GUI_DATA_DIR" ]; then
    PS3RESIGN_GUI_DATA_DIR="$HOME/.local/share/ps3xploit-resigner-gui"
    export PS3RESIGN_GUI_DATA_DIR
fi
# The bundled Python is the host distro's own build; point
# TLS at the host CA bundle explicitly when one exists.
if [ -z "$SSL_CERT_FILE" ] && [ -f /etc/ssl/certs/ca-certificates.crt ]; then
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
    export SSL_CERT_FILE
fi
exec "$HERE/usr/bin/python3.12" "$HERE/usr/share/ps3resigner/app/main.py" "$@"
EOF
chmod +x "$APPDIR/AppRun"

rm -f "$OUT"
ARCH=x86_64 "$TOOLSDIR/appimagetool-extracted/AppRun" \
    "$APPDIR" "$OUT" 2>&1 | tail -3
ls -la "$OUT"
sha256sum "$OUT"
