"""Configuration dialog for client and system options"""

# pylint: disable=no-member
from gettext import gettext as _
from gettext import pgettext as C_
from textwrap import dedent

from gi.repository import Adw, Gtk

from lutris.config import LutrisConfig
from lutris.gui.config.accounts_box import AccountsBox
from lutris.gui.config.boxes import SystemConfigBox
from lutris.gui.config.preferences_box import InterfacePreferencesBox
from lutris.gui.config.runners_box import RunnersBox
from lutris.gui.config.services_box import ServicesBox
from lutris.gui.config.storage_box import StorageBox
from lutris.gui.config.sysinfo_box import SystemBox
from lutris.gui.config.updates_box import UpdatesBox
from lutris.gui.widgets.utils import get_widget_window


class PreferencesDialog(Adw.PreferencesWindow):
    def __init__(self, application=None, parent=None, **kwargs):
        super().__init__(application=application, title=_("Lutris settings"), default_width=1010, default_height=600)
        parent_window = get_widget_window(parent)
        if parent_window:
            self.set_transient_for(parent_window)

        self.lutris_config = LutrisConfig()
        self.page_generators = {}
        self.runners_box = None
        self.system_box = None

        self.shortcut_controller = Gtk.ShortcutController()
        self.add_controller(self.shortcut_controller)

        self._add_interface_page()
        self._add_runners_page()
        self._add_services_page()
        self._add_accounts_page()
        self._add_updates_page()
        self._add_sysinfo_page()
        self._add_storage_page()
        self._add_system_page()

        self.connect("notify::visible-page", self.on_visible_page_changed)

    def _wrap_in_scrolled(self, widget: Gtk.Widget) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(widget)
        return scrolled

    def _add_page(self, stack_id: str, title: str, icon_name: str, content: Gtk.Widget, populate=None) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage()
        page.set_title(title)
        page.set_icon_name(icon_name)
        page.lutris_stack_id = stack_id  # type: ignore[attr-defined]

        group = Adw.PreferencesGroup()
        group.add(content)
        page.add(group)
        self.add(page)

        if populate:
            self.page_generators[stack_id] = populate
        return page

    def _add_interface_page(self):
        self._add_page(
            "prefs-stack",
            _("Interface"),
            "view-grid-symbolic",
            InterfacePreferencesBox(self.shortcut_controller),
        )

    def _add_runners_page(self):
        self.runners_box = RunnersBox()
        self.page_generators["runners-stack"] = self.runners_box.populate_runners
        self._add_page(
            "runners-stack",
            _("Runners"),
            "applications-utilities-symbolic",
            self._wrap_in_scrolled(self.runners_box),
        )

    def _add_services_page(self):
        services_box = ServicesBox()
        self.page_generators["services-stack"] = services_box.populate_services
        self._add_page(
            "services-stack",
            _("Sources"),
            "application-x-addon-symbolic",
            self._wrap_in_scrolled(services_box),
        )

    def _add_accounts_page(self):
        accounts_box = AccountsBox()
        self.page_generators["accounts-stack"] = accounts_box.populate_steam_accounts
        self._add_page(
            "accounts-stack",
            _("Accounts"),
            "system-users-symbolic",
            self._wrap_in_scrolled(accounts_box),
        )

    def _add_updates_page(self):
        updates_box = UpdatesBox()
        self.page_generators["updates-stack"] = updates_box.populate
        self._add_page(
            "updates-stack",
            _("Updates"),
            "system-software-install-symbolic",
            self._wrap_in_scrolled(updates_box),
        )

    def _add_sysinfo_page(self):
        sysinfo_box = SystemBox()
        self.page_generators["sysinfo-stack"] = sysinfo_box.populate
        self._add_page(
            "sysinfo-stack",
            C_("preferences", "System"),
            "computer-symbolic",
            self._wrap_in_scrolled(sysinfo_box),
        )

    def _add_storage_page(self):
        storage_box = StorageBox()
        self.page_generators["storage-stack"] = storage_box.populate
        self._add_page(
            "storage-stack",
            _("Storage"),
            "drive-harddisk-symbolic",
            self._wrap_in_scrolled(storage_box),
        )

    def _add_system_page(self):
        self.system_box = SystemConfigBox("system", self.lutris_config, visible=True)
        self.page_generators["system-stack"] = self.system_box.generate_widgets

        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.system_search_entry = Gtk.SearchEntry(placeholder_text=self.get_search_entry_placeholder())
        self.system_search_entry.connect("search-changed", self._on_system_search_changed)
        page_box.append(self.system_search_entry)
        page_box.append(self._wrap_in_scrolled(self.system_box))

        save_row = Gtk.Button(label=_("Save"), halign=Gtk.Align.END, css_classes=["suggested-action"])
        save_row.connect("clicked", self.on_save)
        page_box.append(save_row)

        self._add_page(
            "system-stack",
            _("Global options"),
            "emblem-system-symbolic",
            page_box,
        )

    def on_visible_page_changed(self, _window, _pspec):
        page = self.get_visible_page()
        if not page:
            return

        stack_id = getattr(page, "lutris_stack_id", None)
        if not stack_id:
            return

        generator = self.page_generators.get(stack_id)
        if generator:
            del self.page_generators[stack_id]
            generator()

        if stack_id == "system-stack":
            self.system_search_entry.set_visible(True)
        elif stack_id == "runners-stack":
            self.runners_box.filter = self.runners_box.filter

    def _on_system_search_changed(self, entry):
        self._set_filter(entry.get_text().lower().strip())

    def get_search_entry_placeholder(self):
        return _("Search global options")

    def on_save(self, _widget):
        self.lutris_config.save()
        self.destroy()

    def _set_filter(self, value):
        if self.system_box:
            self.system_box.filter = value
        if self.runners_box:
            self.runners_box.filter = value
