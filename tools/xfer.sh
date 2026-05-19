#!/usr/bin/env bash
# xfer.sh — file transfer between ThinkPad and desktop
# Usage:
#   xfer.sh pull <remote-path> [local-dest]   # desktop → ThinkPad
#   xfer.sh push <local-path> [remote-dest]   # ThinkPad → desktop
#   xfer.sh ls <remote-path>                  # list files on desktop
#
# <remote-path> is relative to ~ on desktop unless it starts with /
# [local-dest] defaults to current directory
# [remote-dest] defaults to same path as source

set -euo pipefail

REMOTE_HOST="192.168.12.237"
REMOTE_USER="sean-campbell"
SSH_KEY="$HOME/.ssh/id_ed25519_desktop"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"

usage() {
    echo "Usage: xfer.sh pull <remote-path> [local-dest]"
    echo "       xfer.sh push <local-path> [remote-dest]"
    echo "       xfer.sh ls <remote-path>"
    exit 1
}

[[ $# -lt 2 ]] && usage

CMD="$1"
PATH1="$2"
PATH2="${3:-}"

case "$CMD" in
    pull)
        REMOTE_PATH="$PATH1"
        LOCAL_DEST="${PATH2:-.}"
        echo "[xfer] pull: desktop:$REMOTE_PATH → $LOCAL_DEST"
        rsync -avz --progress -e "ssh -i $SSH_KEY" "${REMOTE}:${REMOTE_PATH}" "$LOCAL_DEST"
        ;;
    push)
        LOCAL_PATH="$PATH1"
        REMOTE_DEST="${PATH2:-$(dirname "$LOCAL_PATH")}"
        echo "[xfer] push: $LOCAL_PATH → desktop:$REMOTE_DEST"
        rsync -avz --progress -e "ssh -i $SSH_KEY" "$LOCAL_PATH" "${REMOTE}:${REMOTE_DEST}"
        ;;
    ls)
        REMOTE_PATH="$PATH1"
        ssh -i "$SSH_KEY" "$REMOTE" ls -lah "$REMOTE_PATH"
        ;;
    *)
        usage
        ;;
esac
