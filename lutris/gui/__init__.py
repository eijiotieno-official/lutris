"""Lutris GUI package"""

import gi

gi.require_version("PangoCairo", "1.0")

from gi.repository import Gtk


def _box_pack_start(box: Gtk.Box, child, expand=False, fill=False, padding=0) -> None:  # noqa: ARG001
    if expand:
        child.set_hexpand(True)
    if fill:
        child.set_vexpand(True)
    box.append(child)


def _box_pack_end(box: Gtk.Box, child, expand=False, fill=False, padding=0) -> None:  # noqa: ARG001
    if expand:
        child.set_hexpand(True)
    if fill:
        child.set_vexpand(True)
    box.append(child)


if not hasattr(Gtk.Box, "pack_start"):
    Gtk.Box.pack_start = _box_pack_start  # type: ignore[attr-defined]
    Gtk.Box.pack_end = _box_pack_end  # type: ignore[attr-defined]

if not hasattr(Gtk.Widget, "get_toplevel"):
    Gtk.Widget.get_toplevel = Gtk.Widget.get_root  # type: ignore[attr-defined]
