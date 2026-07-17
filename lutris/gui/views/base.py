import re
import time

from gi.repository import Gdk, Gio, GObject, Gtk

from lutris.database.games import get_game_for_service
from lutris.database.services import ServiceGameCollection
from lutris.game import GAME_START, Game
from lutris.game_actions import GameActions, get_game_actions
from lutris.gui.widgets import EMPTY_NOTIFICATION_REGISTRATION
from lutris.gui.widgets.utils import MEDIA_CACHE_INVALIDATED, get_application
from lutris.util.jobs import schedule_repeating_at_idle
from lutris.util.log import logger
from lutris.util.path_cache import MISSING_GAMES


class GameView:
    # pylint: disable=no-member
    __gsignals__ = {
        "game-selected": (GObject.SIGNAL_RUN_FIRST, None, (object,)),
        "game-activated": (GObject.SIGNAL_RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        self.game_store = None
        self.service = None
        self.service_media = None
        self.cache_notification_registration = EMPTY_NOTIFICATION_REGISTRATION
        self.missing_games_updated_registration = EMPTY_NOTIFICATION_REGISTRATION
        self.game_start_registration = EMPTY_NOTIFICATION_REGISTRATION
        self.image_renderer = None
        self._context_action_group = None
        self._context_popover = None
        self._context_callbacks = {}

    def connect_signals(self):
        """Signal handlers common to all views"""
        self.cache_notification_registration = MEDIA_CACHE_INVALIDATED.register(self.on_media_cache_invalidated)
        self.missing_games_updated_registration = MISSING_GAMES.updated.register(self.on_missing_games_updated)
        self.game_start_registration = GAME_START.register(self.on_game_start)

        self.connect("root", self._on_root_changed)

        click_controller = Gtk.GestureClick()
        click_controller.set_button(Gdk.BUTTON_SECONDARY)
        click_controller.connect("pressed", self._on_secondary_click)
        self.add_controller(click_controller)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self.handle_key_press)
        self.add_controller(key_controller)

    def _on_root_changed(self, widget):
        if widget.get_root() is None:
            self.on_destroy(widget)

    def set_game_store(self, game_store):
        self.game_store = game_store
        self.service = game_store.service
        self.service_media = game_store.service_media

        if self.image_renderer:
            self.image_renderer.service = self.service

    def on_media_cache_invalidated(self):
        self.queue_draw()

    def on_missing_games_updated(self):
        if self.image_renderer and self.image_renderer.show_badges:
            self.queue_draw()

    def on_destroy(self, _widget) -> None:
        self.cache_notification_registration.unregister()
        self.missing_games_updated_registration.unregister()
        self.game_start_registration.unregister()
        self._clear_context_actions()

    def _clear_context_actions(self):
        if self._context_action_group is not None:
            self.insert_action_group("gameviewctx", None)
            self._context_action_group = None
        self._context_callbacks.clear()
        self._context_popover = None

    def _on_secondary_click(self, gesture, _n_press, x, y):
        if gesture.get_current_button() != Gdk.BUTTON_SECONDARY:
            return
        self.popup_contextual_menu(x, y)

    def popup_contextual_menu(self, x, y):
        """Contextual menu."""
        current_path = self.get_path_at(x, y)
        if current_path:
            selection = self.get_selected() or []
            if current_path not in selection:
                selection = [current_path]
                self.set_selected(selection)

            game_actions = self.get_game_actions_for_paths(selection)
            self._show_context_menu(game_actions, x, y)
            return True
        return False

    def _show_context_menu(self, game_actions: GameActions, x: float, y: float):
        self._clear_context_actions()

        entries = game_actions.get_game_actions()
        displayed = game_actions.get_displayed_entries()
        visible_entries = []
        for entry in entries:
            action_id, label, callback = entry
            if label == "-":
                visible_entries.append(entry)
                continue
            if displayed.get(action_id, True):
                visible_entries.append(entry)

        if not visible_entries:
            return

        menu = Gio.Menu()
        self._context_action_group = Gio.SimpleActionGroup()
        self._context_callbacks = {}

        section = Gio.Menu()
        for action_id, label, callback in visible_entries:
            if label == "-":
                menu.append_section(None, section)
                section = Gio.Menu()
                continue

            safe_action_id = re.sub(r"[^a-zA-Z0-9_-]", "_", action_id or "action")
            action = Gio.SimpleAction.new(safe_action_id, None)
            action.connect("activate", self._on_context_action_activated, safe_action_id)
            self._context_action_group.add_action(action)
            self._context_callbacks[safe_action_id] = callback
            section.append(label, "gameviewctx.%s" % safe_action_id)

        if section.get_n_items() > 0:
            menu.append_section(None, section)

        self.insert_action_group("gameviewctx", self._context_action_group)

        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(self)
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        popover.connect("closed", self._on_context_popover_closed)
        self._context_popover = popover
        popover.popup()

    def _on_context_action_activated(self, _action, _parameter, action_id):
        callback = self._context_callbacks.get(action_id)
        if callback:
            callback()

    def _on_context_popover_closed(self, _popover):
        self._clear_context_actions()

    def get_selected_game_actions(self) -> GameActions:
        return self.get_game_actions_for_paths(self.get_selected() or [])

    def get_game_actions_for_paths(self, paths) -> GameActions:
        from lutris.gui.lutriswindow import LutrisWindow  # avoid circular import at module level

        game_ids = [self.get_game_id_for_path(path) for path in paths]
        games = self._get_games_by_ids(game_ids)

        window = self.get_toplevel()
        if not isinstance(window, LutrisWindow):
            raise TypeError("GameView must be contained in a LutrisWindow, not %s" % type(window).__name__)
        return get_game_actions(games, window=window)

    def _get_games_by_ids(self, game_ids: list[str]) -> list[Game]:
        """Resolves a list of game-ids to a list of game objects,
        looking up running games, service games and all that."""

        def _get_game_by_id(id_to_find: str) -> Game:
            application = get_application()
            return application.get_game_by_id(id_to_find) if application else Game(id_to_find)

        games = []
        for game_id in game_ids:
            if self.service:
                db_game = get_game_for_service(self.service.id, game_id)

                if db_game:
                    if db_game["id"]:
                        games.append(_get_game_by_id(db_game["id"]))
                else:
                    service_game = ServiceGameCollection.get_game(self.service.id, game_id)
                    if service_game:
                        games.append(Game.create_empty_service_game(service_game, self.service))
            elif game_id:
                games.append(_get_game_by_id(game_id))

        return games

    def get_selected_game_id(self):
        """Returns the ID of the selected game, if there is exactly one- or
        None if there is no selection or a multiple-selection."""
        selected = self.get_selected() or []
        if len(selected) == 1:
            return self.get_game_id_for_path(selected[0])
        return None

    def handle_key_press(self, _controller, keyval, _keycode, _state):
        try:
            if keyval == Gdk.KEY_Delete:
                game_actions = self.get_selected_game_actions()
                if game_actions.is_game_removable:
                    game_actions.on_remove_game(self)
            elif keyval == Gdk.KEY_Break:
                game_actions = self.get_selected_game_actions()
                if game_actions.is_game_running:
                    game_actions.on_game_stop(self)
        except Exception as ex:
            logger.exception("Unable to handle key press: %s", ex)
        return False

    def get_toplevel(self):
        root = self.get_root()
        if isinstance(root, Gtk.Window):
            return root
        return root

    def get_selected(self):
        return []

    def set_selected(self, paths, scroll_into_view=False):
        raise NotImplementedError()

    def get_game_id_for_path(self, path):
        raise NotImplementedError()

    def get_path_for_game_id(self, game_id):
        raise NotImplementedError()

    def on_game_start(self, game: Game) -> None:
        """On game start, we trigger an animation to show the game is starting; it runs at least
        one cycle, but continues until the game exits the STATE_LAUNCHING state."""

        start_time = time.monotonic()
        cycle_time = 0.375
        max_indent = 0.1
        toplevel = self.get_toplevel()
        paused = False

        def is_modally_blocked():
            application = get_application()
            if not application:
                return False
            for window in application.get_windows():
                if window != toplevel and isinstance(window, Gtk.Window):
                    if window.is_modal() and window.get_transient_for() == toplevel:
                        return True
            return False

        def animate():
            nonlocal paused, start_time

            now = time.monotonic()
            elapsed = now - start_time

            if elapsed > cycle_time:
                if game.state != game.STATE_LAUNCHING:
                    if self.image_renderer.inset_game(game.id, 0.0):
                        self.queue_draw()
                    return False

                start_time = now
                paused = is_modally_blocked()

            cycle = elapsed % cycle_time

            if cycle > cycle_time / 2:
                cycle = cycle_time - cycle

            if paused:
                fraction = 0.0
            else:
                fraction = max_indent * (cycle * 2 / cycle_time)

            if self.image_renderer.inset_game(game.id, fraction):
                self.queue_draw()

            return True

        if self.image_renderer:
            schedule_repeating_at_idle(animate, interval_seconds=0.025)
