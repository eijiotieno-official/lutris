"""AppIndicator/AyatanaAppIndicator based tray icon"""

from gettext import gettext as _

import gi
from gi.repository import Gtk

from lutris.database import categories
from lutris.database.games import get_games
from lutris.game import Game

try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppIndicator

    APP_INDICATOR_SUPPORTED = True
except (ImportError, ValueError):
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator

        APP_INDICATOR_SUPPORTED = True
    except (ImportError, ValueError):
        APP_INDICATOR_SUPPORTED = False


def supports_status_icon() -> bool:
    return APP_INDICATOR_SUPPORTED


class LutrisStatusIcon:
    """Tray icon proxy using AppIndicator when available."""

    def __init__(self, application):
        self.application = application
        self.indicator = None
        self.menu = None
        self.present_menu = None

        if APP_INDICATOR_SUPPORTED:
            self.menu = self._get_menu()
            self.indicator = AppIndicator.Indicator.new(
                "net.lutris.Lutris", "net.lutris.Lutris", AppIndicator.IndicatorCategory.APPLICATION_STATUS
            )
            self.indicator.set_menu(self.menu)
            self.set_visible(True)

    def is_visible(self):
        """Whether the icon is visible"""
        if self.indicator:
            return self.indicator.get_status() != AppIndicator.IndicatorStatus.PASSIVE
        return False

    def set_visible(self, value):
        """Set the visibility of the icon"""
        if self.indicator:
            if value:
                visible = AppIndicator.IndicatorStatus.ACTIVE
            else:
                visible = AppIndicator.IndicatorStatus.PASSIVE
            self.indicator.set_status(visible)

    def _get_menu(self):
        """Instantiates the menu attached to the tray icon"""
        menu = Gtk.Menu()
        installed_games = self._get_installed_games()
        number_of_games_in_menu = 10
        for game in installed_games[:number_of_games_in_menu]:
            menu.append(self._make_menu_item_for_game(game))
        menu.append(Gtk.SeparatorMenuItem())

        self.present_menu = Gtk.MenuItem()
        present_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        present_box.append(Gtk.Image.new_from_icon_name("net.lutris.Lutris"))
        present_box.append(Gtk.Label(label=_("Show Lutris")))
        self.present_menu.set_child(present_box)
        self.present_menu.connect("activate", self.on_activate)
        menu.append(self.present_menu)

        quit_menu = Gtk.MenuItem(label=_("Quit"))
        quit_menu.connect("activate", self.on_quit_application)
        menu.append(quit_menu)
        return menu

    def update_present_menu(self):
        app_window = self.application.window
        if app_window and self.present_menu:
            label = _("Hide Lutris") if app_window.get_visible() else _("Show Lutris")
            child = self.present_menu.get_child()
            if isinstance(child, Gtk.Box):
                for widget in child:
                    if isinstance(widget, Gtk.Label):
                        widget.set_label(label)
                        break

    def on_activate(self, _status_icon, _event=None):
        """Callback to show or hide the window"""
        app_window = self.application.window
        if app_window.get_visible():
            windows = Gtk.Window.list_toplevels()
            for w in windows:
                if w.get_visible() and w.get_transient_for() == app_window:
                    return
            app_window.hide()
        else:
            app_window.show()

    def on_quit_application(self, _widget):
        """Callback to quit the program"""
        self.application.quit()

    def _make_menu_item_for_game(self, game):
        menu_item = Gtk.MenuItem(label=game["name"])
        menu_item.connect("activate", self.on_game_selected, game["id"])
        return menu_item

    @staticmethod
    def _get_installed_games():
        """Adds installed games in order of last use"""
        installed_games = get_games(filters={"installed": 1})
        hidden_game_ids = categories.get_game_ids_for_categories([".hidden"])
        installed_games = [g for g in installed_games if str(g.get("id")) not in hidden_game_ids]
        installed_games.sort(
            key=lambda game: max(game["lastplayed"] or 0, game["installed_at"] or 0),
            reverse=True,
        )
        return installed_games

    def on_game_selected(self, _widget, game_id):
        launch_ui_delegate = self.application.get_launch_ui_delegate()
        Game(game_id).launch(launch_ui_delegate)
