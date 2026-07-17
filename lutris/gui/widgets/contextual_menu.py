import re

from gi.repository import Gdk, Gio, Gtk


class _MenuItemRef:
    """Placeholder returned by add_menuitem for visibility tracking."""

    def __init__(self, action_id):
        self.action_id = action_id
        self._visible = True

    def set_visible(self, visible):
        self._visible = visible

    @property
    def visible(self):
        return self._visible


class _SeparatorRef:
    def __init__(self):
        self._visible = True

    def set_visible(self, visible):
        self._visible = visible

    @property
    def visible(self):
        return self._visible


def update_action_widget_visibility(widgets, visible_predicate):
    """This sets the visibility on a set of widgets, like menu items. You provide a function
    that indicates if an item is visible, or None for separators that are visible based on
    their neighbors. Returns the count of visible widgets that are not separators."""
    visible_count = 0
    previous_visible_widget = None
    for w in widgets:
        visible = visible_predicate(w)

        if visible:
            visible_count = visible_count + 1

        if visible is None:
            if previous_visible_widget is None:
                visible = False
            else:
                visible = visible_predicate(previous_visible_widget) is not None

        w.set_visible(visible)
        if visible:
            previous_visible_widget = w

    if previous_visible_widget and visible_predicate(previous_visible_widget) is None:
        previous_visible_widget.set_visible(False)
    return visible_count


class ContextualMenu:
    def __init__(self, main_entries):
        self.main_entries = main_entries
        self._popover = None
        self._action_group = None
        self._callbacks = {}
        self._parent_window = None

    def add_menuitem(self, entry):
        """Add a menu item to the current menu

        Params:
            entry (tuple): tuple containing name, label and callback

        Returns:
            _MenuItemRef or _SeparatorRef
        """
        name, label, callback = entry
        if label == "-":
            return _SeparatorRef()

        return _MenuItemRef(name)

    def popup(self, event, game_actions):
        self._clear_popover()

        items = []
        for entry in self.main_entries:
            items.append(self.add_menuitem(entry))

        displayed = game_actions.get_displayed_entries()

        def is_visible(w):
            if isinstance(w, _SeparatorRef):
                return None

            return displayed.get(w.action_id, True)

        visible_count = update_action_widget_visibility(items, is_visible)

        if visible_count <= 0:
            return

        menu = Gio.Menu()
        self._action_group = Gio.SimpleActionGroup()
        self._callbacks = {}
        section = Gio.Menu()

        for item, entry in zip(items, self.main_entries):
            name, label, callback = entry
            if isinstance(item, _SeparatorRef):
                if not item.visible:
                    continue
                if section.get_n_items() > 0:
                    menu.append_section(None, section)
                    section = Gio.Menu()
                continue

            if not item.visible:
                continue

            safe_action_id = re.sub(r"[^a-zA-Z0-9_-]", "_", name or "action")
            action = Gio.SimpleAction.new(safe_action_id, None)
            action.connect("activate", self._on_action_activated, safe_action_id)
            self._action_group.add_action(action)
            self._callbacks[safe_action_id] = callback
            section.append(label, "ctx.%s" % safe_action_id)

        if section.get_n_items() > 0:
            menu.append_section(None, section)

        parent = Gtk.Window.get_active()
        if not parent:
            return

        self._parent_window = parent
        parent.insert_action_group("ctx", self._action_group)

        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(parent)

        if event:
            rect = Gdk.Rectangle()
            rect.x = int(event.get_x()) if hasattr(event, "get_x") else 0
            rect.y = int(event.get_y()) if hasattr(event, "get_y") else 0
            rect.width = 1
            rect.height = 1
            popover.set_pointing_to(rect)

        popover.connect("closed", self._on_popover_closed)
        self._popover = popover
        popover.popup()

    def _on_action_activated(self, _action, _parameter, action_id):
        callback = self._callbacks.get(action_id)
        if callback:
            callback()

    def _on_popover_closed(self, _popover):
        if self._parent_window:
            self._parent_window.insert_action_group("ctx", None)
        self._parent_window = None
        self._clear_popover()

    def _clear_popover(self):
        if self._popover:
            self._popover.unparent()
            self._popover = None
        self._action_group = None
        self._callbacks = {}
