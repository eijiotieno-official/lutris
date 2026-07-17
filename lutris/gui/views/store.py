"""Store object for a list of games"""

# pylint: disable=not-an-iterable
from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")

if TYPE_CHECKING:
    from lutris.services.base import BaseService
    from lutris.services.service_media import ServiceMedia

from gi.repository import Gio, GObject, Gtk

from lutris import settings
from lutris.database.games import get_all_installed_game_for_service
from lutris.gui.views.game_item import GameItem, get_column_value
from lutris.gui.views.store_item import StoreItem

from . import (
    COL_ID,
    COL_INSTALLED,
    COL_INSTALLED_AT,
    COL_INSTALLED_AT_TEXT,
    COL_LASTPLAYED,
    COL_LASTPLAYED_TEXT,
    COL_MEDIA_PATHS,
    COL_NAME,
    COL_PLATFORM,
    COL_PLAYTIME,
    COL_PLAYTIME_TEXT,
    COL_RUNNER,
    COL_RUNNER_HUMAN_NAME,
    COL_SLUG,
    COL_SORTNAME,
    COL_YEAR,
)


def try_lower(value):
    try:
        out = value.lower()
    except AttributeError:
        out = value
    return out


def compare_game_items(item1: GameItem, item2: GameItem, sort_col: int) -> int:
    """Compare two GameItem objects for sorting."""
    value1 = get_column_value(item1, sort_col)
    value2 = get_column_value(item2, sort_col)
    if value1 is None and value2 is None:
        value1 = value2 = 0
    elif value1 is None:
        value1 = type(value2)()
    elif value2 is None:
        value2 = type(value1)()
    value1 = try_lower(value1)
    value2 = try_lower(value2)
    diff = -1 if value1 < value2 else 0 if value1 == value2 else 1
    if diff == 0:
        value1 = try_lower(item1.sortname)
        value2 = try_lower(item2.sortname)
        try:
            diff = -1 if value1 < value2 else 0 if value1 == value2 else 1
        except TypeError:
            diff = 0
    if diff == 0:
        value1 = try_lower(item1.runner_human_name)
        value2 = try_lower(item2.runner_human_name)
    try:
        return -1 if value1 < value2 else 0 if value1 == value2 else 1
    except TypeError:
        return 0


def sort_func(model, row1, row2, sort_col):
    """Sorting function for the game store.

    Supports legacy test models that pass row indices, and GameItem instances.
    """
    if isinstance(row1, GameItem) and isinstance(row2, GameItem):
        return compare_game_items(row1, row2, sort_col)

    value1 = model.get_value(row1, sort_col)
    value2 = model.get_value(row2, sort_col)
    if value1 is None and value2 is None:
        value1 = value2 = 0
    elif value1 is None:
        value1 = type(value2)()
    elif value2 is None:
        value2 = type(value1)()
    value1 = try_lower(value1)
    value2 = try_lower(value2)
    diff = -1 if value1 < value2 else 0 if value1 == value2 else 1
    if diff == 0:
        value1 = try_lower(model.get_value(row1, COL_SORTNAME))
        value2 = try_lower(model.get_value(row2, COL_SORTNAME))
        try:
            diff = -1 if value1 < value2 else 0 if value1 == value2 else 1
        except TypeError:
            diff = 0
    if diff == 0:
        value1 = try_lower(model.get_value(row1, COL_RUNNER_HUMAN_NAME))
        value2 = try_lower(model.get_value(row2, COL_RUNNER_HUMAN_NAME))
    try:
        return -1 if value1 < value2 else 0 if value1 == value2 else 1
    except TypeError:
        return 0


class GameRow:
    """Compatibility wrapper exposing list-store row semantics."""

    def __init__(self, item: GameItem, path: Gtk.TreePath):
        self.item = item
        self.path = path

    def __getitem__(self, index: int):
        return get_column_value(self.item, index)


class GameStore(GObject.Object):
    def __init__(self, service: "BaseService | None", service_media: "ServiceMedia") -> None:
        super().__init__()
        self.service = service
        self.service_media = service_media
        self._items_by_id: dict[str, GameItem] = {}
        self._sort_column = COL_SORTNAME
        self._sort_ascending = True

        self._list_store = Gio.ListStore.new(GameItem)
        self._sorter = Gtk.CustomSorter.new(self._compare_for_sorter)
        self.store = Gtk.SortListModel(model=self._list_store, sorter=self._sorter)

    def _compare_for_sorter(self, item1, item2, _user_data):
        result = compare_game_items(item1, item2, self._sort_column)
        if not self._sort_ascending:
            result = -result
        return result

    def set_sort_column(self, sort_column: int, ascending: bool = True) -> None:
        """Set the active sort column for the store model."""
        if self._sort_column != sort_column or self._sort_ascending != ascending:
            self._sort_column = sort_column
            self._sort_ascending = ascending
            self._sorter.changed()

    def get_sort_column(self) -> tuple[int, bool]:
        return self._sort_column, self._sort_ascending

    def _find_store_position(self, item: GameItem) -> int | None:
        for index in range(self._list_store.get_n_items()):
            if self._list_store.get_item(index) == item:
                return index
        return None

    def _find_sorted_position(self, item: GameItem) -> int | None:
        for index in range(self.store.get_n_items()):
            if self.store.get_item(index) == item:
                return index
        return None

    def get_path_by_id(self, game_id):
        """Return the TreePath for a game ID, or None."""
        if not game_id:
            return None
        item = self._items_by_id.get(str(game_id))
        if item is None:
            return None
        position = self._find_sorted_position(item)
        if position is None:
            return None
        return Gtk.TreePath((position,))

    def get_row_by_id(self, game_id, filtered=False):  # pylint: disable=unused-argument
        if not game_id:
            return None
        item = self._items_by_id.get(str(game_id))
        if item is None:
            return None
        path = self.get_path_by_id(game_id)
        if path is None:
            return None
        return GameRow(item, path)

    def remove_game(self, game_id):
        """Remove a game from the view."""
        item = self._items_by_id.pop(str(game_id), None)
        if item is None:
            return
        position = self._find_store_position(item)
        if position is not None:
            self._list_store.remove(position)

    def update(self, db_game: dict) -> set[int] | None:
        """Update game information.

        Return the indices of the row that were updated, or an empty set if no change
        was made, or None if the game could not be found.
        """
        store_item = StoreItem(db_game, self.service, self.service_media)
        row = self.get_row_by_id(store_item.id)
        if not row and "service_id" in db_game:
            row = self.get_row_by_id(db_game["service_id"])
        if not row:
            return None

        old_id = row.item.id
        changed_indices = row.item.update_from_store_item(store_item)

        new_id = store_item.id
        if old_id != new_id:
            self._items_by_id.pop(old_id, None)
            self._items_by_id[new_id] = row.item

        if changed_indices:
            self._sorter.changed()
        return changed_indices

    update_game = update

    def add_game(self, db_game):
        """Add a game to the store"""
        store_item = StoreItem(db_game, self.service, self.service_media)
        self.add_item(store_item)

    def add_item(self, store_item):
        item = GameItem.from_store_item(store_item)
        self._items_by_id[store_item.id] = item
        self._list_store.append(item)

    def add_preloaded_games(self, db_games, service_id):
        """Add games to the store, but preload their installed-game data
        all at once, for faster database access. This should be used if all or almost all
        games are being loaded."""

        installed_db_games = {}
        if service_id and db_games:
            installed_db_games = get_all_installed_game_for_service(service_id)

        for db_game in db_games:
            if installed_db_games is not None and "appid" in db_game:
                appid = db_game["appid"]
                store_item = StoreItem(db_game, self.service, self.service_media)
                store_item.apply_installed_game_data(installed_db_games.get(appid))
                self.add_item(store_item)
            else:
                self.add_game(db_game)
