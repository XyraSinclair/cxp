#!/usr/bin/env bash
# install.sh — install cxp (codexpool) and the codex shim.
# Idempotent, $HOME-relative, copies nothing secret.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
POOL="$HOME/.codexpool"

# 1. pick a PATH dir for the `cxp` CLI
BINDIR="$HOME/bin"
[ -d "$BINDIR" ] || BINDIR="/usr/local/bin"
mkdir -p "$BINDIR" "$POOL/bin"

# 2. install the two source files
install -m 0755 "$HERE/cxp"        "$BINDIR/cxp"
install -m 0755 "$HERE/cxp-bridge" "$POOL/cxp-bridge"
echo "installed: $BINDIR/cxp, $POOL/cxp-bridge"

# 3. the codex shim — routes model-running `codex` calls through the pool,
#    while auth/meta subcommands go straight to the real codex. Resolves the
#    real codex by PATH, skipping this shim's own dir (no recursion).
cat > "$POOL/bin/codex" <<'SHIM'
#!/bin/zsh
# Transparent `codex` shim (cxp pool). Routes model runs through the pool so the
# supervised proxy is the only token refresher; auth/meta go to the real codex.
REAL_CODEX=""
for d in ${(s/:/)PATH}; do
  [[ "$d" == "$HOME/.codexpool/bin" ]] && continue
  if [[ -x "$d/codex" ]]; then REAL_CODEX="$d/codex"; break; fi
done
[[ -z "$REAL_CODEX" ]] && { print -u2 "cxp shim: real codex not found on PATH"; exit 127; }
case "${1:-}" in
  login|logout|--version|-V|--help|-h|mcp|completion)
    exec "$REAL_CODEX" "$@" ;;
esac
CXP_AGENT="$HOME/.codexpool/cxp-agent"
[[ -x "$CXP_AGENT" ]] && exec "$CXP_AGENT" __codex "$@"
exec "$REAL_CODEX" "$@"
SHIM
chmod 0755 "$POOL/bin/codex"
echo "installed: $POOL/bin/codex (shim)"

cat <<EOF

cxp installed. Next:
  pip install -r "$HERE/requirements.txt"     # aiohttp (bridge is stdlib-only)
  export PATH="$POOL/bin:\$PATH"               # so the codex shim wins (add to your rc)
  cxp import                                   # seed pool from ~/.codex/accounts/*.auth.json
  cxp login                                    # add accounts via OAuth (repeat per account)
  cxp install-agent                            # launchd keepalive
  cxp status                                   # verify
EOF
