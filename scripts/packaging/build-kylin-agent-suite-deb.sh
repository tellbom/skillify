#!/bin/sh
set -eu

VERSION="${VERSION:-0.1.0}"
SOURCE_ROOT="${SOURCE_ROOT:-$(pwd)}"
SOURCE_HOME="${SOURCE_HOME:-$HOME}"
OUT_DIR="${OUT_DIR:-$SOURCE_ROOT/dist}"
PACKAGE="skillify-agent-suite"
ROOT="$OUT_DIR/${PACKAGE}_${VERSION}_amd64"
OPT="$ROOT/opt/skillify-agent-suite"

rm -rf "$ROOT"
mkdir -p \
  "$ROOT/DEBIAN" \
  "$ROOT/usr/bin" \
  "$ROOT/usr/share/applications" \
  "$ROOT/usr/share/icons/hicolor/256x256/apps" \
  "$OPT/bin" \
  "$OPT/app" \
  "$OPT/python/site-packages" \
  "$OPT/agent-host"

# CC Switch: use the Kylin-compatible runtime already accepted on the endpoint.
mkdir -p "$OPT"
cp -a "$SOURCE_HOME/.local/opt/cc-switch/v3.19.2-kylin" "$OPT/cc-switch"
rm -f \
  "$OPT/cc-switch"/*.deb \
  "$OPT/cc-switch"/*.AppImage \
  "$OPT/cc-switch"/*.log \
  "$OPT/cc-switch"/*.pid \
  "$OPT/cc-switch"/*-screen.png \
  "$OPT/cc-switch"/ccswitch-import.png

# Claude Code and OpenCode are self-contained Linux x86_64 executables.
mkdir -p "$OPT/bin"
cp -a "$SOURCE_HOME/.local/bin/claude" "$OPT/bin/claude"
cp -a "$SOURCE_HOME/.local/lib/node_modules/opencode-ai/bin/opencode.exe" "$OPT/bin/opencode"

# The official Agent Host requires Node >=20. Only the runtime executable is needed.
cp -a "$SOURCE_HOME/node24/bin/node" "$OPT/bin/node"

# Bundle the relocatable Python 3.11 runtime used by the accepted endpoint.
PYTHON_REAL="$(readlink -f "$SOURCE_ROOT/.venv/bin/python3")"
PYTHON_ROOT="$(dirname "$(dirname "$PYTHON_REAL")")"
mkdir -p "$OPT/python/site-packages"
cp -a "$PYTHON_ROOT/." "$OPT/python/"
cp -a "$SOURCE_ROOT/.venv/lib/python3.11/site-packages/." "$OPT/python/site-packages/"
rm -f \
  "$OPT/python/site-packages/_editable_impl_skillify.pth" \
  "$OPT/python/site-packages/a1_coverage.pth"
rm -rf \
  "$OPT/python/site-packages/skillify-"*.dist-info \
  "$OPT/python/site-packages/coverage" \
  "$OPT/python/site-packages/coverage-"*.dist-info \
  "$OPT/python/site-packages/pytest" \
  "$OPT/python/site-packages/_pytest" \
  "$OPT/python/site-packages/pytest-"*.dist-info

# Skillify runtime source and bundled workflow/app definitions.
mkdir -p "$OPT/app"
cp -a "$SOURCE_ROOT/src" "$OPT/app/src"
cp -a "$SOURCE_ROOT/workflows" "$OPT/app/workflows"
cp -a "$SOURCE_ROOT/apps" "$OPT/app/apps"
cp -a "$SOURCE_ROOT/pyproject.toml" "$OPT/app/pyproject.toml"

# Agent Host compiled output and production dependencies.
mkdir -p "$OPT/agent-host"
cp -a "$SOURCE_ROOT/agent-host/dist" "$OPT/agent-host/dist"
cp -a "$SOURCE_ROOT/agent-host/package.json" "$OPT/agent-host/package.json"
cp -a "$SOURCE_ROOT/agent-host/package-lock.json" "$OPT/agent-host/package-lock.json"
cp -a "$SOURCE_ROOT/agent-host/node_modules" "$OPT/agent-host/node_modules"
rm -rf \
  "$OPT/agent-host/node_modules/typescript" \
  "$OPT/agent-host/node_modules/@types" \
  "$OPT/agent-host/node_modules/@anthropic-ai/claude-agent-sdk-darwin-"* \
  "$OPT/agent-host/node_modules/@anthropic-ai/claude-agent-sdk-win32-"* \
  "$OPT/agent-host/node_modules/@anthropic-ai/claude-agent-sdk-linux-arm64"* \
  "$OPT/agent-host/node_modules/@anthropic-ai/claude-agent-sdk-linux-x64-musl"

cat >"$OPT/bin/cc-switch" <<'EOF'
#!/bin/sh
root=/opt/skillify-agent-suite/cc-switch
app="$root/squashfs-root"
loader="$root/glibc-2.35/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"
libs="$root/glibc-2.35/lib/x86_64-linux-gnu:$root/cxx-12/usr/lib/x86_64-linux-gnu:$root/freetype-2.11/usr/lib/x86_64-linux-gnu:$root/gbm-23/usr/lib/x86_64-linux-gnu:$root/drm-2.4.113/usr/lib/x86_64-linux-gnu:$app/usr/lib"
export APPDIR="$app" GTK_DATA_PREFIX="$app" GTK_THEME="Adwaita:light" GDK_BACKEND=x11
export XDG_DATA_DIRS="$app/usr/share:/usr/share" GSETTINGS_SCHEMA_DIR="$app/usr/share/glib-2.0/schemas" GTK_EXE_PREFIX="$app/usr"
export GTK_PATH="$app/usr/lib/x86_64-linux-gnu/gtk-3.0:/usr/lib/x86_64-linux-gnu/gtk-3.0" GTK_IM_MODULE_FILE="$app/usr/lib/x86_64-linux-gnu/gtk-3.0/3.0.0/immodules.cache"
export GDK_PIXBUF_MODULE_FILE="$app/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders.cache" GIO_EXTRA_MODULES="$app/usr/lib/x86_64-linux-gnu/gio/modules"
cd "$app/usr"
exec "$loader" --library-path "$libs" "$app/usr/bin/cc-switch" "$@"
EOF

cat >"$OPT/bin/skillctl" <<'EOF'
#!/bin/sh
root=/opt/skillify-agent-suite
export PATH="$root/bin:$PATH"
export PYTHONPATH="$root/app/src:$root/python/site-packages"
export SKILLIFY_AGENT_HOST_ENTRYPOINT="$root/agent-host/dist/index.js"
export SKILLIFY_AGENT_NODE_EXECUTABLE="$root/bin/node"
export SKILLIFY_OPENCODE_EXECUTABLE="$root/bin/opencode"
exec "$root/python/bin/python3.11" -m skillify.cli.main "$@"
EOF

for command in cc-switch claude opencode skillctl; do
  chmod 0755 "$OPT/bin/$command"
  ln -s "/opt/skillify-agent-suite/bin/$command" "$ROOT/usr/bin/$command"
done
chmod 0755 "$OPT/bin/node"

cp -a "$OPT/cc-switch/squashfs-root/CC Switch.png" \
  "$ROOT/usr/share/icons/hicolor/256x256/apps/cc-switch.png"

cat >"$ROOT/usr/share/applications/cc-switch.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=CC Switch
Name[zh_CN]=CC Switch 模型配置
Comment=Manage Claude Code provider configuration
Exec=/usr/bin/cc-switch
Icon=cc-switch
Terminal=false
Categories=Development;
MimeType=x-scheme-handler/ccswitch;
EOF

cat >"$ROOT/usr/share/applications/skillify-agent-terminal.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Skillify Agent Terminal
Name[zh_CN]=Skillify Agent 终端
Comment=Open a terminal with Skillify, Claude Code and OpenCode
Exec=x-terminal-emulator
Icon=utilities-terminal
Terminal=false
Categories=Development;
EOF

cat >"$ROOT/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: $VERSION
Section: devel
Priority: optional
Architecture: amd64
Installed-Size: $(du -sk "$OPT" | awk '{print $1}')
Maintainer: Skillify
Depends: libc6, libgtk-3-0, libx11-6
Description: Skillify endpoint agent suite for Kylin V10 SP1
 Bundles CC Switch 3.19.2, Claude Code 2.1.179, OpenCode 1.17.18,
 Skillify skillctl, Python 3.11, Node 24 and the official Agent Host.
EOF

cat >"$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
gtk-update-icon-cache -q /usr/share/icons/hicolor >/dev/null 2>&1 || true
exit 0
EOF
chmod 0755 "$ROOT/DEBIAN/postinst"

mkdir -p "$OUT_DIR"
dpkg-deb --build --root-owner-group -Zxz "$ROOT" \
  "$OUT_DIR/${PACKAGE}_${VERSION}_amd64.deb"
sha256sum "$OUT_DIR/${PACKAGE}_${VERSION}_amd64.deb" \
  >"$OUT_DIR/${PACKAGE}_${VERSION}_amd64.deb.sha256"

printf '%s\n' "$OUT_DIR/${PACKAGE}_${VERSION}_amd64.deb"
