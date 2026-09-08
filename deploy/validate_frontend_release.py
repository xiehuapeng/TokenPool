#!/usr/bin/env python3
"""Validate and smoke-test immutable frontend releases using the standard library.

JS checking covers literal relative JS/CSS references and Vite assets/ preload
tables. Runtime-computed URLs still need a browser smoke test.
"""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
from urllib.parse import quote, unquote, urlsplit


JS_REFERENCE = re.compile(r'''["']((?:\.{1,2}/|/|assets/)[^"'\\\s]+\.(?:m?js|css)(?:[?#][^"'\\\s]*)?)["']''')
CSS_REFERENCE = re.compile(r'''url\(\s*["']?([^"')\s]+)["']?\s*\)|@import\s+["']([^"']+)["']''')


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def checked_member(member):
    name = member.name
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
            or re.match(r"^[A-Za-z]:", name) or any(ord(c) < 32 for c in name)):
        raise ValueError(f"Unsafe archive member: {name!r}")
    if not (member.isdir() or member.isfile()):
        raise ValueError(f"Archive member is not a regular file/directory: {name!r}")
    if str(path) == "." and not member.isdir():
        raise ValueError("Archive root must be a directory")
    return path


class IndexReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.references.append(attrs["src"])
        if tag == "link" and attrs.get("href"):
            rel = attrs.get("rel", "").lower().split()
            if (set(rel) & {"stylesheet", "modulepreload"}
                    or urlsplit(attrs["href"]).path.endswith((".js", ".mjs", ".css"))
                    or ("preload" in rel and attrs.get("as") in {"script", "style"})):
                self.references.append(attrs["href"])


def local_reference(root, source, reference):
    url = urlsplit(reference)
    if url.scheme or url.netloc or not url.path:
        return None
    path = unquote(url.path)
    # Vite's dependency tables use assets/... relative to the document root.
    candidate = root / path.lstrip("/") if path.startswith(("/", "assets/")) else source.parent / path
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        raise ValueError(f"Missing/unsafe local reference in {source.relative_to(root)}: {reference!r}")
    return candidate


def validate_files(root):
    index = root / "index.html"
    if not index.is_file():
        raise ValueError("Release has no index.html")
    parser = IndexReferences()
    parser.feed(index.read_text(encoding="utf-8"))
    references = set()
    for reference in parser.references:
        target = local_reference(root, index, reference)
        if target:
            references.add(target)
    for source in root.rglob("*"):
        if source.is_symlink():
            raise ValueError(f"Release contains a symlink: {source}")
        if not source.is_file() or source.suffix not in {".js", ".mjs", ".css"}:
            continue
        text = source.read_text(encoding="utf-8")
        if source.suffix == ".css":
            literals = [left or right for left, right in CSS_REFERENCE.findall(text)]
        else:
            literals = JS_REFERENCE.findall(text)
        for reference in literals:
            target = local_reference(root, source, reference)
            if target:
                references.add(target)
    return references


def preserve_assets(previous, destination):
    old_assets = previous / "assets"
    if old_assets.is_symlink():
        raise ValueError("Previous assets directory must not be a symlink")
    if not old_assets.exists():
        return
    for source in sorted(old_assets.rglob("*")):
        if source.is_symlink() or not (source.is_dir() or source.is_file()):
            raise ValueError(f"Unsafe previous asset: {source}")
        target = destination / "assets" / source.relative_to(old_assets)
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif target.exists():
            if not target.is_file() or digest(source) != digest(target):
                raise ValueError(f"Asset name collision with different content: {target.relative_to(destination)}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def prepare(archive, destination, previous):
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"Release already exists: {destination}")
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if len(members) > 10000 or sum(item.size for item in members) > 512 * 1024 * 1024:
            raise ValueError("Archive exceeds 10000 entries or 512 MiB uncompressed")
        seen = set()
        checked = []
        for member in members:
            path = checked_member(member)
            if path in seen:
                raise ValueError(f"Duplicate archive member: {member.name!r}")
            seen.add(path)
            checked.append((member, path))
        # No archive entry is written until every member has been checked.
        destination.mkdir()
        for member, path in checked:
            target = destination / path
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o644)
    references = validate_files(destination)
    if previous:
        preserve_assets(previous, destination)
    assets = destination / "assets"
    files = {destination / "index.html", *references}
    if assets.exists():
        files.update(item for item in assets.rglob("*") if item.is_file())
    return {item.relative_to(destination).as_posix(): digest(item) for item in sorted(files)}


def verify(manifest, base_url):
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.query or parsed.fragment:
        raise ValueError("HTTP base URL must use http(s) without query/fragment")
    expected = json.loads(manifest.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="tokenpool-http-check-") as temporary:
        response = Path(temporary) / "body"
        # Check the actual homepage as well as index.html and every asset.
        checks = [("", expected["index.html"]), *expected.items()]
        for path, expected_hash in checks:
            url = base_url.rstrip("/") + "/" + quote(path, safe="/")
            subprocess.run([
                "curl", "--fail", "--silent", "--show-error", "--max-time", "15",
                "--header", "Cache-Control: no-cache", "--output", str(response),
                "--url", url,
            ], check=True)
            if digest(response) != expected_hash:
                raise ValueError(f"HTTP content mismatch: /{path}")
    print(f"HTTP verification passed: {len(checks)} homepage/assets")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    preparing = sub.add_parser("prepare")
    preparing.add_argument("archive", type=Path)
    preparing.add_argument("destination", type=Path)
    preparing.add_argument("--previous", type=Path)
    verifying = sub.add_parser("verify")
    verifying.add_argument("manifest", type=Path)
    verifying.add_argument("base_url")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            print(json.dumps(prepare(args.archive, args.destination, args.previous), sort_keys=True))
        else:
            verify(args.manifest, args.base_url)
    except (ValueError, OSError, tarfile.TarError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Frontend validation failed: {error}\n")


if __name__ == "__main__":
    main()
