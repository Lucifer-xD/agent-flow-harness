#!/usr/bin/env bash
# Installs AFH's terminal app on macOS or Linux, for this user only (no sudo):
#
#   curl -fsSL https://agentflowharness.com/install.sh | bash
#
# It downloads the newest release from GitHub, checks its SHA-256, unpacks it to ~/.afh/cli and puts
# `afh` on your PATH. `afh uninstall` undoes this; your threads, settings and keys stay.
set -euo pipefail

temp="" staging="" worker="" animate=""  # the exit trap runs after main has returned
cleanup() {
  if [ -n "$worker" ]; then kill "$worker" 2>/dev/null || true; fi
  if [ -n "$temp" ]; then rm -rf "$temp"; fi
  if [ -n "$staging" ]; then rm -rf "$staging"; fi
  if [ -n "$animate" ]; then printf '\033[0m\033[?25h'; fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# The logo, as on the app's start screen, one cell per array item. 256 colors, because macOS
# Terminal has no true color: amber, orange, pink.
rows=(' #####7 #######7##7  ##7' '##r==##7##r====J##|  ##|' '#######|#####7  #######|' '##r==##|##r==J  ##r==##|' '##|  ##|##|     ##|  ##|' 'L=J  L=JL=J     L=J  L=J')
colors=(214 214 214 214 208 208 208 208 209 209 203 203 203 204 204 204 205 205 198 198 199 199 199 199)
width=24
cells=()
load_logo() {
  local row c ch
  for row in "${rows[@]}"; do
    for ((c = 0; c < width; c++)); do
      ch="${row:c:1}"
      case "$ch" in
        '#') ch='█' ;;
        r) ch='╔' ;;
        7) ch='╗' ;;
        L) ch='╚' ;;
        J) ch='╝' ;;
        =) ch='═' ;;
        '|') ch='║' ;;
      esac
      cells[${#cells[@]}]="$ch"
    done
  done
}

# fill is 0 to 1000, tick moves the shine along
frame() {
  local fill="$1" tick="$2" status="$3" first="$4"
  local edge=$((fill * width / 1000)) sweep=$((tick % 44 - 10)) text="" r c ink ch far
  if [ -z "$first" ]; then text=$'\033[7A\r'; fi
  for ((r = 0; r < 6; r++)); do
    text+="  "
    for ((c = 0; c < width; c++)); do
      ch="${cells[r * width + c]}"
      if [ "$ch" != " " ]; then
        far=$((c - sweep))
        if [ "$c" -ge "$edge" ]; then ink=244
        elif [ "$far" -ge -1 ] && [ "$far" -le 1 ]; then ink=223
        else ink="${colors[c]}"
        fi
        text+=$'\033[38;5;'"${ink}m"
      fi
      text+="$ch"
    done
    text+=$'\033[K\n'
  done
  text+=$'\033[0m\033[K\n  '"$status"$'\033[K'
  printf '%s' "$text"
}

# Everything that takes time. It runs beside the animation and reports through files in $temp.
work() {
  local base="$1" home="$2" asset="$3" versions="$4"
  fail() { printf '%s' "$1" > "$temp/failed"; exit 1; }

  curl -fsSIL "$base/$asset" 2>/dev/null | tr -d '\r' | awk 'tolower($1) == "content-length:" { n = $2 } END { print n + 0 }' > "$temp/total" || true
  curl -fsSL "$base/afh-checksums.txt" -o "$temp/afh-checksums.txt" || fail "Couldn't reach the download. Check your connection."
  curl -fsSL "$base/$asset" -o "$temp/$asset" || fail "The download stopped. Check your connection."
  : > "$temp/unpack"

  local want got
  want="$(grep -F "$asset" "$temp/afh-checksums.txt" | head -n 1 | cut -d' ' -f1)"
  if [ -z "$want" ]; then fail "No checksum for $asset."; fi
  if command -v sha256sum >/dev/null 2>&1; then got="$(sha256sum "$temp/$asset" | cut -d' ' -f1)"; else got="$(shasum -a 256 "$temp/$asset" | cut -d' ' -f1)"; fi
  if [ "$want" != "$got" ]; then fail "The download didn't match its checksum, so nothing was installed."; fi

  mkdir -p "$staging"
  tar -xzf "$temp/$asset" -C "$staging"
  local version
  version="$("$staging/afh/afh" --version | sed 's/^afh //')" || fail "The downloaded program didn't start."
  if [ -z "$version" ]; then fail "The downloaded program didn't start."; fi

  rm -rf "${versions:?}/$version"
  mv "$staging" "$versions/$version"

  mkdir -p "$home/bin"
  printf '#!/bin/sh\nexec "%s" "$@"\n' "$versions/$version/afh/afh" > "$home/bin/afh"
  chmod 755 "$home/bin/afh"

  local line="export PATH=\"$home/bin:\$PATH\"  # added by AFH"
  case ":$PATH:" in
    *":$home/bin:"*) ;;
    *)
      for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
        if [ -f "$rc" ] || [ "$rc" = "$HOME/.profile" ]; then
          grep -qF ".afh/bin" "$rc" 2>/dev/null || printf '\n%s\n' "$line" >> "$rc"
          : > "$temp/added"
        fi
      done
      ;;
  esac
  printf '%s' "$version" > "$temp/version"
}

main() {
  local base="${AFH_DOWNLOAD_BASE:-https://github.com/Lucifer-xD/agent-flow-harness/releases/latest/download}"
  local home="${AFH_HOME:-$HOME/.afh}"
  local os arch asset
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$os-$arch" in
    Darwin-arm64) asset="afh-macos-arm64.tar.gz" ;;
    Darwin-x86_64) asset="afh-macos-x64.tar.gz" ;;
    Linux-x86_64) asset="afh-linux-x64.tar.gz" ;;
    *) echo "There's no AFH build for $os on $arch yet." >&2; exit 1 ;;
  esac

  local versions="$home/cli/versions"
  temp="$(mktemp -d)"
  staging="$versions/.new-$$"
  mkdir -p "$versions"

  if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
    case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
      *[Uu][Tt][Ff]-8* | *[Uu][Tt][Ff]8*) animate="yes" ;;
    esac
  fi

  # stdin is this script when it arrives through a pipe, so nothing here may read it
  (work "$base" "$home" "$asset" "$versions") </dev/null >/dev/null 2>"$temp/errors" &
  worker=$!

  local shown=0 tick=0 first="yes" total got goal
  if [ -n "$animate" ]; then
    load_logo
    printf '\033[?25l\n'
    while kill -0 "$worker" 2>/dev/null; do
      if [ -f "$temp/unpack" ]; then
        shown=$((shown + (970 - shown) / 40))
      else
        total="$(cat "$temp/total" 2>/dev/null || true)"
        goal=0
        if [ -f "$temp/$asset" ] && [ "${total:-0}" -gt 0 ]; then
          got="$(wc -c < "$temp/$asset")"
          goal=$((got * 800 / total))
        fi
        shown=$((shown + (goal - shown) / 4))
      fi
      frame "$shown" "$tick" "Installing AFH  $((shown / 10))%" "$first"
      first=""
      tick=$((tick + 1))
      sleep 0.08
    done
  else
    echo "Installing AFH..."
  fi

  local done="yes"
  wait "$worker" || done=""
  worker=""

  if [ -z "$done" ] || [ ! -f "$temp/version" ]; then
    local why="Something went wrong."
    if [ -f "$temp/failed" ]; then why="$(cat "$temp/failed")"
    elif [ -s "$temp/errors" ]; then why="$(tail -n 1 "$temp/errors")"
    fi
    if [ -n "$animate" ]; then
      frame "$shown" "$tick" $'\033[31m'"AFH wasn't installed: $why"$'\033[0m' "$first"
      printf '\n'
    else
      echo "AFH wasn't installed: $why" >&2
    fi
    exit 1
  fi

  local version next
  version="$(cat "$temp/version")"
  next="Go to a project folder and type: afh"
  if [ -f "$temp/added" ]; then next="Open a new terminal, go to a project folder and type: afh"; fi
  if [ -n "$animate" ]; then
    frame 1000 44 $'\033[32m'"AFH $version is ready."$'\033[0m' "$first"
    printf '\n\n  %s\n\n' "$next"
  else
    echo "AFH $version is installed."
    echo "$next"
  fi
}

main "$@"
