"""ColumnView based game list"""

from gettext import gettext as _

# pylint: disable=no-member
from gi.repository import Gdk, Gtk, Pango

from lutris import settings
from lutris.gui.views import (
    COL_INSTALLED_AT,
    COL_INSTALLED_AT_TEXT,
    COL_LASTPLAYED,
    COL_LASTPLAYED_TEXT,
    COL_NAME,
    COL_PLATFORM,
    COL_PLAYTIME,
    COL_PLAYTIME_TEXT,
    COL_RUNNER_HUMAN_NAME,
    COL_SORTNAME,
    COL_YEAR,
    COLUMN_NAMES,
)
from lutris.gui.views.base import GameView
from lutris.gui.views.game_item import GameItem, get_column_value
from lutris.gui.views.store import compare_game_items
from lutris.gui.widgets.game_grid_cell import GameListMediaCell, GameMediaPresentation


class GameListView(Gtk.ColumnView, GameView):
    """Show the main list of games."""

    __gsignals__ = GameView.__gsignals__

    def __init__(self, store):
        super().__init__()
        GameView.__init__(self)

        self._selection_model = None
        self._selection_handler_id = None
        self._columns: list[Gtk.ColumnViewColumn] = []
        self.presentation = GameMediaPresentation()
        self.image_renderer = self.presentation
        self.media_column = None

        self.set_show_row_separators(True)
        self.set_reorderable(True)

        if settings.SHOW_MEDIA:
            self.media_column = self._add_media_column()

        self._add_text_column(_("Name"), COL_NAME, 200, always_visible=True, sort_id=COL_SORTNAME)
        self._add_text_column(_("Year"), COL_YEAR, 60)
        self._add_text_column(_("Runner"), COL_RUNNER_HUMAN_NAME, 120)
        self._add_text_column(_("Platform"), COL_PLATFORM, 120)
        self._add_text_column(_("Last Played"), COL_LASTPLAYED_TEXT, 120, sort_id=COL_LASTPLAYED)
        self._add_text_column(_("Play Time"), COL_PLAYTIME_TEXT, 100, sort_id=COL_PLAYTIME)
        self._add_text_column(_("Installed At"), COL_INSTALLED_AT_TEXT, 120, sort_id=COL_INSTALLED_AT)

        header_gesture = Gtk.GestureClick()
        header_gesture.set_button(Gdk.BUTTON_SECONDARY)
        header_gesture.connect("pressed", self._on_header_button_pressed)
        self.add_controller(header_gesture)

        self.set_game_store(store)

        self.connect_signals()
        self.connect("activate", self.on_row_activated)

    def set_game_store(self, game_store):
        super().set_game_store(game_store)
        self.model = game_store.store
        if self._selection_model and self._selection_handler_id:
            self._selection_model.disconnect(self._selection_handler_id)
        self._selection_model = Gtk.MultiSelection.new(self.model)
        self.set_model(self._selection_model)
        self._selection_handler_id = self._selection_model.connect("selection-changed", self._on_selection_changed)

        if self.media_column:
            size = game_store.service_media.size
            self.media_column.set_fixed_width(size[0])

    def _make_text_factory(self, column_id):
        factory = Gtk.SignalListItemFactory()

        def on_setup(_factory, list_item):
            label = Gtk.Label(xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_margin_start(10)
            label.set_margin_end(10)
            list_item.set_child(label)

        def on_bind(_factory, list_item):
            item = list_item.get_item()
            label = list_item.get_child()
            if isinstance(item, GameItem) and isinstance(label, Gtk.Label):
                label.set_markup(get_column_value(item, column_id))

        factory.connect("setup", on_setup)
        factory.connect("bind", on_bind)
        return factory

    def _make_media_factory(self):
        factory = Gtk.SignalListItemFactory()

        def on_setup(_factory, list_item):
            list_item.set_child(GameListMediaCell(self.presentation))

        def on_bind(_factory, list_item):
            item = list_item.get_item()
            cell = list_item.get_child()
            if isinstance(item, GameItem) and isinstance(cell, GameListMediaCell):
                cell.set_game_item(item)

        factory.connect("setup", on_setup)
        factory.connect("bind", on_bind)
        return factory

    def _make_column_sorter(self, sort_column: int):
        def compare(item1, item2, _user_data):
            return compare_game_items(item1, item2, sort_column)

        return Gtk.CustomSorter.new(compare)

    def _add_media_column(self):
        column = Gtk.ColumnViewColumn(title="")
        column.set_factory(self._make_media_factory())
        column.set_resizable(True)
        column.set_sorter(None)
        self.append_column(column)
        self._columns.append(column)
        return column

    def _add_text_column(
        self,
        header,
        column_id,
        default_width,
        always_visible=False,
        sort_id=None,
    ):
        column = Gtk.ColumnViewColumn(title=header)
        column.set_factory(self._make_text_factory(column_id))
        column.set_resizable(True)
        column.set_expand(True)

        sort_column = column_id if sort_id is None else sort_id
        column.set_sorter(self._make_column_sorter(sort_column))

        setting_key = COLUMN_NAMES[column_id]

        width = settings.read_setting("%s_column_width" % setting_key, section="list view")
        is_visible = settings.read_setting("%s_visible" % setting_key, section="list view")
        column.set_fixed_width(int(width) if width else default_width)
        column.set_visible(is_visible == "True" or always_visible if is_visible else True)

        self.append_column(column)
        self._columns.append(column)
        column.connect("notify::fixed-width", self.on_column_width_changed, column)
        return column

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
            return None
        selection = self._selection_model.get_selection()
        if selection.get_size() == 0:
            return None
        paths = []
        position = 0
        while True:
            position = selection.get_nth(position)
            if position == Gtk.INVALID_LIST_POSITION:
                break
            paths.append(Gtk.TreePath((position,)))
            position += 1
        return paths

    def get_game_id_for_path(self, path):
        position = path.get_indices()[0]
        item = self.model.get_item(position)
        return item.id if item else None

    def get_path_for_game_id(self, game_id):
        if self.game_store:
            return self.game_store.get_path_by_id(game_id)
        return None

    def set_selected_game(self, game_id):
        row = self.game_store.get_row_by_id(game_id, filtered=True)
        if row:
            self.set_cursor(row.path)

    def select_path(self, path):
        if self._selection_model:
            self._selection_model.select_item(path.get_indices()[0], Gtk.SelectionMode.DEFAULT)

    def set_cursor(self, path, column=None, start_editing=False):  # pylint: disable=unused-argument
        self.set_selected([path], scroll_into_view=True)

    def on_row_activated(self, _view, position):
        """Handles double clicks"""
        selected_id = self.get_game_id_for_path(Gtk.TreePath((position,)))
        if selected_id:
            self.emit("game-activated", selected_id)

    def _on_selection_changed(self, *_args):
        self.emit("game-selected", self.get_selected())

    def _on_header_button_pressed(self, gesture, _n_press, x, y):
        if gesture.get_current_button() != Gdk.BUTTON_SECONDARY:
            return
        if self.get_path_at(x, y) is not None:
            return
        menu = GameListColumnToggleMenu(self._columns)
        menu.set_parent(self)
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        menu.set_pointing_to(rect)
        menu.popup()

    @staticmethod
    def on_column_width_changed(column, _pspec, user_data):
        col = user_data or column
        col_name = col.get_title()
        if col_name:
            settings.write_setting(
                col_name.replace(" ", "") + "_column_width",
                col.get_fixed_width(),
                "list view",
            )

    def get_toplevel(self):
        return self.get_root()


class GameListColumnToggleMenu(Gtk.Popover):
    def __init__(self, columns):
        super().__init__()
        self.columns = columns
        self.column_map = {}

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(box)
        self.create_menuitems(box)

    def create_menuitems(self, box):
        for column in self.columns:
            title = column.get_title()
            if title == "":
                continue
            checkbox = Gtk.CheckButton(label=title)
            checkbox.set_active(column.get_visible())
            checkbox.set_margin_start(12)
            checkbox.set_margin_end(12)
            checkbox.set_margin_top(6)
            checkbox.set_margin_bottom(6)
            if title == _("Name"):
                checkbox.set_sensitive(False)
            else:
                checkbox.connect("toggled", self.on_toggle_column)
            self.column_map[checkbox] = column
            box.append(checkbox)

    def on_toggle_column(self, check_button):
        column = self.column_map[check_button]
        is_visible = check_button.get_active()
        column.set_visible(is_visible)
        settings.write_setting(
            column.get_title().replace(" ", "") + "_visible",
            str(is_visible),
            "list view",
        )
