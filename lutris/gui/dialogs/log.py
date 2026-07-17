"""Window to show game logs"""

import os
from datetime import datetime
from gettext import gettext as _
from typing import TYPE_CHECKING

from gi.repository import Gdk, GObject, Gtk, Pango

from lutris.gui.dialogs import FileDialog
from lutris.gui.widgets.log_text_view import LogTextView
from lutris.util import datapath

if TYPE_CHECKING:
    from lutris.game import Game
    from lutris.gui.application import LutrisApplication


class LogWindow(GObject.Object):
    def __init__(self, game: "Game", buffer: Gtk.TextBuffer, application: "LutrisApplication | None" = None):
        super().__init__()
        ui_filename = os.path.join(datapath.get(), "ui/log-window.ui")
        builder = Gtk.Builder()
        builder.add_from_file(ui_filename)
        builder.connect_signals(self)
        self.window: Gtk.ApplicationWindow = builder.get_object("log_window")

        self.title = _("Log for {}").format(game)
        self.window.set_title(self.title)

        self.buffer = buffer
        self.logtextview = LogTextView(self.buffer)
        self._font_size = self._get_current_font_size()

        scrolled_window: Gtk.ScrolledWindow = builder.get_object("scrolled_window")
        scrolled_window.set_child(self.logtextview)

        self.search_entry: Gtk.SearchEntry = builder.get_object("search_entry")
        self.search_entry.connect("search-changed", self.logtextview.find_first)
        self.search_entry.connect("next-match", self.logtextview.find_next)
        self.search_entry.connect("previous-match", self.logtextview.find_previous)

        save_button: Gtk.Button = builder.get_object("save_button")
        save_button.connect("clicked", self.on_save_clicked)

        # Add zoom buttons
        zoom_in_button: Gtk.Button = builder.get_object("zoom_in_button")
        zoom_out_button: Gtk.Button = builder.get_object("zoom_out_button")
        zoom_in_button.connect("clicked", self.on_zoom_in_clicked)
        zoom_out_button.connect("clicked", self.on_zoom_out_clicked)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.window.add_controller(key_controller)
        self.window.present()

    def _get_current_font_size(self) -> float:
        context = self.logtextview.get_pango_context()
        font_desc = context.get_font_description()
        return font_desc.get_size() / Pango.SCALE

    def _apply_font_size(self) -> None:
        tag_table = self.buffer.get_tag_table()
        tag = tag_table.lookup("log-font")
        if not tag:
            tag = self.buffer.create_tag("log-font")
        tag.set_property("font", Pango.FontDescription.from_string(f"monospace {int(self._font_size)}"))
        self.buffer.apply_tag(
            tag,
            self.buffer.get_start_iter(),
            self.buffer.get_end_iter(),
        )

    def on_key_pressed(self, _controller, keyval, keycode, state) -> bool:
        shift = state & Gdk.ModifierType.SHIFT_MASK
        if keyval == Gdk.KEY_Return:
            if shift:
                self.search_entry.emit("previous-match")
            else:
                self.search_entry.emit("next-match")
            return True
        return False

    def on_save_clicked(self, _button: Gtk.Button) -> None:
        """Handler to save log to a file"""
        now = datetime.now()
        log_filename = "%s (%s).log" % (self.title, now.strftime("%Y-%m-%d-%H-%M"))
        file_dialog = FileDialog(
            message="Save the logs to...", default_path=os.path.expanduser("~/%s" % log_filename), mode="save"
        )
        log_path = file_dialog.filename
        if not log_path:
            return None

        text = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)
        with open(log_path, "w", encoding="utf-8") as log_file:
            log_file.write(text)

    def on_zoom_in_clicked(self, _button: Gtk.Button) -> None:
        """Increase font size"""
        if self._font_size < 48:
            self._font_size += 1
            self._apply_font_size()

    def on_zoom_out_clicked(self, _button: Gtk.Button) -> None:
        """Decrease font size"""
        if self._font_size > 6:
            self._font_size -= 1
            self._apply_font_size()
