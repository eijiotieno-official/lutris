"""Entry box with popup list and search"""

from gi.repository import Gdk, GLib, GObject, Gtk

from lutris.gui.dialogs import display_error
from lutris.gui.widgets.utils import get_widget_window


class SearchableEntrybox(Gtk.Box):
    """Entry box with autocompletion and popup list function.
    Well fitted for large lists.
    """

    __gsignals__ = {
        "changed": (GObject.SIGNAL_RUN_FIRST, None, (str,)),
    }

    def __init__(self, choice_func, initial=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.initial = initial
        self.choice_func = choice_func
        self.liststore = Gtk.ListStore(str, str)
        self.entry = Gtk.Entry()

        self.completion = Gtk.EntryCompletion()
        self.completion.set_model(self.liststore)
        self.completion.set_text_column(0)
        self.completion.set_match_func(self.search_store)
        self.entry.set_completion(self.completion)

        self._popover = Gtk.Popover()
        self._popover.set_parent(self.entry)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._popover.set_child(self._list_box)

        self.entry.connect("changed", self.on_entrybox_change)
        scroll_controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_controller.connect("scroll", self._on_entrybox_scroll)
        self.entry.add_controller(scroll_controller)
        self.entry.connect("icon-press", self.on_entrybox_icon_press)
        self.append(self.entry)
        GLib.idle_add(self._populate_entrybox_choices, choice_func)

    def get_model(self):
        """Proxy to the liststore"""
        return self.liststore

    def get_active_id(self):
        """Return the ID associated with the current entry text."""
        text = self.entry.get_text()
        for row in self.liststore:
            if row[0] == text:
                return row[1]
        return None

    @staticmethod
    def get_has_entry():
        """The entry present is not for editing custom values, only search"""
        return False

    def search_store(self, _completion, string, _iter):
        """Return true if the search string is in the row text."""
        row_text = self.liststore[_iter][0].lower()
        return string.lower() in row_text

    def _clear_popup_choices(self):
        child = self._list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._list_box.remove(child)
            child = next_child

    def _populate_entrybox_choices(self, choice_func):
        """Populate the liststore and popup list with choices."""
        try:
            choices = choice_func()
            self._clear_popup_choices()
            for choice in choices:
                self.liststore.append(choice)
                row_button = Gtk.Button(label=choice[0])
                row_button.set_has_frame(False)
                row_button.connect("clicked", self.on_list_item_clicked, choice[0], choice[1])
                self._list_box.append(row_button)

            if self.initial:
                self._set_initial_text()
                self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "emblem-ok-symbolic")
            else:
                self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "system-search-symbolic")
        except Exception as ex:
            self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "error-symbolic")
            display_error(ex, parent=get_widget_window(self))

    def repopulate(self):
        """Clear and repopulate choices; used when an async choices load completes."""
        self.liststore.clear()
        self._populate_entrybox_choices(self.choice_func)

    def on_entrybox_icon_press(self, _entry, _icon_pos, _event):
        """Show popup list when the primary icon is pressed."""
        rect = Gdk.Rectangle()
        rect.x = 0
        rect.y = self.entry.get_height()
        rect.width = self.entry.get_width()
        rect.height = 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    def on_list_item_clicked(self, _button, label, active_id):
        """Set the selected item text in the entry and emit the changed signal."""
        self.entry.set_text(label)
        self._popover.popdown()
        self.emit("changed", active_id)

    def _set_initial_text(self):
        """Set the initial text in the entry if it matches an item."""
        for row in self.liststore:
            if row[1] == self.initial:
                self.entry.set_text(row[0])
                break

    def _on_entrybox_scroll(self, _controller, _dx, _dy):
        """Prevents users from accidentally changing configuration values while scrolling down dialogs."""
        return True

    def on_entrybox_change(self, _widget):
        """Action triggered on entrybox 'changed' signal."""
        active_id = self.get_active_id()
        self._update_search_icon()
        if active_id:
            self.emit("changed", active_id)

    def _update_search_icon(self):
        """Updates the icon based on the search result."""
        text = self.entry.get_text()
        if not text:
            self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "system-search-symbolic")
        elif any(row[0] == text for row in self.liststore):
            self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "emblem-ok-symbolic")
        elif any(text.lower() in row[0].lower() for row in self.liststore):
            self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "content-loading-symbolic")
        else:
            self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "action-unavailable-symbolic")
