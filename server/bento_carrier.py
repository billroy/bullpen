"""Safe inspection for Bento carrier archives."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import zipfile


_NESTED_ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tgz",
    ".tar.gz",
    ".tbz",
    ".tbz2",
    ".tar.bz2",
    ".txz",
    ".tar.xz",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
)


@dataclass(frozen=True)
class BentoLimits:
    max_entries: int = 256
    max_total_uncompressed_bytes: int = 25 * 1024 * 1024
    max_member_uncompressed_bytes: int = 5 * 1024 * 1024
    max_json_member_bytes: int = 2 * 1024 * 1024
    max_manifest_bytes: int = 512 * 1024
    max_compression_ratio: int = 100
    max_json_depth: int = 64


class BentoCarrierError(ValueError):
    """Raised when a Bento carrier fails safe inspection."""

    def __init__(self, message: str, code: str = "invalid-bento"):
        super().__init__(message)
        self.message = message
        self.code = code


def _json_depth(value, depth=0):
    if isinstance(value, dict):
        if not value:
            return depth + 1
        return max(_json_depth(item, depth + 1) for item in value.values())
    if isinstance(value, list):
        if not value:
            return depth + 1
        return max(_json_depth(item, depth + 1) for item in value)
    return depth + 1


def _normalize_member_name(name):
    raw = str(name or "").replace("\\", "/")
    if "\x00" in raw:
        raise BentoCarrierError("Archive contains a NUL byte in a path", "nul-path")
    if not raw:
        raise BentoCarrierError("Archive contains an empty path", "empty-path")
    if raw.startswith("/"):
        raise BentoCarrierError("Archive contains an absolute path", "absolute-path")
    if re.match(r"^[A-Za-z]:", raw):
        raise BentoCarrierError("Archive contains an invalid absolute path", "absolute-path")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts:
        raise BentoCarrierError("Archive contains an empty normalized path", "empty-path")
    if any(part == ".." for part in parts):
        raise BentoCarrierError("Archive contains invalid relative paths", "path-traversal")
    if parts[0].endswith(":"):
        raise BentoCarrierError("Archive contains an invalid absolute path", "absolute-path")
    normalized = "/".join(parts)
    return normalized, normalized.casefold()


def _is_special_member(info):
    # ZIP stores Unix file type bits in the high 16 bits of external_attr.
    mode = (int(getattr(info, "external_attr", 0) or 0) >> 16) & 0o170000
    if mode == 0:
        return False
    regular = 0o100000
    directory = 0o040000
    return mode not in (regular, directory)


def _decode_json_member(zf, name, *, code, max_bytes, max_depth):
    try:
        info = zf.getinfo(name)
    except KeyError as exc:
        raise BentoCarrierError(f"Archive is missing {name}", code) from exc
    if info.file_size > max_bytes:
        raise BentoCarrierError(f"{name} is too large", "json-too-large")
    try:
        raw = zf.read(info)
    except RuntimeError as exc:
        raise BentoCarrierError("Archive contains an encrypted member", "encrypted-member") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BentoCarrierError(f"{name} must be UTF-8 JSON", "invalid-json-encoding") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BentoCarrierError(f"{name} must be valid JSON", "invalid-json") from exc
    if _json_depth(data) > max_depth:
        raise BentoCarrierError(f"{name} JSON is too deeply nested", "json-too-deep")
    return data


def _descriptor_path(descriptor):
    path = descriptor.get("path")
    if path is None:
        return None
    if not isinstance(path, str):
        raise BentoCarrierError("Manifest descriptor path must be a string", "invalid-descriptor-path")
    normalized, _folded = _normalize_member_name(path)
    return normalized


def _validate_attribute_bundle(descriptor, files, zf, limits):
    if not isinstance(descriptor, dict):
        raise BentoCarrierError("Attribute descriptor must be an object", "invalid-attribute")
    path = _descriptor_path(descriptor)
    if not path:
        return
    if path not in files:
        raise BentoCarrierError("Attribute path does not reference a file", "missing-attribute-path")
    _decode_json_member(
        zf,
        path,
        code="invalid-attribute-json",
        max_bytes=limits.max_json_member_bytes,
        max_depth=limits.max_json_depth,
    )


def _validate_manifest(manifest, files, directories, zf, limits):
    if not isinstance(manifest, dict):
        raise BentoCarrierError("bento.json root must be an object", "invalid-manifest")
    if manifest.get("format") != "bento":
        raise BentoCarrierError("bento.json format must be 'bento'", "invalid-format")
    if manifest.get("version") != "1":
        raise BentoCarrierError("Unsupported Bento version", "unsupported-version")

    profiles = manifest.get("profiles", [])
    items = manifest.get("items", [])
    attributes = manifest.get("attributes", [])
    if not isinstance(profiles, list):
        raise BentoCarrierError("Manifest profiles must be a list", "invalid-profiles")
    if not isinstance(items, list):
        raise BentoCarrierError("Manifest items must be a list", "invalid-items")
    if not isinstance(attributes, list):
        raise BentoCarrierError("Manifest attributes must be a list", "invalid-attributes")

    for item in items:
        if not isinstance(item, dict):
            raise BentoCarrierError("Item descriptor must be an object", "invalid-item")
        path = _descriptor_path(item)
        if path:
            if path in directories:
                raise BentoCarrierError("Item path must reference a file", "item-path-directory")
            if path not in files:
                raise BentoCarrierError("Item path does not reference a file", "missing-item-path")
        for attr in item.get("attributes", []) or []:
            _validate_attribute_bundle(attr, files, zf, limits)

    for attr in attributes:
        _validate_attribute_bundle(attr, files, zf, limits)

    return profiles, items, attributes


def _safe_profile(profile):
    if not isinstance(profile, dict):
        return {"id": "", "version": "", "label": ""}
    return {
        "id": str(profile.get("id") or ""),
        "version": str(profile.get("version") or ""),
        "label": str(profile.get("label") or ""),
    }


def _safe_item(item):
    return {
        "id": str(item.get("id") or ""),
        "label": str(item.get("label") or ""),
        "media_type": str(item.get("media_type") or ""),
        "path": str(item.get("path") or ""),
    }


def _safe_attribute(attribute):
    return {
        "label": str(attribute.get("label") or ""),
        "namespace": str(attribute.get("namespace") or ""),
        "name": str(attribute.get("name") or ""),
        "version": str(attribute.get("version") or ""),
        "path": str(attribute.get("path") or ""),
        "inline": "data" in attribute,
    }


def inspect_bento(fileobj, *, limits=None):
    """Validate a Bento carrier and return a preview-safe summary."""
    limits = limits or BentoLimits()
    try:
        with zipfile.ZipFile(fileobj, "r") as zf:
            normalized_names = {}
            files = set()
            directories = set()
            total_size = 0
            total_compressed_size = 0
            infos = zf.infolist()
            if len(infos) > limits.max_entries:
                raise BentoCarrierError("Archive contains too many files", "too-many-files")

            for info in infos:
                normalized, folded = _normalize_member_name(info.filename)
                if folded in normalized_names:
                    raise BentoCarrierError(
                        "Archive contains duplicate normalized paths",
                        "duplicate-path",
                    )
                normalized_names[folded] = normalized

                if _is_special_member(info):
                    raise BentoCarrierError("Archive contains special files", "special-file")
                if int(getattr(info, "flag_bits", 0) or 0) & 0x1:
                    raise BentoCarrierError("Archive contains encrypted members", "encrypted-member")

                is_directory = (info.filename or "").replace("\\", "/").endswith("/")
                lower_name = normalized.casefold()
                if not is_directory and any(lower_name.endswith(suffix) for suffix in _NESTED_ARCHIVE_SUFFIXES):
                    raise BentoCarrierError("Archive contains nested archive files", "nested-archive")

                compressed_size = max(0, int(info.compress_size or 0))
                member_size = max(0, int(info.file_size or 0))
                total_compressed_size += max(1, compressed_size)
                total_size += member_size
                if member_size > limits.max_member_uncompressed_bytes:
                    raise BentoCarrierError("Archive member is too large", "member-too-large")
                if total_size > limits.max_total_uncompressed_bytes:
                    raise BentoCarrierError("Archive is too large", "archive-too-large")
                if member_size > max(1, compressed_size) * limits.max_compression_ratio:
                    raise BentoCarrierError("Archive contains highly compressed entries", "compression-ratio")
                if total_size > total_compressed_size * limits.max_compression_ratio:
                    raise BentoCarrierError("Archive compression ratio is too high", "compression-ratio")

                if is_directory:
                    directories.add(normalized)
                else:
                    files.add(normalized)

            if "bento.json" not in files:
                raise BentoCarrierError("Archive is missing bento.json", "missing-manifest")
            manifest = _decode_json_member(
                zf,
                "bento.json",
                code="missing-manifest",
                max_bytes=limits.max_manifest_bytes,
                max_depth=limits.max_json_depth,
            )
            profiles, items, attributes = _validate_manifest(manifest, files, directories, zf, limits)
    except zipfile.BadZipFile as exc:
        raise BentoCarrierError("Invalid zip file", "invalid-zip") from exc

    safe_profiles = [_safe_profile(profile) for profile in profiles]
    unsupported = [profile["id"] for profile in safe_profiles if profile["id"]]
    return {
        "ok": True,
        "format": "bento",
        "version": "1",
        "profiles": safe_profiles,
        "items": [_safe_item(item) for item in items],
        "attributes": [_safe_attribute(attr) for attr in attributes if isinstance(attr, dict)],
        "supported_profiles": [],
        "unsupported_profiles": unsupported,
        "warnings": [],
    }
