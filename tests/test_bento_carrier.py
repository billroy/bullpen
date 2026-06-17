"""Tests for Bento carrier inspection and preview."""

import io
import json
import os
import zipfile

import pytest

from server.app import create_app, socketio
from server.bento_carrier import BentoCarrierError, BentoLimits, inspect_bento
from server.init import init_workspace
from server.persistence import read_json


def _zip_bytes(entries, *, infos=None):
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, data in entries.items():
            zf.writestr(path, data)
        for info, data in infos or []:
            zf.writestr(info, data)
    mem.seek(0)
    return mem


def _bento_manifest(**overrides):
    manifest = {
        "format": "bento",
        "version": "1",
        "profiles": [],
        "items": [],
        "attributes": [],
    }
    manifest.update(overrides)
    return json.dumps(manifest)


def _valid_bento(**manifest_overrides):
    return _zip_bytes({"bento.json": _bento_manifest(**manifest_overrides)})


def _expect_code(archive, code, *, limits=None):
    with pytest.raises(BentoCarrierError) as err:
        inspect_bento(archive, limits=limits)
    assert err.value.code == code


def test_inspect_minimal_bento():
    preview = inspect_bento(_valid_bento())

    assert preview["ok"] is True
    assert preview["format"] == "bento"
    assert preview["version"] == "1"
    assert preview["profiles"] == []
    assert preview["items"] == []


def test_inspect_non_bullpen_bento_reports_unsupported_profile():
    preview = inspect_bento(
        _zip_bytes(
            {
                "bento.json": _bento_manifest(
                    profiles=[
                        {"id": "org.example.other", "version": "1", "label": "Other App"}
                    ],
                    items=[
                        {
                            "id": "note.one",
                            "label": "Note",
                            "media_type": "application/json",
                            "path": "payload/note.json",
                        }
                    ],
                ),
                "payload/note.json": "{}",
            }
        )
    )

    assert preview["supported_profiles"] == []
    assert preview["unsupported_profiles"] == ["org.example.other"]
    assert preview["items"][0]["path"] == "payload/note.json"


def test_rejects_invalid_zip():
    _expect_code(io.BytesIO(b"not a zip"), "invalid-zip")


def test_rejects_missing_manifest():
    _expect_code(_zip_bytes({"payload/item.json": "{}"}), "missing-manifest")


def test_rejects_invalid_manifest_json():
    _expect_code(_zip_bytes({"bento.json": "{"}), "invalid-json")


def test_rejects_manifest_root_that_is_not_object():
    _expect_code(_zip_bytes({"bento.json": "[]"}), "invalid-manifest")


def test_rejects_unsupported_version():
    _expect_code(_valid_bento(version="2"), "unsupported-version")


def test_rejects_too_many_files():
    entries = {"bento.json": _bento_manifest()}
    entries.update({f"payload/{idx}.txt": "x" for idx in range(3)})

    _expect_code(
        _zip_bytes(entries),
        "too-many-files",
        limits=BentoLimits(max_entries=3),
    )


def test_rejects_high_expansion_archive():
    archive = _zip_bytes(
        {
            "bento.json": _bento_manifest(),
            "payload/bomb.txt": "A" * 4096,
        }
    )

    _expect_code(
        archive,
        "compression-ratio",
        limits=BentoLimits(max_compression_ratio=2),
    )


def test_rejects_nested_archive_member():
    _expect_code(
        _zip_bytes({"bento.json": _bento_manifest(), "payload/nested.zip": "x"}),
        "nested-archive",
    )


def test_rejects_absolute_path():
    _expect_code(
        _zip_bytes({"bento.json": _bento_manifest(), "/payload/item.json": "{}"}),
        "absolute-path",
    )


def test_rejects_path_traversal():
    _expect_code(
        _zip_bytes({"bento.json": _bento_manifest(), "payload/../item.json": "{}"}),
        "path-traversal",
    )


def test_rejects_empty_normalized_path():
    _expect_code(
        _zip_bytes({"bento.json": _bento_manifest(), "./": ""}),
        "empty-path",
    )


def test_rejects_duplicate_normalized_paths_casefolded():
    _expect_code(
        _zip_bytes({"bento.json": _bento_manifest(), "payload/item.json": "1", "PAYLOAD/ITEM.JSON": "2"}),
        "duplicate-path",
    )


def test_rejects_windows_drive_prefix():
    _expect_code(
        _zip_bytes({"bento.json": _bento_manifest(), "C:/payload/item.json": "{}"}),
        "absolute-path",
    )


def test_rejects_symlink_member():
    info = zipfile.ZipInfo("payload/link")
    info.create_system = 3
    info.external_attr = 0o120777 << 16

    _expect_code(
        _zip_bytes({"bento.json": _bento_manifest()}, infos=[(info, "target")]),
        "special-file",
    )


def test_rejects_invalid_items_list():
    _expect_code(_valid_bento(items={}), "invalid-items")


def test_rejects_item_that_is_not_object():
    _expect_code(_valid_bento(items=["bad"]), "invalid-item")


def test_rejects_item_path_that_is_not_string():
    _expect_code(_valid_bento(items=[{"path": 123}]), "invalid-descriptor-path")


def test_rejects_missing_item_path():
    _expect_code(
        _valid_bento(items=[{"id": "missing", "path": "payload/missing.json"}]),
        "missing-item-path",
    )


def test_rejects_item_path_that_points_to_directory():
    _expect_code(
        _zip_bytes(
            {
                "bento.json": _bento_manifest(
                    items=[{"id": "dir", "path": "payload/dir"}]
                ),
                "payload/dir/": "",
            }
        ),
        "item-path-directory",
    )


def test_rejects_missing_attribute_path():
    _expect_code(
        _valid_bento(attributes=[{"label": "Preview", "path": "attributes/preview.json"}]),
        "missing-attribute-path",
    )


def test_rejects_invalid_attribute_json():
    _expect_code(
        _zip_bytes(
            {
                "bento.json": _bento_manifest(
                    attributes=[{"label": "Preview", "path": "attributes/preview.json"}]
                ),
                "attributes/preview.json": "{",
            }
        ),
        "invalid-json",
    )


def _received(client, name):
    matches = [event["args"][0] for event in client.get_received() if event["name"] == name]
    assert matches, f"missing socket event {name}"
    return matches[-1]


def test_bento_preview_event_returns_carrier_preview(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    client.emit("bento:preview", {"file": _valid_bento().getvalue()})

    assert _received(client, "bento:previewed")["ok"] is True


def test_bento_preview_event_rejects_missing_upload(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    client.emit("bento:preview", {})

    assert _received(client, "bento:error")["code"] == "missing-upload"


def test_bento_preview_event_rejects_invalid_archive(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    client.emit("bento:preview", {"file": b"not a zip"})

    assert _received(client, "bento:error")["code"] == "invalid-zip"


def test_bento_preview_event_does_not_mutate_workspace(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    before_config = read_json(os.path.join(bp_dir, "config.json"))
    before_layout = read_json(os.path.join(bp_dir, "layout.json"))

    client.emit("bento:preview", {"file": _valid_bento().getvalue()})

    assert _received(client, "bento:previewed")["ok"] is True
    assert read_json(os.path.join(bp_dir, "config.json")) == before_config
    assert read_json(os.path.join(bp_dir, "layout.json")) == before_layout
