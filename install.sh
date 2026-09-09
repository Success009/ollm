#!/usr/bin/env bash
# OLLM Universal Fast Installer and Updater for Linux
set -e

REPO_URL="https://github.com/Success009/ollm.git"
INSTALL_DIR="${OLLM_INSTALL_DIR:-$HOME/.local/share/ollm}"
BIN_DIR="$HOME/.local/bin"

# ANSI Colors
BOLD="\033[1m"
GREEN="\033[38;5;82m"
CYAN="\033[38;5;39m"
DIM="\033[38;5;242m"
YELLOW="\033[38;5;214m"
RESET="\033[0m"

echo -e "\n${BOLD}${CYAN}=== OLLM (Offline Large Language Model) Installer ===${RESET}\n"

# 1. Check if git and python3 exist
command -v git >/dev/null 2>&1 || MISSING_GIT=1
command -v python3 >/dev/null 2>&1 || MISSING_PY=1

# Test if python venv actually works without errors
VENV_TEST=0
if [ -z "$MISSING_PY" ]; then
    TMP_VENV="/tmp/.ollm_test_venv_$$"
    if python3 -m venv "$TMP_VENV" >/dev/null 2>&1; then
        rm -rf "$TMP_VENV"
    else
        VENV_TEST=1
    fi
fi

# 2. If system packages missing, install via package manager
if [ "$MISSING_GIT" = "1" ] || [ "$MISSING_PY" = "1" ] || [ "$VENV_TEST" = "1" ]; then
    echo -e "${YELLOW}[*] Missing required system packages. Installing...${RESET}"
    
    # Configure sudo execution safely with TTY
    RUN_CMD=""
    if [ "$EUID" -ne 0 ]; then
        if command -v sudo >/dev/null 2>&1; then
            RUN_CMD="sudo"
        fi
    fi

    # Read from /dev/tty if available so sudo password prompt works even inside pipes
    if [ -n "$RUN_CMD" ] && [ -e /dev/tty ]; then
        SUDO_EXEC="$RUN_CMD </dev/tty"
    else
        SUDO_EXEC="$RUN_CMD"
    fi

    if command -v apt-get >/dev/null 2>&1; then
        echo -e "${DIM}Running apt update & install...${RESET}"
        $SUDO_EXEC apt-get update -y
        $SUDO_EXEC apt-get install -y git curl python3 python3-pip python3-venv mpv ffmpeg
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO_EXEC dnf install -y git curl python3 python3-pip mpv ffmpeg
    elif command -v pacman >/dev/null 2>&1; then
        $SUDO_EXEC pacman -Sy --noconfirm git curl python python-pip mpv ffmpeg
    elif command -v apk >/dev/null 2>&1; then
        $SUDO_EXEC apk add --no-cache git curl python3 py3-pip mpv ffmpeg
    elif command -v zypper >/dev/null 2>&1; then
        $SUDO_EXEC zypper in -y git curl python3 python3-pip mpv ffmpeg
    fi
fi

# 3. Verify Python 3.10+
if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${YELLOW}Error: python3 could not be found. Please install Python 3.10+ manually.${RESET}" >&2
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo -e "${YELLOW}Error: Python 3.10 or newer is required (found $PY_VER).${RESET}" >&2
    exit 1
fi

# 4. Clone or Update OLLM
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "${CYAN}[*] Updating existing OLLM installation at $INSTALL_DIR...${RESET}"
    cd "$INSTALL_DIR"
    git fetch origin main --quiet || true
    git reset --hard origin/main --quiet || git pull --ff-only || true
else
    echo -e "${CYAN}[*] Downloading OLLM into $INSTALL_DIR...${RESET}"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# 5. Virtual Environment Setup
VENV_DIR="$INSTALL_DIR/.venv"
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo -e "${CYAN}[*] Creating isolated Python virtual environment...${RESET}"
    python3 -m venv "$VENV_DIR"
fi

echo -e "${CYAN}[*] Installing dependencies (this may take a minute on first install)...${RESET}"
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR" --quiet

# 6. Install CLI Launcher Scripts
mkdir -p "$BIN_DIR"

cat << 'EOF' > "$BIN_DIR/ollm"
#!/usr/bin/env bash
INSTALL_DIR="${OLLM_INSTALL_DIR:-$HOME/.local/share/ollm}"
exec "$INSTALL_DIR/.venv/bin/python3" -m ollm.cli "$@"
EOF
chmod +x "$BIN_DIR/ollm"

cat << 'EOF' > "$BIN_DIR/lm"
#!/usr/bin/env bash
INSTALL_DIR="${OLLM_INSTALL_DIR:-$HOME/.local/share/ollm}"
exec "$INSTALL_DIR/.venv/bin/python3" -m ollm.cli "$@"
EOF
chmod +x "$BIN_DIR/lm"

# Attempt system-wide link if accessible
if [ -w "/usr/local/bin" ]; then
    ln -sf "$BIN_DIR/ollm" /usr/local/bin/ollm 2>/dev/null || true
    ln -sf "$BIN_DIR/lm" /usr/local/bin/lm 2>/dev/null || true
fi

# Ensure ~/.local/bin is in PATH
for cfg in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
    if [ -f "$cfg" ] && ! grep -q '\.local/bin' "$cfg"; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$cfg"
    fi
done

export PATH="$BIN_DIR:$PATH"

echo -e "\n${BOLD}${GREEN}[✓] OLLM successfully installed & configured!${RESET}"
echo -e "${DIM}Run '${BOLD}lm${RESET}${DIM}' or '${BOLD}ollm${RESET}${DIM}' in your terminal to begin.${RESET}\n"
