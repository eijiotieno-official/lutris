"""Shared config dialog stuff"""

# pylint: disable=not-an-iterable
from collections.abc import Callable
from gettext import gettext as _
from typing import TYPE_CHECKING

from gi.repository import Adw, Gtk

from lutris import settings
from lutris.config import LutrisConfig, make_game_config_id, rename_config
from lutris.game import Game
from lutris.gui.config import DIALOG_HEIGHT, DIALOG_WIDTH
from lutris.gui.config.boxes import GameBox, RunnerBox, SystemConfigBox
from lutris.gui.config.game_info_box import GameInfoBox
from lutris.gui.config.widget_generator import WidgetWarningMessageBox
from lutris.gui.dialogs import DirectoryDialog, ErrorDialog, QuestionDialog, SavableModelessDialog, display_error
from lutris.gui.dialogs.delegates import DialogInstallUIDelegate
from lutris.gui.dialogs.move_game import MoveDialog
from lutris.gui.widgets.notifications import send_notification
from lutris.runners import import_runner
from lutris.services.lutris import download_lutris_media
from lutris.util.jobs import AsyncCall
from lutris.util.log import logger
from lutris.util.strings import parse_playtime, slugify

if TYPE_CHECKING:
    from lutris.gui.config.boxes import ConfigBox


# pylint: disable=too-many-instance-attributes, no-member
class GameDialogCommon(SavableModelessDialog, DialogInstallUIDelegate):
    """Base class for config dialogs"""

    no_runner_label = _("Select a runner in the Game Info tab")

    def __init__(self, title: str, config_level: str, parent: Gtk.Widget | None = None):
        super().__init__(title, parent=parent, border_width=0)
        self.config_level = config_level
        self.set_default_size(DIALOG_WIDTH, DIALOG_HEIGHT)

        self.view_stack: Gtk.Stack = None
        self.view_switcher: Adw.ViewSwitcher = None

        self.info_box: GameInfoBox = None
        self.runner_box = None

        self.timer_id = None
        self.game: Game = None
        self.saved = None
        self.option_page_names: set[str] = set()
        self.searchable_page_names: set[str] = set()
        self.advanced_switch_widgets = []
        self.header_bar_widgets = []
        self.game_box = None
        self.system_box: SystemConfigBox = None
        self.runner_name = None
        self.lutris_config: LutrisConfig = None
        self.stack_page_generators: dict[str, Callable[[], None]] = {}
        self.stack_page_updaters: dict[str, Callable[[], None]] = {}

        self.build_header_bar()
        self.build_view_stack()

    @staticmethod
    def build_scrolled_window(widget: Gtk.Widget) -> Gtk.ScrolledWindow:
        scrolled_window = Gtk.ScrolledWindow(visible=True)
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_child(widget)
        return scrolled_window

    def build_view_stack(self) -> None:
        self.view_stack = Gtk.Stack(visible=True)
        self.view_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.view_stack.connect("notify::visible-child", self.on_stack_visible_child_changed)

        self.view_switcher = Adw.ViewSwitcher()
        self.view_switcher.set_stack(self.view_stack)
        self.view_switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)

        header_bar = self.get_header_bar()
        header_bar.set_title_widget(self.view_switcher)

        self.vbox.append(self.view_stack)

    def on_stack_visible_child_changed(self, _stack: Gtk.Stack, _pspec) -> None:
        page_name = self.view_stack.get_visible_child_name()
        if not page_name:
            return

        generator = self.stack_page_generators.get(page_name)
        if generator:
            generator()
            del self.stack_page_generators[page_name]
        else:
            updater = self.stack_page_updaters.get(page_name)
            if updater:
                updater()

        self.update_advanced_switch_visibility(page_name)
        self.update_search_entry_visibility(page_name)

    def build_notebook(self) -> None:
        """Backward-compatible alias for building the view stack."""
        pass

    def build_tabs(self) -> None:
        self.timer_id = None
        if self.config_level == "game":
            self._build_info_tab()
            self._build_game_tab()
        self._build_runner_tab()
        self._build_system_tab()

        current_page_name = self.view_stack.get_visible_child_name()
        if current_page_name:
            self.update_advanced_switch_visibility(current_page_name)
            self.update_search_entry_visibility(current_page_name)

    def set_header_bar_widgets_visibility(self, value: bool) -> None:
        for widget in self.header_bar_widgets:
            widget.set_visible(value)

    def update_advanced_switch_visibility(self, current_page_name: str) -> None:
        if self.view_stack:
            show_switch = current_page_name in self.option_page_names
            for widget in self.advanced_switch_widgets:
                widget.set_visible(show_switch)

    def update_search_entry_visibility(self, current_page_name: str) -> None:
        if self.view_stack:
            show_search = current_page_name in self.searchable_page_names
            self.set_search_entry_visibility(show_search)

    def set_search_entry_visibility(
        self, show_search: bool, placeholder_text: str | None = None, tooltip_markup: str | None = None
    ) -> None:
        header_bar = self.get_header_bar()
        if show_search and self.search_entry:
            header_bar.set_title_widget(self.search_entry)
            self.search_entry.set_placeholder_text(placeholder_text or self.get_search_entry_placeholder())
            self.search_entry.set_tooltip_markup(tooltip_markup)
        elif self.view_switcher:
            header_bar.set_title_widget(self.view_switcher)

    def get_search_entry_placeholder(self) -> str:
        if self.game and self.game.name:
            return _("Search %s options") % self.game.name
        return _("Search options")

    def _build_info_tab(self) -> None:
        self.info_box = GameInfoBox(parent_widget=self, game=self.game)
        info_sw = self.build_scrolled_window(self.info_box)
        page_name, _page_index = self._add_stack_page(info_sw, _("Game info"))
        self.option_page_names.add(page_name)

    def on_move_clicked(self, _button: Gtk.Button) -> None:
        game_directory = self.game.directory if self.game else ""
        new_location = DirectoryDialog("Select new location for the game", default_path=game_directory, parent=self)
        if not new_location.folder or new_location.folder == game_directory:
            return
        move_dialog = MoveDialog(self.game, new_location.folder, parent=self)
        move_dialog.connect("game-moved", self.on_game_moved)
        move_dialog.move()

    def on_game_moved(self, dialog: MoveDialog) -> None:
        new_directory = dialog.new_directory
        if new_directory:
            self.game = Game(self.game.id if self.game else None)
            self.lutris_config = self.game.config
            self._rebuild_tabs()
            if self.info_box.directory_entry:
                self.info_box.directory_entry.set_text(new_directory)
            send_notification("Finished moving game", "%s moved to %s" % (dialog.game, new_directory))
        else:
            send_notification("Failed to move game", "Lutris could not move %s" % dialog.game)

    def _build_game_tab(self) -> None:
        def is_searchable(game: Game) -> bool:
            return game.has_runner and len(game.runner.game_options) > 8

        def has_advanced(game: Game) -> bool:
            if game.has_runner:
                for opt in game.runner.game_options:
                    if opt.get("advanced"):
                        return True
            return False

        if self.game and self.runner_name:
            self.game.runner_name = self.runner_name
            self.game_box = self._build_options_tab(
                _("Game options"),
                lambda: GameBox(self.config_level, self.lutris_config, self.game),
                advanced=has_advanced(self.game),
                searchable=is_searchable(self.game),
            )
        elif self.runner_name:
            game = Game(None)
            game.runner_name = self.runner_name
            self.game_box = self._build_options_tab(
                _("Game options"),
                lambda: GameBox(self.config_level, self.lutris_config, game),
                advanced=has_advanced(game),
                searchable=is_searchable(game),
            )
        else:
            self._build_missing_options_tab(self.no_runner_label, _("Game options"))

    def _build_runner_tab(self) -> None:
        if self.runner_name:
            self.runner_box = self._build_options_tab(
                _("Runner options"), lambda: RunnerBox(self.config_level, self.lutris_config)
            )
        else:
            self._build_missing_options_tab(self.no_runner_label, _("Runner options"))

    def _build_system_tab(self) -> None:
        self.system_box = self._build_options_tab(
            _("System options"), lambda: SystemConfigBox(self.config_level, self.lutris_config)
        )

    def _build_options_tab(
        self,
        page_label: str,
        box_factory: Callable[[], "ConfigBox"],
        advanced: bool = True,
        searchable: bool = True,
    ) -> "ConfigBox":
        if not self.lutris_config:
            raise RuntimeError("Lutris config not loaded yet")
        config_box = box_factory()
        page_name, page_index = self._add_stack_page(self.build_scrolled_window(config_box), page_label)

        self.stack_page_updaters[page_name] = config_box.update_widgets

        if page_index == 0:
            config_box.generate_widgets()
        else:
            self.stack_page_generators[page_name] = config_box.generate_widgets

        if advanced:
            self.option_page_names.add(page_name)
        if searchable:
            self.searchable_page_names.add(page_name)
        return config_box

    def _get_first_page_name(self) -> str | None:
        if self.view_stack.get_n_pages() > 0:
            return self.view_stack.get_nth_page(0).get_name()
        return None

    def _build_missing_options_tab(self, missing_label: str, page_label: str) -> None:
        label = Gtk.Label(label=missing_label)
        page_name, _page_index = self._add_stack_page(label, page_label)
        self.option_page_names.add(page_name)

    def _add_stack_page(self, widget: Gtk.Widget, label: str) -> tuple[str, int]:
        page_index = self.view_stack.get_n_pages()
        page_name = "page-%d" % (page_index + 1)
        self.view_stack.add_titled(widget, page_name, label)
        return page_name, page_index

    def build_header_bar(self) -> None:
        self.search_entry = Gtk.SearchEntry(width_chars=30, placeholder_text=_("Search options"))
        self.search_entry.connect("search-changed", self.on_search_entry_changed)

        switch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5, visible=True)
        switch_box.set_tooltip_text(_("Show advanced options"))

        switch_label = Gtk.Label(label=_("Advanced"), visible=True)
        switch = Gtk.Switch(visible=True, valign=Gtk.Align.CENTER)
        switch.set_state(settings.read_setting("show_advanced_options") == "True")
        switch.connect("state-set", lambda _w, s: self.on_show_advanced_options_toggled(bool(s)))

        switch_box.append(switch_label)
        switch_box.append(switch)

        header_bar = self.get_header_bar()
        header_bar.pack_end(switch_box)

        self.advanced_switch_widgets = [switch_label, switch]
        self.header_bar_widgets = [self.cancel_button, self.save_button, switch_box]

        if self.view_stack:
            page_name = self.view_stack.get_visible_child_name()
            if page_name:
                self.update_advanced_switch_visibility(page_name)

    def on_search_entry_changed(self, entry: Gtk.Entry) -> None:
        text = entry.get_text().lower().strip()
        self._set_filter(text)

    def on_show_advanced_options_toggled(self, is_active: bool) -> None:
        settings.write_setting("show_advanced_options", is_active)
        self._set_advanced_options_visible(is_active)

    def _set_advanced_options_visible(self, value: bool) -> None:
        if self.info_box:
            self.info_box.advanced_visibility = value
        if self.system_box:
            self.system_box.advanced_visibility = value
        if self.runner_box:
            self.runner_box.advanced_visibility = value
        if self.game_box:
            self.game_box.advanced_visibility = value

    def _set_filter(self, value: str) -> None:
        if self.system_box:
            self.system_box.filter = value
        if self.runner_box:
            self.runner_box.filter = value
        if self.game_box:
            self.game_box.filter = value

    def on_runner_changed(self, widget: Gtk.ComboBox) -> None:
        new_runner_index = widget.get_active()
        game_info_box = self.info_box
        if game_info_box.runner_index and new_runner_index != game_info_box.runner_index:
            dlg = QuestionDialog(
                {
                    "parent": self,
                    "question": _(
                        "Are you sure you want to change the runner for this game ? "
                        "This will reset the full configuration for this game and "
                        "is not reversible."
                    ),
                    "title": _("Confirm runner change"),
                }
            )

            if dlg.result == Gtk.ResponseType.YES:
                self._switch_runner(widget, new_runner_index)
            else:
                widget.set_active(game_info_box.runner_index)
        else:
            self._switch_runner(widget, new_runner_index)

    def _switch_runner(self, widget: Gtk.ComboBox, new_runner_index: int) -> None:
        current_page_name = self.view_stack.get_visible_child_name()
        game_info_box = self.info_box
        game_info_box.runner_index = new_runner_index
        if new_runner_index == 0:
            logger.info("No runner selected, resetting configuration")
            self.runner_name = None
            self.lutris_config = None
        else:
            runner_name = widget.get_model()[new_runner_index][1]
            if runner_name == self.runner_name:
                logger.debug("Runner unchanged, not creating a new config")
                return
            logger.info("Creating new configuration with runner %s", runner_name)
            self.runner_name = runner_name
            self.lutris_config = LutrisConfig(runner_slug=self.runner_name, level="game")
        self._rebuild_tabs()
        if current_page_name:
            self.view_stack.set_visible_child_name(current_page_name)

    def _rebuild_tabs(self) -> None:
        while self.view_stack.get_n_pages() > 1:
            page = self.view_stack.get_nth_page(self.view_stack.get_n_pages() - 1)
            self.view_stack.remove(page.get_child())

        self.option_page_names = {name for name in self.option_page_names if name == "page-1"}
        self.searchable_page_names.clear()
        self.stack_page_generators.clear()
        self.stack_page_updaters = {
            name: updater for name, updater in self.stack_page_updaters.items() if name == "page-1"
        }
        self._build_game_tab()
        self._build_runner_tab()
        self._build_system_tab()

    def on_response(self, _widget: Gtk.Dialog, response: Gtk.ResponseType) -> None:
        if response in (Gtk.ResponseType.CANCEL, Gtk.ResponseType.DELETE_EVENT):
            if self.game:
                self.game.reload_config()
        super().on_response(_widget, response)

    def is_valid(self) -> bool:
        game_info_box = self.info_box
        if not self.runner_name:
            ErrorDialog(_("Runner not provided"), parent=self)
            return False
        if not game_info_box.name_entry.get_text():
            ErrorDialog(_("Please fill in the name"), parent=self)
            return False
        if self.runner_name == "steam" and not self.lutris_config.game_config.get("appid"):
            ErrorDialog(_("Steam AppID not provided"), parent=self)
            return False
        playtime_text = game_info_box.playtime_entry.get_text()
        if playtime_text and (not self.game or playtime_text != self.game.formatted_playtime):
            try:
                parse_playtime(playtime_text)
            except ValueError as ex:
                display_error(ex, parent=self)
                return False

        invalid_fields = []
        runner_class = import_runner(self.runner_name)
        runner_instance = runner_class()
        for config in ["game", "runner"]:
            for k, v in getattr(self.lutris_config, config + "_config").items():
                option = runner_instance.find_option(config + "_options", k)
                if option is None:
                    continue
                validator = option.get("validator")
                if validator is not None:
                    try:
                        res = validator(v)
                        logger.debug("%s validated successfully: %s", k, res)
                    except Exception:
                        invalid_fields.append(option.get("label"))
        if invalid_fields:
            ErrorDialog(_("The following fields have invalid values: ") + ", ".join(invalid_fields), parent=self)
            return False
        return True

    def on_save(self, _button: Gtk.Button) -> bool | None:
        if not self.is_valid():
            logger.warning(_("Current configuration is not valid, ignoring save request"))
            return None
        game_info_box = self.info_box
        name = game_info_box.name_entry.get_text()
        sortname = game_info_box.sortname_entry.get_text()

        if not game_info_box.slug:
            game_info_box.slug = slugify(name)
        if game_info_box.slug != game_info_box.initial_slug:
            AsyncCall(download_lutris_media, None, game_info_box.slug)
        if not self.game:
            self.game = Game()

        year = None
        if game_info_box.year_entry.get_text():
            year = int(game_info_box.year_entry.get_text())

        playtime = None
        playtime_text = game_info_box.playtime_entry.get_text()
        if playtime_text and playtime_text != self.game.formatted_playtime:
            playtime = parse_playtime(playtime_text)

        if not self.lutris_config.game_config_id:
            self.lutris_config.game_config_id = make_game_config_id(game_info_box.slug)

        self.game.name = name
        self.game.sortname = sortname
        self.game.slug = game_info_box.slug
        self.game.year = year
        if playtime:
            self.game.playtime = playtime
        self.game.is_installed = True
        self.game.config = self.lutris_config

        if new_config_id := rename_config(self.lutris_config.game_config_id, self.game.slug):
            self.game.game_config_id = new_config_id

        self.game.runner_name = self.runner_name

        if "icon" not in self.game.custom_images:
            self.game.runner.extract_icon(game_info_box.slug)

        self.game.save()
        self.destroy()
        self.saved = True
        return True


class RunnerMessageBox(WidgetWarningMessageBox):
    def __init__(self) -> None:
        super().__init__(margin_left=12, margin_right=12, icon_name="dialog-warning")
