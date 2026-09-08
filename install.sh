#!/usr/bin/env bash
# OLLM Universal One-Line Installer and Updater for Linux
set -e

REPO_URL="https://github.com/Success009/ollm.git"
INSTALL_DIR="${OLLM_INSTALL_DIR:-$HOME/.local/share/ollm}"
BIN_DIR="$HOME/.local/bin"

# ANSI Colors
BOLD="\033[1m"
GREEN="\033[38;5;82m"
CYAN="\033[38;5;39m"
DIM="\033[38;5;242m"
RESET="\033[0m"

echo -e "\n${BOLD}${CYAN}=== OLLM (Offline Large Language Model) Installer ===${RESET}\n"

# 1. Package Manager Dependency Detection & Installation
install_system_deps() {
    echo -e "${DIM}[*] Checking system dependencies...${RESET}"
    local missing_pkgs=()

    command -v curl >/dev/null 2>&1 || missing_pkgs+=("curl")
    command -v git >/dev/null 2>&1 || missing_pkgs+=("git")
    command -v python3 >/dev/null 2>&1 || missing_pkgs+=("python3")

    # Check python venv capability
    if command -v python3 >/dev/null 2>&1; then
        python3 -c "import venv" >/dev/null 2>&1 || missing_pkgs+=("python3-venv")
    fi

    if [ ${#missing_pkgs[@]} -eq 0 ]; then
        echo -e "${GREEN}[✓] Required system utilities already present.${RESET}"
        return 0
    fi

    echo -e "${CYAN}[*] Installing missing dependencies: ${missing_pkgs[*]}...${RESET}"
    SUDO=""
    if [ "$EUID" -ne 0 ]; then
        if command -v sudo >/dev/null 2>&1; then
            SUDO="sudo"
        else
            echo -e "${DIM}[!] sudo not found; attempting direct install...${RESET}"
        fi
    fi

    if command -v apt-get >/dev/null 2>&1; then
        $SUDO apt-get update -qq
        $SUDO apt-get install -y -qq git curl python3 python3-pip python3-venv build-essential
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO dnf install -y -q git curl python3 python3-pip gcc gcc-c++ make
    elif command -v pacman >/dev/null 2>&1; then
        $SUDO pacman -Sy --noconfirm git curl python python-pip base-devel
    elif command -v apk >/dev/null 2>&1; then
        $SUDO apk add --no-cache git curl python3 py3-pip build-base
    elif command -v zypper >/dev/null 2>&1; then
        $SUDO zypper in -y git curl python3 python3-pip gcc gcc-c++ make
    else
        echo -e "${DIM}[!] Unknown package manager. Please ensure git, curl, and python3-venv are installed.${RESET}"
    fi
}

install_system_deps

# 2. Check Python Version (>= 3.10)
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required." >&2
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "Error: Python 3.10 or newer is required. Found Python $PY_VER." >&2
    exit 1
fi

# 3. Clone or Update Repository
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "${CYAN}[*] Existing installation found at $INSTALL_DIR. Updating...${RESET}"
    cd "$INSTALL_DIR"
    git fetch origin main --quiet || true
    git reset --hard origin/main --quiet || git pull --ff-only --quiet || true
else
    echo -e "${CYAN}[*] Cloning OLLM repository to $INSTALL_DIR...${RESET}"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone "$REPO_URL" "$INSTALL_DIR" --quiet
    cd "$INSTALL_DIR"
fi

# 4. Setup Python Virtual Environment
VENV_DIR="$INSTALL_DIR/.venv"
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo -e "${DIM}[*] Creating virtual environment...${RESET}"
    python3 -m venv "$VENV_DIR"
fi

echo -e "${DIM}[*] Installing/updating Python dependencies...${RESET}"
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR" --quiet

# 5. Create Binary Wrappers in ~/.local/bin and /usr/local/bin
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

# Attempt system-wide symlinks if /usr/local/bin is writable or passwordless sudo available
if [ -w "/usr/local/bin" ]; then
    ln -sf "$BIN_DIR/ollm" /usr/local/bin/ollm 2>/dev/null || true
    ln -sf "$BIN_DIR/lm" /usr/local/bin/lm 2>/dev/null || true
elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo ln -sf "$BIN_DIR/ollm" /usr/local/bin/ollm 2>/dev/null || true
    sudo ln -sf "$BIN_DIR/lm" /usr/local/bin/lm 2>/dev/null || true
fi

# 6. Ensure PATH Contains ~/.local/bin
SHELL_CONFIGS=("$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile")
for cfg in "${SHELL_CONFIGS[@]}"; do
    if [ -f "$cfg" ] && ! grep -q '\.local/bin' "$cfg"; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$cfg"
    fi
done

export PATH="$BIN_DIR:$PATH"

echo -e "\n${BOLD}${GREEN}[✓] OLLM is ready to use!${RESET}"
echo -e "${DIM}Run '${BOLD}lm${RESET}${DIM}' or '${BOLD}ollm${RESET}${DIM}' in your terminal to start.${RESET}\n"
