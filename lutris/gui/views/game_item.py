"""GObject representation of a game row for GTK4 views."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GObject

from lutris import settings
from lutris.gui.views.store_item import StoreItem
from lutris.util.strings import gtk_safe

COLUMN_PROPERTIES = (
    "id",
    "slug",
    "name",
    "sortname",
    "media_paths",
    "year",
    "runner",
    "runner_human_name",
    "platform",
    "lastplayed",
    "lastplayed_text",
    "installed",
    "installed_at",
    "installed_at_text",
    "playtime",
    "playtime_text",
)


def get_column_value(item: "GameItem", column: int):
    """Return the value for a column index on a GameItem."""
    return getattr(item, COLUMN_PROPERTIES[column])


@GObject.type_register
class GameItem(GObject.Object):
    """A single game entry exposed to GTK4 list models."""

    __gtype_name__ = "GameItem"

    id = GObject.Property(type=str, default="")
    slug = GObject.Property(type=str, default="")
    name = GObject.Property(type=str, default="")
    sortname = GObject.Property(type=str, default="")
    media_paths = GObject.Property(type=GObject.TYPE_PYOBJECT, default=None)
    year = GObject.Property(type=str, default="")
    runner = GObject.Property(type=str, default="")
    runner_human_name = GObject.Property(type=str, default="")
    platform = GObject.Property(type=str, default="")
    lastplayed = GObject.Property(type=int, default=0)
    lastplayed_text = GObject.Property(type=str, default="")
    installed = GObject.Property(type=bool, default=False)
    installed_at = GObject.Property(type=int, default=0)
    installed_at_text = GObject.Property(type=str, default="")
    playtime = GObject.Property(type=float, default=0.0)
    playtime_text = GObject.Property(type=str, default="")

    @classmethod
    def from_store_item(cls, store_item: StoreItem) -> "GameItem":
        """Create a GameItem populated from a StoreItem."""
        return cls(
            id=store_item.id,
            slug=store_item.slug,
            name=store_item.name,
            sortname=store_item.sortname if store_item.sortname else store_item.name,
            media_paths=store_item.get_media_paths() if settings.SHOW_MEDIA else [],
            year=store_item.year,
            runner=store_item.runner,
            runner_human_name=store_item.runner_text,
            platform=gtk_safe(store_item.platform),
            lastplayed=store_item.lastplayed or 0,
            lastplayed_text=store_item.lastplayed_text,
            installed=store_item.installed,
            installed_at=store_item.installed_at or 0,
            installed_at_text=store_item.installed_at_text,
            playtime=store_item.playtime,
            playtime_text=store_item.playtime_text,
        )

    def update_from_store_item(self, store_item: StoreItem) -> set[int]:
        """Update this item from a StoreItem, returning changed column indices."""
        new_values = {
            "id": store_item.id,
            "slug": store_item.slug,
            "name": store_item.name,
            "sortname": store_item.sortname if store_item.sortname else store_item.name,
            "media_paths": store_item.get_media_paths() if settings.SHOW_MEDIA else [],
            "year": store_item.year,
            "runner": store_item.runner,
            "runner_human_name": store_item.runner_text,
            "platform": gtk_safe(store_item.platform),
            "lastplayed": store_item.lastplayed or 0,
            "lastplayed_text": store_item.lastplayed_text,
            "installed": store_item.installed,
            "installed_at": store_item.installed_at or 0,
            "installed_at_text": store_item.installed_at_text,
            "playtime": store_item.playtime,
            "playtime_text": store_item.playtime_text,
        }

        changed_indices: set[int] = set()
        for index, prop_name in enumerate(COLUMN_PROPERTIES):
            new_value = new_values[prop_name]
            if getattr(self, prop_name) != new_value:
                setattr(self, prop_name, new_value)
                changed_indices.add(index)
        return changed_indices
