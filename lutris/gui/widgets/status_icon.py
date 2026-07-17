"""AppIndicator/AyatanaAppIndicator based tray icon"""

from gettext import gettext as _

import gi
from gi.repository import Gio, Gtk

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
        self.menu_model = None
        self.present_action = None

        if APP_INDICATOR_SUPPORTED:
            self.menu_model = self._build_menu_model()
            self.indicator = AppIndicator.Indicator.new(
                "net.lutris.Lutris", "net.lutris.Lutris", AppIndicator.IndicatorCategory.APPLICATION_STATUS
            )
            if hasattr(self.indicator, "set_menu_model"):
                self.indicator.set_menu_model(self.menu_model)
            else:
                popover_menu = Gtk.PopoverMenu.new_from_model(self.menu_model)
                self.indicator.set_menu(popover_menu)
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

    def _build_menu_model(self) -> Gio.Menu:
        """Builds the menu model attached to the tray icon."""
        menu = Gio.Menu()
        installed_games = self._get_installed_games()
        games_section = Gio.Menu()
        for index, game in enumerate(installed_games[:10]):
            games_section.append(f"game-{index}", game["name"])
        if installed_games:
            menu.append_section(None, games_section)

        window_section = Gio.Menu()
        window_section.append("present", _("Show Lutris"))
        window_section.append("quit", _("Quit"))
        menu.append_section(None, window_section)

        action_group = Gio.SimpleActionGroup()
        for index, game in enumerate(installed_games[:10]):
            action = Gio.SimpleAction.new(f"game-{index}", None)
            action.connect("activate", self._on_game_action, game["id"])
            action_group.add_action(action)

        self.present_action = Gio.SimpleAction.new("present", None)
        self.present_action.connect("activate", self.on_activate)
        action_group.add_action(self.present_action)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self.on_quit_application)
        action_group.add_action(quit_action)

        self._action_group = action_group
        return menu

    def _on_game_action(self, _action, _parameter, game_id):
        launch_ui_delegate = self.application.get_launch_ui_delegate()
        Game(game_id).launch(launch_ui_delegate)

    def update_present_menu(self):
        app_window = self.application.window
        if app_window and self.present_action and self.menu_model:
            label = _("Hide Lutris") if app_window.get_visible() else _("Show Lutris")
            # Rebuild menu to update the present label
            if self.indicator and hasattr(self.indicator, "set_menu_model"):
                self.menu_model = self._build_menu_model()
                self.indicator.set_menu_model(self.menu_model)

    def on_activate(self, *_args):
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

    def on_quit_application(self, *_args):
        """Callback to quit the program"""
        self.application.quit()

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
