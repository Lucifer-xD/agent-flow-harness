#!/usr/bin/env bash
# Installs AFH's terminal app on macOS or Linux, for this user only (no sudo):
#
#   curl -fsSL https://agentflowharness.com/install.sh | bash
#
# It downloads the newest release from GitHub, checks its SHA-256, unpacks it to ~/.afh/cli and puts
# `afh` on your PATH. `afh uninstall` undoes this; your threads, settings and keys stay.
set -euo pipefail
temp="" staging=""  # the exit trap runs after the function has returned

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

  local versions
  temp="$(mktemp -d)"
  versions="$home/cli/versions"
  staging="$versions/.new-$$"
  trap 'rm -rf "$temp" "$staging"' EXIT
  mkdir -p "$versions"

  echo "Downloading AFH..."
  curl -fsSL "$base/$asset" -o "$temp/$asset"
  curl -fsSL "$base/afh-checksums.txt" -o "$temp/afh-checksums.txt"

  local want got
  want="$(grep -F "$asset" "$temp/afh-checksums.txt" | head -n 1 | cut -d' ' -f1)"
  if [ -z "$want" ]; then echo "No checksum for $asset." >&2; exit 1; fi
  if command -v sha256sum >/dev/null 2>&1; then got="$(sha256sum "$temp/$asset" | cut -d' ' -f1)"; else got="$(shasum -a 256 "$temp/$asset" | cut -d' ' -f1)"; fi
  if [ "$want" != "$got" ]; then echo "The download didn't match its checksum, so nothing was installed." >&2; exit 1; fi

  echo "Unpacking..."
  mkdir -p "$staging"
  tar -xzf "$temp/$asset" -C "$staging"
  local version
  version="$("$staging/afh/afh" --version | sed 's/^afh //')"
  if [ -z "$version" ]; then echo "The downloaded program didn't start." >&2; exit 1; fi

  rm -rf "${versions:?}/$version"
  mv "$staging" "$versions/$version"

  mkdir -p "$home/bin"
  printf '#!/bin/sh\nexec "%s" "$@"\n' "$versions/$version/afh/afh" > "$home/bin/afh"
  chmod 755 "$home/bin/afh"

  local line="export PATH=\"$home/bin:\$PATH\"  # added by AFH"
  local added=""
  case ":$PATH:" in
    *":$home/bin:"*) ;;
    *)
      for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
        if [ -f "$rc" ] || [ "$rc" = "$HOME/.profile" ]; then
          grep -qF ".afh/bin" "$rc" 2>/dev/null || printf '\n%s\n' "$line" >> "$rc"
          added="yes"
        fi
      done
      ;;
  esac

  echo
  echo "AFH $version is installed."
  if [ -n "$added" ]; then
    echo "Open a new terminal, go to a project folder and type: afh"
  else
    echo "Go to a project folder and type: afh"
  fi
}

main "$@"
