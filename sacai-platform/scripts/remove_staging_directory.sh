#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-}"
case "${TARGET}" in
  /private/tmp/*|/tmp/*|/private/var/folders/*/T/*|/var/folders/*/T/*)
    rm -rf -- "${TARGET}"
    ;;
  *)
    echo "Refusing to remove non-temporary staging path: ${TARGET}" >&2
    exit 1
    ;;
esac
