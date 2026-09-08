#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <frontend-dist.tar.gz> [release-id]" >&2
  exit 2
fi

archive_path="$1"
release_id="${2:-$(date +%Y%m%d-%H%M%S)}"
release_root="${TOKENPOOL_RELEASE_ROOT:-/var/www/tokenpool-releases}"
current_link="${TOKENPOOL_CURRENT_LINK:-/var/www/tokenpool-current}"
web_owner="${TOKENPOOL_WEB_OWNER:-www-data}"
web_group="${TOKENPOOL_WEB_GROUP:-www-data}"
http_base_url="${TOKENPOOL_HTTP_BASE_URL:-http://127.0.0.1}"
python="${TOKENPOOL_PYTHON:-python3}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
validator="${script_dir}/validate_frontend_release.py"
release_dir="${release_root}/${release_id}"
next_link="${current_link}.next.$$"
next_link_owned=0
previous_target=""
manifest=""
activated=0
success=0

cleanup() {
  exit_status=$?
  trap - EXIT
  if (( activated && ! success )); then
    echo "Frontend verification failed; restoring previous link" >&2
    if [[ -n "$previous_target" ]]; then
      ln -s -- "$previous_target" "$next_link"
      next_link_owned=1
      mv -Tf -- "$next_link" "$current_link"
      next_link_owned=0
    elif [[ -L "$current_link" && "$(readlink -- "$current_link")" == "$release_dir" ]]; then
      rm -f -- "$current_link"
    fi
    systemctl reload nginx || echo "Warning: nginx reload after rollback failed" >&2
  fi
  if (( next_link_owned )); then rm -f -- "$next_link"; fi
  [[ -z "$manifest" ]] || rm -f -- "$manifest"
  exit "$exit_status"
}
trap cleanup EXIT

if [[ ! -f "$archive_path" ]]; then
  echo "Archive does not exist: $archive_path" >&2
  exit 2
fi
if [[ ! "$release_id" =~ ^[0-9A-Za-z._-]+$ || "$release_id" == "." || "$release_id" == ".." ]]; then
  echo "Invalid release id: $release_id" >&2
  exit 2
fi
if [[ "$release_root" != /* || "$current_link" != /* || "$release_root" == "/" || "$current_link" == "/" ]]; then
  echo "Release root and current link must be explicit absolute non-root paths" >&2
  exit 2
fi
if [[ -e "$release_dir" || -L "$release_dir" || -e "$next_link" || -L "$next_link" ]]; then
  echo "Release already exists: $release_dir" >&2
  exit 2
fi

if [[ -e "$current_link" && ! -L "$current_link" ]]; then
  echo "Current path is not a symlink: $current_link" >&2
  exit 2
fi
install -d -o "$web_owner" -g "$web_group" "$release_root"
exec 9>"${release_root}/.deploy.lock"
flock -n 9 || { echo "Another frontend deployment is active" >&2; exit 1; }
if [[ -L "$current_link" ]]; then
  previous_target="$(readlink -- "$current_link")"
  previous_dir="$(readlink -f -- "$current_link")"
  if [[ ! -d "$previous_dir" || ! -f "$previous_dir/index.html" ]]; then
    echo "Previous release is not a valid directory" >&2
    exit 1
  fi
fi

# Validate nginx while the old frontend is still active.
nginx -t
manifest="$(mktemp "${release_root}/.verify-${release_id}.XXXXXX")"
prepare_args=(prepare "$archive_path" "$release_dir")
if [[ -n "$previous_target" ]]; then
  prepare_args+=(--previous "$previous_dir")
fi
"$python" "$validator" "${prepare_args[@]}" > "$manifest"
chown -R -- "$web_owner:$web_group" "$release_dir"

echo "Previous frontend link: ${previous_target:-<absent>}"
ln -s -- "$release_dir" "$next_link"
next_link_owned=1
mv -Tf -- "$next_link" "$current_link"
next_link_owned=0
activated=1

systemctl reload nginx
"$python" "$validator" verify "$manifest" "$http_base_url"
success=1
echo "Frontend release activated: $release_dir"
