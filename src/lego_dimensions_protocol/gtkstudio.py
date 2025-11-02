"""GTK-based interactive tag studio for LEGO Dimensions tags."""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
import sys
from pathlib import Path
from collections.abc import MutableMapping
from typing import Dict, Optional, Sequence, Tuple

from . import characters
from .characters import CharacterInfo
from .gateway import Pad, PortalNotFoundError
from .rfid import TagEvent, TagEventType, TagTracker

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - GTK imports are optional during tests
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GdkPixbuf, Gio, GLib, Gtk

    _GTK_AVAILABLE = True
except ModuleNotFoundError as exc:  # pragma: no cover - runtime import guard
    gi = None  # type: ignore
    GdkPixbuf = Gio = GLib = Gtk = None  # type: ignore
    _GTK_IMPORT_ERROR = exc
    _GTK_AVAILABLE = False
else:  # pragma: no cover - GTK imports are optional during tests
    _GTK_IMPORT_ERROR = None


_PACKAGE_ROOT = Path(__file__).resolve().parent
_VENDOR_ROOT = _PACKAGE_ROOT.parent.parent / "vendor" / "ldnfctags"
_CHARACTER_IMAGE_ROOT = _VENDOR_ROOT / "images" / "characters"


def _require_gtk() -> None:
    if not _GTK_AVAILABLE:
        raise ModuleNotFoundError(
            "PyGObject (GTK 3) is required for the graphical tag studio. "
            "Install it with 'pip install pygobject'."
        ) from _GTK_IMPORT_ERROR


def _format_pad(pad: Optional[Pad]) -> str:
    if pad is None:
        return "Removed"
    return f"{pad.name.title()} (pad {int(pad)})"


def _format_character_id(character_id: Optional[int]) -> str:
    if character_id is None:
        return "Unknown"
    return f"{character_id} (0x{character_id:04X})"


def _format_timestamp(timestamp: datetime) -> str:
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_pad(value: Optional[str]) -> Optional[Pad]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return Pad[text.upper()]
    except KeyError:
        pass
    try:
        numeric = int(text, 0)
    except (TypeError, ValueError):
        return None
    try:
        return Pad(numeric)
    except ValueError:
        return None


def _escape(text: str) -> str:
    return GLib.markup_escape_text(text) if _GTK_AVAILABLE else text


def _score_image(path: Path) -> Tuple[int, str]:
    stem = path.stem
    try:
        size_hint = int(stem.split("_")[-1])
    except (ValueError, IndexError):
        size_hint = 0
    return size_hint, stem


def find_character_image(character: Optional[CharacterInfo]) -> Optional[Path]:
    """Return the best matching character image for *character* if available."""

    if character is None:
        return None
    directory = _CHARACTER_IMAGE_ROOT
    if not directory.exists():
        return None
    pattern = f"{character.id:03d}_*.png"
    matches = sorted(directory.glob(pattern))
    if not matches:
        return None
    matches.sort(key=_score_image)
    return matches[-1]


@dataclass
class TagRecord:
    uid: str
    pad: Optional[Pad]
    character_id: Optional[int]
    character_name: Optional[str]
    character_world: Optional[str]
    write_pad: bool
    writable: bool
    writable_reason: str
    last_seen: datetime
    source: str
    image_path: Optional[Path] = None
    source_path: Optional[Path] = None

    @property
    def display_name(self) -> str:
        if self.character_name:
            return self.character_name
        return f"UID {self.uid}".strip()

    @property
    def pad_label(self) -> str:
        return _format_pad(self.pad)

    @property
    def character_id_label(self) -> str:
        return _format_character_id(self.character_id)

    @property
    def world_label(self) -> str:
        return self.character_world or "Unknown"

    @property
    def write_pad_label(self) -> str:
        return "Yes" if self.write_pad else "No"

    @property
    def writable_label(self) -> str:
        return "Yes" if self.writable else "No"

    @property
    def last_seen_label(self) -> str:
        return _format_timestamp(self.last_seen)

    @property
    def source_label(self) -> str:
        if self.source == "live":
            return "Live portal"
        if self.source == "file" and self.source_path is not None:
            return f"Saved file ({self.source_path.name})"
        if self.source == "file":
            return "Saved file"
        return self.source

    @property
    def source_path_label(self) -> str:
        return str(self.source_path) if self.source_path is not None else "—"

    def to_json(self) -> Dict[str, object]:
        return {
            "uid": self.uid,
            "pad": None if self.pad is None else self.pad.name,
            "character_id": self.character_id,
            "character_name": self.character_name,
            "character_world": self.character_world,
            "write_pad": self.write_pad,
            "writable": self.writable,
            "writable_reason": self.writable_reason,
            "last_seen": self.last_seen.astimezone(timezone.utc).isoformat(),
        }

    @classmethod
    def from_event(cls, event: TagEvent) -> "TagRecord":
        character: Optional[CharacterInfo] = event.character
        if character is None and event.character_id is not None:
            character = characters.get_character(event.character_id)
        character_name = character.name if character is not None else None
        character_world = character.world if character is not None else None
        pad = event.pad
        write_pad = pad is Pad.CENTRE

        if pad is None:
            writable = False
            reason = "Tag removed from the portal."
        elif not write_pad:
            writable = False
            reason = "Move the tag to the centre pad (pad 1) to enable writing."
        elif event.character_id is None:
            writable = False
            reason = "Waiting for the portal to read the character payload."
        else:
            writable = True
            reason = "Tag is on the write pad with character data available."

        image_path = find_character_image(character)
        return cls(
            uid=event.uid,
            pad=pad,
            character_id=event.character_id,
            character_name=character_name,
            character_world=character_world,
            write_pad=write_pad,
            writable=writable,
            writable_reason=reason,
            last_seen=datetime.now(timezone.utc),
            source="live",
            image_path=image_path,
        )

    @classmethod
    def from_json(
        cls, data: MutableMapping[str, object], *, source_path: Optional[Path] = None
    ) -> "TagRecord":
        uid = str(data.get("uid", "")).strip()
        pad = _parse_pad(data.get("pad") if isinstance(data.get("pad"), str) else None)
        try:
            character_id = int(data["character_id"]) if data.get("character_id") is not None else None
        except (TypeError, ValueError):
            character_id = None
        character = characters.get_character(character_id) if character_id is not None else None
        character_name = (
            (character.name if character else None)
            or (str(data.get("character_name")) if data.get("character_name") else None)
        )
        character_world = (
            (character.world if character else None)
            or (str(data.get("character_world")) if data.get("character_world") else None)
        )
        write_pad = bool(data.get("write_pad", pad is Pad.CENTRE))
        writable = bool(data.get("writable", write_pad and character_id is not None))
        reason = str(data.get("writable_reason") or "Loaded from snapshot.")
        last_seen_value = str(data.get("last_seen") or "")
        last_seen = _parse_timestamp(last_seen_value) if last_seen_value else datetime.now(timezone.utc)
        image_path = find_character_image(character)
        return cls(
            uid=uid,
            pad=pad,
            character_id=character_id,
            character_name=character_name,
            character_world=character_world,
            write_pad=write_pad,
            writable=writable,
            writable_reason=reason,
            last_seen=last_seen,
            source="file",
            image_path=image_path,
            source_path=source_path,
        )


class TagStudioWindow(Gtk.ApplicationWindow):  # type: ignore[misc]
    """Main GTK window for the interactive tag studio."""

    def __init__(self, app: Gtk.Application, *, poll_timeout: int = 250) -> None:  # type: ignore[misc]
        _require_gtk()
        super().__init__(application=app)
        self.set_title("LEGO Tag Studio")
        self.set_default_size(1024, 640)
        self._records: Dict[str, TagRecord] = {}
        self._row_refs: Dict[str, Gtk.TreeRowReference] = {}
        self._selected_key: Optional[str] = None
        self._tracker: Optional[TagTracker] = None
        self._tracker_listener = None
        self._poll_timeout = poll_timeout

        self._build_ui()
        self.connect("destroy", self._on_destroy)
        self._start_tracker()

    def _build_ui(self) -> None:
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = "LEGO Tag Studio"
        self.set_titlebar(header)

        self._save_button = Gtk.Button.new_from_icon_name("document-save", Gtk.IconSize.BUTTON)
        self._save_button.set_tooltip_text("Save the currently detected tags to a JSON snapshot")
        self._save_button.connect("clicked", self._on_save_clicked)
        header.pack_end(self._save_button)

        self._load_button = Gtk.Button.new_from_icon_name("document-open", Gtk.IconSize.BUTTON)
        self._load_button.set_tooltip_text("Load a previously saved tag snapshot")
        self._load_button.connect("clicked", self._on_load_clicked)
        header.pack_end(self._load_button)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(outer)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        outer.pack_start(paned, True, True, 0)

        self._store = Gtk.ListStore(str, str, str, str, str, object)
        tree = Gtk.TreeView(model=self._store)
        tree.set_headers_visible(True)
        tree.append_column(self._build_column("Tag", 1))
        tree.append_column(self._build_column("Pad", 2))
        tree.append_column(self._build_column("Source", 3))
        tree.append_column(self._build_column("Last seen", 4))
        selection = tree.get_selection()
        selection.connect("changed", self._on_selection_changed)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(tree)
        paned.add1(scroll)
        self._tree = tree

        detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        detail_box.set_border_width(12)
        paned.add2(detail_box)

        self._detail_title = Gtk.Label(xalign=0)
        self._detail_title.set_use_markup(True)
        detail_box.pack_start(self._detail_title, False, False, 0)

        self._detail_subtitle = Gtk.Label(xalign=0)
        detail_box.pack_start(self._detail_subtitle, False, False, 0)

        self._detail_image = Gtk.Image()
        self._detail_image.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
        detail_box.pack_start(self._detail_image, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        detail_box.pack_start(grid, False, False, 0)

        fields = [
            ("UID", "uid"),
            ("Character ID", "character_id"),
            ("World", "world"),
            ("Pad", "pad"),
            ("Write pad", "write_pad"),
            ("Writable", "writable"),
            ("Last seen", "last_seen"),
            ("Source", "source"),
            ("Source file", "source_path"),
        ]
        self._detail_labels: Dict[str, Gtk.Label] = {}
        for row, (title, key) in enumerate(fields):
            title_label = Gtk.Label(label=f"{title}:", xalign=1)
            title_label.get_style_context().add_class("dim-label")
            value_label = Gtk.Label(xalign=0)
            value_label.set_selectable(True)
            grid.attach(title_label, 0, row, 1, 1)
            grid.attach(value_label, 1, row, 1, 1)
            self._detail_labels[key] = value_label

        self._writable_reason_label = Gtk.Label(xalign=0)
        self._writable_reason_label.set_line_wrap(True)
        self._writable_reason_label.set_selectable(True)
        detail_box.pack_start(self._writable_reason_label, False, False, 0)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        status_box.set_border_width(6)
        outer.pack_end(status_box, False, False, 0)

        self._status_label = Gtk.Label(xalign=0)
        status_box.pack_start(self._status_label, True, True, 0)

        self._clear_detail()
        self._update_action_sensitivity()

    def _build_column(self, title: str, column: int) -> Gtk.TreeViewColumn:
        renderer = Gtk.CellRendererText()
        column_obj = Gtk.TreeViewColumn(title, renderer, text=column)
        column_obj.set_resizable(True)
        column_obj.set_expand(column == 1)
        return column_obj

    def _start_tracker(self) -> None:
        try:
            tracker = TagTracker(poll_timeout=self._poll_timeout)
        except ModuleNotFoundError as exc:
            LOGGER.warning("PyUSB is not available: %s", exc)
            self._set_status("PyUSB is required to talk to the LEGO Dimensions portal.", error=True)
            self._tracker = None
            return
        except PortalNotFoundError as exc:
            LOGGER.warning("Toy pad gateway not found: %s", exc)
            self._set_status("Toy pad gateway not found. Connect the portal and retry.", error=True)
            self._tracker = None
            return
        except Exception as exc:
            LOGGER.exception("Failed to start tag tracker")
            self._set_status(f"Unable to start tag tracker: {exc}", error=True)
            self._tracker = None
            return

        self._tracker = tracker

        def _listener(event: TagEvent) -> None:
            GLib.idle_add(self._handle_event, event)

        self._tracker_listener = _listener
        tracker.add_listener(_listener)
        self._set_status("Listening for tags on the LEGO Dimensions portal…")

    def _handle_event(self, event: TagEvent) -> bool:
        key = f"live:{event.uid.lower()}"
        if event.type is TagEventType.REMOVED:
            existing = self._records.get(key)
            if existing is not None:
                self._set_status(f"Removed {existing.display_name} from the portal.")
            self._remove_record(key)
            return False

        record = TagRecord.from_event(event)
        if self._tracker is None:
            record.writable = False
            record.writable_reason = "Portal connection unavailable."
        self._records[key] = record
        self._update_row(key, record)
        self._set_status(f"Detected {record.display_name} on {record.pad_label}.")
        return False

    def _update_row(self, key: str, record: TagRecord) -> None:
        values = [
            key,
            record.display_name,
            record.pad_label,
            record.source_label,
            record.last_seen_label,
            record,
        ]
        row_ref = self._row_refs.get(key)
        if row_ref is not None:
            path = row_ref.get_path()
            if path is not None:
                tree_iter = self._store.get_iter(path)
                self._store[tree_iter] = values
        else:
            tree_iter = self._store.append(values)
            path = self._store.get_path(tree_iter)
            if path is not None:
                self._row_refs[key] = Gtk.TreeRowReference.new(self._store, path)
            if self._selected_key is None:
                self._tree.get_selection().select_path(path)
        self._update_action_sensitivity()
        if self._selected_key == key:
            self._show_record(record)

    def _remove_record(self, key: str) -> None:
        self._records.pop(key, None)
        row_ref = self._row_refs.pop(key, None)
        if row_ref is not None:
            path = row_ref.get_path()
            if path is not None:
                tree_iter = self._store.get_iter(path)
                self._store.remove(tree_iter)
        if self._selected_key == key:
            self._selected_key = None
            self._clear_detail()
        self._update_action_sensitivity()

    def _on_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model, tree_iter = selection.get_selected()
        if tree_iter is None:
            self._selected_key = None
            self._clear_detail()
            return
        key = model[tree_iter][0]
        record = model[tree_iter][5]
        self._selected_key = key
        self._show_record(record)

    def _show_record(self, record: TagRecord) -> None:
        title = _escape(record.display_name)
        self._detail_title.set_markup(f"<span size='xx-large' weight='bold'>{title}</span>")
        self._detail_subtitle.set_text(f"World: {record.world_label}")

        if record.image_path and record.image_path.exists():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(record.image_path), width=320, height=320, preserve_aspect_ratio=True
                )
                self._detail_image.set_from_pixbuf(pixbuf)
            except Exception:
                LOGGER.exception("Failed to load character artwork from %s", record.image_path)
                self._detail_image.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
        else:
            self._detail_image.set_from_icon_name("image-x-generic", Gtk.IconSize.DIALOG)

        self._detail_labels["uid"].set_text(record.uid)
        self._detail_labels["character_id"].set_text(record.character_id_label)
        self._detail_labels["world"].set_text(record.world_label)
        self._detail_labels["pad"].set_text(record.pad_label)
        self._detail_labels["write_pad"].set_text(record.write_pad_label)
        self._detail_labels["writable"].set_text(record.writable_label)
        self._detail_labels["last_seen"].set_text(record.last_seen_label)
        self._detail_labels["source"].set_text(record.source_label)
        self._detail_labels["source_path"].set_text(record.source_path_label)
        self._writable_reason_label.set_text(record.writable_reason)

    def _clear_detail(self) -> None:
        self._detail_title.set_markup("<span size='xx-large' weight='bold'>No tag selected</span>")
        self._detail_subtitle.set_text("Place a tag on the portal to view its details.")
        self._detail_image.set_from_icon_name("image-x-generic", Gtk.IconSize.DIALOG)
        for label in self._detail_labels.values():
            label.set_text("—")
        self._writable_reason_label.set_text("")

    def _set_status(self, message: str, *, error: bool = False) -> None:
        prefix = "⚠ " if error else ""
        self._status_label.set_text(f"{prefix}{message}")

    def _update_action_sensitivity(self) -> None:
        has_live = any(key.startswith("live:") for key in self._records)
        self._save_button.set_sensitive(has_live)

    def _on_save_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserDialog(
            title="Save tag snapshot",
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE,
            Gtk.ResponseType.ACCEPT,
        )
        dialog.set_do_overwrite_confirmation(True)
        filter_json = Gtk.FileFilter()
        filter_json.set_name("JSON files")
        filter_json.add_pattern("*.json")
        dialog.add_filter(filter_json)
        dialog.set_current_name("tag_snapshot.json")

        try:
            response = dialog.run()
            if response == Gtk.ResponseType.ACCEPT:
                filename = dialog.get_filename()
                if filename:
                    self._save_snapshot(Path(filename))
        finally:
            dialog.destroy()

    def _save_snapshot(self, path: Path) -> None:
        live_records = [record for key, record in self._records.items() if key.startswith("live:")]
        data = {"tags": [record.to_json() for record in live_records]}
        try:
            path.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            LOGGER.exception("Failed to save snapshot to %s", path)
            self._set_status(f"Failed to save snapshot: {exc}", error=True)
            return
        self._set_status(f"Saved {len(live_records)} tag(s) to {path}.")

    def _on_load_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserDialog(
            title="Load tag snapshot",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,
            Gtk.ResponseType.ACCEPT,
        )
        filter_json = Gtk.FileFilter()
        filter_json.set_name("JSON files")
        filter_json.add_pattern("*.json")
        dialog.add_filter(filter_json)

        try:
            response = dialog.run()
            if response == Gtk.ResponseType.ACCEPT:
                filename = dialog.get_filename()
                if filename:
                    self._load_snapshot(Path(filename))
        finally:
            dialog.destroy()

    def _load_snapshot(self, path: Path) -> None:
        try:
            contents = path.read_text()
            payload = json.loads(contents)
        except FileNotFoundError:
            self._set_status(f"Snapshot {path} does not exist.", error=True)
            return
        except json.JSONDecodeError as exc:
            self._set_status(f"Failed to read snapshot: {exc}", error=True)
            return
        except Exception as exc:
            LOGGER.exception("Failed to load snapshot from %s", path)
            self._set_status(f"Unable to load snapshot: {exc}", error=True)
            return

        tags = payload.get("tags", [])
        if not isinstance(tags, list):
            self._set_status("Invalid snapshot format.", error=True)
            return

        self._remove_file_records()

        loaded = 0
        for index, entry in enumerate(tags):
            if not isinstance(entry, MutableMapping):
                continue
            try:
                record = TagRecord.from_json(entry, source_path=path)
            except Exception:
                LOGGER.exception("Failed to parse snapshot entry %s", index)
                continue
            key = f"file:{path}:{index}"
            self._records[key] = record
            self._update_row(key, record)
            loaded += 1

        if loaded == 0:
            self._set_status(f"No tags found in {path.name}.", error=True)
        else:
            self._set_status(f"Loaded {loaded} tag(s) from {path.name}.")

    def _remove_file_records(self) -> None:
        to_remove = [key for key in self._records if key.startswith("file:")]
        for key in to_remove:
            self._remove_record(key)

    def _on_destroy(self, *_args) -> None:
        if self._tracker is not None and self._tracker_listener is not None:
            self._tracker.remove_listener(self._tracker_listener)
            self._tracker_listener = None
        if self._tracker is not None:
            self._tracker.close()
            self._tracker = None


class TagStudioApplication(Gtk.Application):  # type: ignore[misc]
    """GTK application wrapper for the tag studio."""

    def __init__(self, *, poll_timeout: int = 250) -> None:
        _require_gtk()
        super().__init__(application_id="io.github.lego.dimensions.TagStudio")
        self._poll_timeout = poll_timeout
        self._window: Optional[TagStudioWindow] = None

    def do_activate(self) -> None:  # pragma: no cover - GTK lifecycle
        if self._window is None:
            self._window = TagStudioWindow(self, poll_timeout=self._poll_timeout)
        self._window.present()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the GTK tag studio application."""

    _require_gtk()
    if argv is None:
        raw_args = sys.argv[1:]
        program_name = sys.argv[0]
    else:
        raw_args = list(argv)
        program_name = "lego-tag-studio-gtk"

    parser = argparse.ArgumentParser(prog=program_name, description="Interactive GTK tag studio")
    parser.add_argument(
        "--timeout",
        type=int,
        default=250,
        help="Poll timeout in milliseconds while waiting for tag updates",
    )
    args, extra = parser.parse_known_args(raw_args)

    app = TagStudioApplication(poll_timeout=args.timeout)
    exit_code = app.run([program_name, *extra])
    return int(exit_code)


__all__ = [
    "TagStudioApplication",
    "TagStudioWindow",
    "find_character_image",
    "main",
]
