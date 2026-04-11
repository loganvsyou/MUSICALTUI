#!/usr/bin/env bash
set -e

BINARY="musicaltui"
INSTALL_DIR="/usr/local/bin"

echo "── musicaltui installer ──────────────────────"

# Check binary exists next to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_PATH="$HOME/dist/$BINARY"

if [ ! -f "$BIN_PATH" ]; then
  echo "Error: binary not found at $BIN_PATH"
  echo "Build it first with:"
  echo "  pyinstaller --onefile --name musicaltui --collect-all textual --collect-all spotipy media_tui.py"
  exit 1
fi

# Check for mpv
if ! command -v mpv &>/dev/null; then
  echo ""
  echo "Warning: mpv is not installed (required for local file playback)"
  echo "Install it with: brew install mpv"
  echo ""
fi

# Install
echo "Installing $BINARY to $INSTALL_DIR ..."
sudo cp "$BIN_PATH" "$INSTALL_DIR/$BINARY"
sudo chmod +x "$INSTALL_DIR/$BINARY"

echo ""
echo "Done! Run it with:"
echo "  musicaltui ~/Music"
echo "─────────────────────────────────────────────"
