"""Grid view for the main window"""

# pylint: disable=no-member
from gi.repository import Gtk

from lutris.gui.views.base import GameView
from lutris.gui.views.game_item import GameItem
from lutris.gui.widgets.game_grid_cell import GameGridCell, GameMediaPresentation
from lutris.util.log import logger


class GameGridView(Gtk.GridView, GameView):
    __gsignals__ = GameView.__gsignals__

    min_width = 70  # Minimum width for a cell

    def __init__(self, store, hide_text=False):
        super().__init__()
        GameView.__init__(self)

        self._show_badges = True
        self._hide_text = hide_text
        self._selection_model = None
        self._selection_handler_id = None
        self._label_width = self.min_width
        self.presentation = GameMediaPresentation()
        self.image_renderer = self.presentation

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        factory.connect("unbind", self._on_factory_unbind)
        self.set_factory(factory)

        self.set_enable_rubberband(True)
        self.set_max_columns(0)
        self.set_single_click_activate(False)
        self.set_tab_behavior(Gtk.ListTabBehavior.ITEM)

        self.set_game_store(store)

        self.connect_signals()
        self.connect("activate", self.on_item_activated)
        self.connect("notify::style", self.on_style_updated)

    def _on_factory_setup(self, _factory, list_item):
        cell = GameGridCell(self.presentation, show_label=not self._hide_text)
        list_item.set_child(cell)

    def _on_factory_bind(self, _factory, list_item):
        item = list_item.get_item()
        cell = list_item.get_child()
        if isinstance(item, GameItem) and isinstance(cell, GameGridCell):
            cell.set_game_item(item)
            if not self._hide_text:
                cell.set_label_width(self._label_width)

    def _on_factory_unbind(self, _factory, list_item):
        cell = list_item.get_child()
        if isinstance(cell, GameGridCell):
            cell.set_game_item(None)

    def set_game_store(self, game_store):
        super().set_game_store(game_store)
        self.model = game_store.store
        if self._selection_model and self._selection_handler_id:
            self._selection_model.disconnect(self._selection_handler_id)
        self._selection_model = Gtk.MultiSelection.new(self.model)
        self.set_model(self._selection_model)
        self._selection_handler_id = self._selection_model.connect("selection-changed", self._on_selection_changed)

        size = game_store.service_media.size
        self.presentation.set_expected_size(size[0], size[1])
        if not self._hide_text:
            self._label_width = max(size[0], self.min_width)

    @property
    def show_badges(self):
        return self._show_badges

    @show_badges.setter
    def show_badges(self, value):
        if self._show_badges != value:
            self._show_badges = value
            self.presentation.show_badges = value
            self.queue_draw()

    def get_path_at(self, x, y):
        picked = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        while picked and picked != self:
            if isinstance(picked, Gtk.ListItem):
                position = picked.get_position()
                if position != Gtk.INVALID_LIST_POSITION:
                    return Gtk.TreePath((position,))
            picked = picked.get_parent()
        return None

    def set_selected(self, paths, scroll_into_view=False):
        if not self._selection_model:
            return
        self._selection_model.unselect_all()

        for idx, path in enumerate(paths):
            position = path.get_indices()[0]
            mode = Gtk.SelectionMode.ADD if idx else Gtk.SelectionMode.DEFAULT
            self._selection_model.select_item(position, mode)
            if scroll_into_view and idx == 0:
                self.scroll_to(position, Gtk.ListScrollFlags.NONE, 0.0, 0.0)

    def get_selected(self):
        """Return list of all selected items"""
        if not self._selection_model:
            return []
        selection = self._selection_model.get_selection()
        paths = []
        position = 0
        while True:
            position = selection.get_nth(position)
            if position == Gtk.INVALID_LIST_POSITION:
                break
            paths.append(Gtk.TreePath((position,)))
            position += 1
        return paths

    def select_path(self, path):
        if self._selection_model:
            self._selection_model.select_item(path.get_indices()[0], Gtk.SelectionMode.DEFAULT)

    def set_cursor(self, path, column=None, start_editing=False):  # pylint: disable=unused-argument
        self.set_selected([path], scroll_into_view=True)

    def get_game_id_for_path(self, path):
        position = path.get_indices()[0]
        item = self.model.get_item(position)
        return item.id if item else None

    def get_path_for_game_id(self, game_id):
        if self.game_store:
            return self.game_store.get_path_by_id(game_id)
        return None

    def on_item_activated(self, _view, position):
        """Handles double clicks"""
        path = Gtk.TreePath((position,))
        selected_id = self.get_game_id_for_path(path)
        if selected_id:
            logger.debug("Item activated: %s", selected_id)
            self.emit("game-activated", selected_id)

    def _on_selection_changed(self, *_args):
        self.emit("game-selected", self.get_selected())

    def on_style_updated(self, _widget):
        self.queue_draw()

    def get_toplevel(self):
        return self.get_root()
