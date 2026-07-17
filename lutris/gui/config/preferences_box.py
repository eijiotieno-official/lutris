from gettext import gettext as _
from typing import Any

from gi.repository import Adw, Gio, Gtk  # type: ignore

from lutris import settings
from lutris.gui.config.base_config_box import BaseConfigBox
from lutris.gui.config.widget_generator import WidgetGenerator
from lutris.gui.widgets.status_icon import supports_status_icon
from lutris.settings import read_setting


def _is_system_dark_by_default():
    app = Gio.Application.get_default()
    return app.style_manager.is_dark_by_default


class InterfacePreferencesBox(BaseConfigBox):
    settings_options = [
        {
            "option": "hide_client_on_game_start",
            "label": _("Minimize client when a game is launched"),
            "type": "bool",
            "help": _("Minimize the Lutris window while playing a game; it will return when the game exits."),
        },
        {
            "option": "hide_text_under_icons",
            "label": _("Hide text under icons"),
            "type": "bool",
            "help": _("Removes the names from the Lutris window when in grid view, but not list view."),
        },
        {
            "option": "hide_badges_on_icons",
            "label": _("Hide badges on icons (Ctrl+p to toggle)"),
            "type": "bool",
            "accelerator": "<Primary>p",
            "help": _("Removes the platform and missing-game badges from icons in the Lutris window."),
        },
        {
            "option": "show_tray_icon",
            "label": _("Show Tray Icon"),
            "type": "bool",
            "available": supports_status_icon,
            "help": _(
                "Adds a Lutris icon to the tray, and prevents Lutris from exiting when the Lutris window is closed. "
                "You can still exit using the menu of the tray icon."
            ),
        },
        {
            "option": "discord_rpc",
            "label": _("Enable Discord Rich Presence for Available Games"),
            "type": "bool",
        },
        {
            "option": "preferred_theme",
            "type": "choice",
            "label": _("Theme"),
            "choices": [
                (_("System Default"), "default"),
                (_("Light"), "light"),
                (_("Dark"), "dark"),
            ],
            "default": "default",
            "help": _("Overrides Lutris's appearance to be light or dark."),
        },
    ]

    def __init__(self, shortcut_controller):
        super().__init__()
        self.shortcut_controller = shortcut_controller

        group = Adw.PreferencesGroup(title=_("Interface options"))
        self.append(group)

        gen = PreferencesWidgetGenerator(self)
        gen.changed.register(self.on_setting_changed)
        self.widget_generator = gen

        for option in self.settings_options:
            gen.generate_container(option)
            if gen.option_container:
                group.add(gen.option_container)

        gen.update_widgets()

    def on_setting_changed(self, option_key, new_value):
        settings.write_setting(option_key, new_value)


class PreferencesWidgetGenerator(WidgetGenerator):
    """Generator for interface preferences using Adw preference rows."""

    def get_setting(self, option_key: str, default: Any) -> Any:
        return read_setting(option_key, default=default)

    def create_wrapper_box(self, option: dict[str, Any], value: Any, default: Any) -> Gtk.Widget | None:
        return super().create_wrapper_box(option, value, default)

    def build_option_widget(
        self, option: dict[str, Any], widget: Gtk.Widget | None, no_label: bool = False, expand: bool = False
    ) -> Gtk.Widget | None:
        if no_label:
            return super().build_option_widget(option, widget, no_label=no_label, expand=expand)

        if isinstance(self.wrapper, Adw.ActionRow) and widget:
            self.wrapper.set_activatable_widget(widget)
        return widget
