#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <frontend-dist.tar.gz> [release-id]" >&2
  exit 2
fi

archive_path="$1"
release_id="${2:-$(date +%Y%m%d-%H%M%S)}"
release_root="/var/www/tokenpool-releases"
current_link="/var/www/tokenpool-current"
release_dir="${release_root}/${release_id}"
next_link="${current_link}.next.$$"
trap 'rm -f "$next_link"' EXIT

if [[ ! -f "$archive_path" ]]; then
  echo "Archive does not exist: $archive_path" >&2
  exit 2
fi
if [[ ! "$release_id" =~ ^[0-9A-Za-z._-]+$ ]]; then
  echo "Invalid release id: $release_id" >&2
  exit 2
fi
if [[ -e "$release_dir" ]]; then
  echo "Release already exists: $release_dir" >&2
  exit 2
fi

install -d -o www-data -g www-data "$release_root"
install -d -o www-data -g www-data "$release_dir"
tar -xzf "$archive_path" -C "$release_dir"

if [[ ! -f "${release_dir}/index.html" ]]; then
  echo "Release has no index.html: $release_dir" >&2
  exit 1
fi

chown -R www-data:www-data "$release_dir"
ln -s "$release_dir" "$next_link"
mv -Tf "$next_link" "$current_link"

nginx -t
systemctl reload nginx
echo "Frontend release activated: $release_dir"
