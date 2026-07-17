"""Widget generators and their signal handlers"""

import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from gettext import gettext as _
from inspect import Parameter, signature
from typing import TYPE_CHECKING, Any

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # type: ignore

from lutris.config import LutrisConfig
from lutris.gui.widgets import NotificationSource
from lutris.gui.widgets.common import EditableGrid, FileChooserEntry, Label
from lutris.gui.widgets.searchable_entrybox import SearchableEntrybox
from lutris.gui.widgets.utils import get_widget_window
from lutris.util.log import logger
from lutris.util.strings import gtk_safe

if TYPE_CHECKING:
    from lutris.gui.config.boxes import ConfigBox


def _add_to_parent(parent: Gtk.Widget, child: Gtk.Widget) -> None:
    if isinstance(parent, Adw.PreferencesGroup):
        parent.add(child)
    elif isinstance(parent, Gtk.Box):
        parent.append(child)
    else:
        parent.append(child)


class WidgetGenerator(ABC):
    """This class generates widgets for an options page. It even adds the widgets
    to a 'wrapper' you can supply and, if required, that wrapper goes into a container
    which also contains message boxes for errors and warnings.

    The specific inner widgets are generated according to an option dict.

    The generator also accumulates and tracks the wrappers and containers for future use,
    and can update their state via a call to update_widgets(). When doing this, various callables
    in the option dicts can be re-evaluated; you provide a set of 'callback_args' and 'callback_kwargs'
    that are passed along to these callbacks. These collbacks also take the identifier of the
    option, from the 'option' key of the option dict.

    'changed' is a NotificationSource for whenever the generated widget changes a value;
    the same 'changed' NotificationSource is shared by all the widgets this generator generates.

    You can only create new containers, not discard old ones, but you *can* regenerate the widget
    inside the wrapper as a way to force it to update.
    """

    GeneratorFunction = Callable[[dict[str, Any], Any, Any], Gtk.Widget | None]

    def __init__(self, parent: "ConfigBox", *callback_args, **callback_kwargs) -> None:
        self.parent = parent
        self.callback_args = callback_args
        self.callback_kwargs = callback_kwargs
        self.changed = NotificationSource()  # takes option_key, new_value
        self.changed.register(self.on_changed, priority=1000)
        self._default_directory: str | None = None
        self._current_parent: Gtk.Widget | None = None
        self._current_section: str | None = None

        # These are outputs set by generate_widget() or generate_container()
        # and they are reset on each call.
        self.wrapper: Gtk.Widget | None = None
        self.default_value = None
        self.tooltip_default: str | None = None
        self.options: dict[str, dict[str, Any]] = {}
        self.option_widget: Gtk.Widget | None = None
        self.option_container: Gtk.Widget | None = None
        self.warning_messages: list[Gtk.Widget] = []

        # These accumulate results across all widgets
        self.wrappers: dict[str, Gtk.Widget] = {}
        self.section_frames: list["SectionFrame"] = []
        self.option_containers: dict[str, Gtk.Widget] = {}

        self._generators: dict[str, WidgetGenerator.GeneratorFunction] = {
            "label": self._generate_label,
            "string": self._generate_string,
            "bool": self._generate_bool,
            "range": self._generate_range,
            "choice": self._generate_choice,
            "choice_with_entry": self._generate_choice_with_entry,
            "choice_with_search": self._generate_choice_with_search,
            "file": self._generate_file,
            "multiple_file": self._generate_multiple_file,
            "directory": self._generate_directory,
            "mapping": self._generate_mapping,
            "command_line": self._generate_command_line,
        }

    def on_changed(self, option_key: str, new_value: Any) -> None:
        """Called when any value is changed; this is called later than ordinary
        handlers for the 'changed' notification, and by default just updates the
        widgets."""
        self.update_widgets()

    @property
    def default_directory(self) -> str:
        """This is the directory selected by default by file and directory choosers."""
        if not self._default_directory:
            lutris_config = LutrisConfig()
            self._default_directory = lutris_config.system_config.get("game_path") or os.path.expanduser("~")
        return self._default_directory

    @default_directory.setter
    def default_directory(self, new_dir: str) -> None:
        self._default_directory = new_dir

    # Widget Construction

    def add_container(self, option: dict[str, Any], wrapper: Gtk.Box | None = None) -> Gtk.Widget | None:
        """Generates the option's widget, wrapper and container, and adds the container to the parent;
        if the option uses 'section', then the container is actually placed inside a SectionFrame,
        or in the previous frame if it is for the same section."""
        option_container = self.generate_container(option, wrapper)

        if option_container and self.parent:
            if not self._current_parent:
                self._current_parent = self.parent

            if option.get("section") != self._current_section:
                self._current_section = option.get("section")
                if self._current_section:
                    frame = SectionFrame(self._current_section, visible=True)
                    self.section_frames.append(frame)
                    self._current_parent = frame
                    _add_to_parent(self.parent, frame)
                else:
                    self._current_parent = self.parent

            _add_to_parent(self._current_parent, option_container)
        return option_container

    def generate_container(self, option: dict[str, Any], wrapper: Gtk.Box | None = None) -> Gtk.Widget | None:
        """Creates the widget, wrapper, and container; this returns the container
        (or the wrapper if there's no container)."""
        option_widget = self.generate_widget(option, wrapper)
        if option_widget and self.wrapper:
            option_key = option["option"]
            option_container = self.create_option_container(option, self.wrapper)
            self.option_containers[option_key] = option_container

            option_container.lutris_option_key = option_key  # type:ignore[attr-defined]
            option_container.lutris_option_label = option["label"]  # type:ignore[attr-defined]
            option_container.lutris_option_helptext = option.get("help") or ""  # type:ignore[attr-defined]

            option_container.lutris_advanced = bool(option.get("advanced"))  # type:ignore[attr-defined]
            option_container.lutris_option = option  # type:ignore[attr-defined]

            self.option_container = option_container
            return option_container
        return None

    def generate_widget(self, option: dict[str, Any], wrapper: Gtk.Box | None = None) -> Gtk.Widget | None:
        """This creates a wrapper box and a label and widget within it according to the options dict
        given. The option widget itself, is returned, but this method also sets attributes on the
        generator. You get 'wrapper', 'default_value', 'tooltip_default' and 'option_widget' which restates
        the return value. This returns None if the entire option should be omitted."""
        option_key = option["option"]
        option_type = option["type"]
        default = self.get_default(option)
        value = self.get_setting(option_key, default)

        self.default_value = default
        self.tooltip_default = None
        self.option_widget = None
        self.option_container = None
        self.warning_messages.clear()
        self.wrappers.pop(option_key, None)

        self.options[option_key] = option

        if wrapper:
            children = wrapper.get_first_child()
            while children:
                next_child = children.get_next_sibling()
                wrapper.remove(children)
                children = next_child
            self.wrapper = wrapper
        else:
            self.wrapper = self.create_wrapper_box(option, value, default)
            if not self.wrapper:
                return None

        func = self._generators.get(option_type)
        if func:
            option_widget = func(option, value, default)
        else:
            raise ValueError("Unknown widget type %s" % option_type)

        self.wrappers[option_key] = self.wrapper
        self.option_widget = option_widget
        self.tooltip_default = self.tooltip_default or (default if isinstance(default, str) else None)

        self.configure_wrapper_box(self.wrapper, option, value, default)
        self.configure_warning_messages(option)
        return option_widget

    def configure_wrapper_box(self, wrapper: Gtk.Widget, option: dict[str, Any], value: Any, default: Any) -> None:
        tooltip = self.get_tooltip(option, value, default)
        if tooltip and hasattr(wrapper, "set_subtitle"):
            wrapper.set_subtitle(tooltip)  # type: ignore[attr-defined]

    def get_tooltip(self, option: dict[str, Any], value: Any, default: Any):
        tooltip = option.get("help")
        if self.tooltip_default:
            tooltip = tooltip + "\n\n" if tooltip else ""
            tooltip += _("<b>Default</b>: ") + self.tooltip_default
        return tooltip

    def configure_warning_messages(self, option: dict[str, Any]):
        if "error" in option:
            self.warning_messages.append(ConfigErrorBox(option["error"]))

        if "warning" in option:
            self.warning_messages.append(ConfigWarningBox(option["warning"]))

    def create_wrapper_box(self, option: dict[str, Any], value: Any, default: Any) -> Gtk.Widget | None:
        available = self._evaluate_flag_option("available", option)
        if not available:
            return None
        return Adw.ActionRow(title=option.get("label", ""))

    def create_option_container(self, option: dict[str, Any], wrapper: Gtk.Widget) -> Gtk.Widget:
        if self.warning_messages:
            option_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, visible=True)
            option_container.append(wrapper)
            for widget in self.warning_messages:
                option_container.append(widget)
            return option_container
        return wrapper

    def build_option_widget(
        self, option: dict[str, Any], widget: Gtk.Widget | None, no_label: bool = False, expand: bool = True
    ) -> Gtk.Widget | None:
        if self.wrapper and widget:
            if isinstance(self.wrapper, Adw.ActionRow):
                if no_label:
                    self.wrapper.set_activatable_widget(widget)
                else:
                    self.wrapper.set_activatable_widget(widget)
            elif isinstance(self.wrapper, Gtk.Box):
                if not no_label and "label" in option:
                    label = Label(option["label"])
                    self.wrapper.append(label)
                option_size = option.get("size", None)
                if option_size:
                    expand = option_size != "small"
                if expand:
                    widget.set_hexpand(True)
                self.wrapper.append(widget)
        return widget

    # Dynamic Widget Updates

    def update_widgets(self) -> None:
        for option_key, container in self.option_containers.items():
            if hasattr(container, "lutris_option"):
                option = container.lutris_option
                wrapper = self.wrappers[option_key]
                self.update_option_container(option, container, wrapper)

        for frame in self.section_frames:
            visible = frame.has_visible_children()
            frame.set_visible(visible)

    def update_option_container(self, option, container: Gtk.Widget, wrapper: Gtk.Widget):
        child = container.get_first_child()
        while child:
            if hasattr(child, "update_message"):
                child.update_message(option, self)
            child = child.get_next_sibling()

        visible = self.get_visibility(option)
        container.set_visible(visible)

        condition: bool = self.get_condition(option)
        wrapper.set_sensitive(condition)

    # Widget factories

    def _generate_label(self, option, value, default):
        text = option["label"]
        label = Label(text)
        label.set_use_markup(True)
        label.set_halign(Gtk.Align.START)
        label.set_valign(Gtk.Align.CENTER)
        return self.build_option_widget(option, label, no_label=True)

    def _generate_string(self, option, value, default):
        def on_changed(entry):
            self.changed.fire(option_key, entry.get_text())

        option_key = option["option"]
        if isinstance(self.wrapper, Adw.EntryRow):
            row = self.wrapper
            row.set_text(value or default or "")
            row.connect("changed", on_changed)
            return row

        entry = Gtk.Entry()
        entry.set_text(value or default or "")
        entry.connect("changed", on_changed)
        return self.build_option_widget(option, entry)

    def _generate_bool(self, option, value, default):
        def on_notify_active(widget, _gparam):
            self.changed.fire(option_key, widget.get_active())

        def to_bool(to_convert):
            if to_convert is None:
                return None
            if isinstance(to_convert, str):
                text = to_convert.casefold().strip()
                if text == "true":
                    return True
                if text == "false":
                    return False
                return None
            return bool(to_convert)

        option_key = option["option"]
        active = to_bool(value)
        if active is None:
            active = bool(to_bool(default))

        row = Adw.SwitchRow(title=option["label"])
        row.set_active(active)
        row.connect("notify::active", on_notify_active)
        self.wrapper = row
        self.tooltip_default = _("Enabled") if to_bool(default) else _("Disabled")
        return row

    def _generate_range(self, option, value, default):
        def on_changed(widget, _gparam):
            self.changed.fire(option_key, widget.get_value())

        option_key = option["option"]
        min_val = option["min"]
        max_val = option["max"]

        adjustment = Gtk.Adjustment.new(
            value if value is not None else (default if default is not None else min_val),
            min_val,
            max_val,
            1,
            0,
            0,
        )
        row = Adw.SpinRow(title=option["label"])
        row.set_adjustment(adjustment)
        row.connect("notify::value", on_changed)
        self.wrapper = row
        return row

    def _populate_combo_row(self, row: Adw.ComboRow, expanded, value, default):
        model = Gtk.StringList()
        values = []
        tooltip_default = None
        for choice_ui, choice_value in expanded:
            model.append(choice_ui)
            values.append(choice_value)
            if choice_value == default:
                tooltip_default = choice_ui
        row.set_model(model)
        if value in values:
            row.set_selected(values.index(value))
        elif default in values:
            row.set_selected(values.index(default))
        if tooltip_default:
            self.tooltip_default = str(tooltip_default)
        return values

    def _generate_choice(self, option, value, default, has_entry=False):
        def expand_combobox_choices():
            expanded = []
            tooltip_default = None
            valid = []
            has_value = False
            choice_iterable = None
            if isinstance(choices, Mapping):
                choice_iterable = choices.items()
            if not choice_iterable:
                if isinstance(choices, (list, tuple)) and choices:
                    if isinstance(choices[0], str):
                        choice_iterable = zip(choices, choices)
                    elif isinstance(choices[0], (list, tuple)) and len(choices[0]) == 2:
                        choice_iterable = choices
            if not choice_iterable:
                raise ValueError(
                    "Choice entries must be list of strings, list of tuple of strings or a dict of strings\n"
                    "Type is %s" % type(choices)
                )

            for choice_ui, choice_value in choice_iterable:
                if choice_value == value:
                    has_value = True
                if choice_value == default:
                    tooltip_default = choice_ui
                    choice_ui = _("%s (default)") % tooltip_default
                valid.append(choice_value)
                expanded.append((choice_ui, choice_value))
            if not has_value and value:
                expanded.insert(0, (value, value))
            return expanded, tooltip_default, valid

        def on_combo_changed(row, _gparam):
            selected = row.get_selected()
            if selected < 0:
                return
            option_value = row_values[selected]
            self.changed.fire(option_key, option_value)

        def on_combobox_change(widget):
            list_store = widget.get_model()
            active = widget.get_active()
            option_value = None
            if active < 0:
                if widget.get_has_entry():
                    option_value = widget.get_child().get_text()
            else:
                option_value = list_store[active][1]
            self.changed.fire(option_key, option_value)

        option_key = option["option"]
        choices_src = option.get("choices")
        choices = self._evaluate_option("choices", None, option)
        expanded_choices, _tooltip_default, valid_choices = expand_combobox_choices()

        if has_entry:
            liststore = Gtk.ListStore(str, str)
            for choice in expanded_choices:
                liststore.append(choice)
            combobox = Gtk.ComboBox.new_with_model_and_entry(liststore)
            combobox.set_entry_text_column(0)
            if value in [v for _k, v in expanded_choices]:
                combobox.set_active_id(value)
            elif value:
                for ch in combobox.get_children():
                    if isinstance(ch, Gtk.Entry):
                        ch.set_text(value or "")
                        break
            else:
                combobox.set_active_id(default)
            combobox.connect("changed", on_combobox_change)
            combobox.set_valign(Gtk.Align.CENTER)
            self._prevent_combobox_scroll(combobox)
            return self.build_option_widget(option, combobox)

        row = Adw.ComboRow(title=option["label"])
        row_values = self._populate_combo_row(row, expanded_choices, value, default)
        row.connect("notify::selected", on_combo_changed)
        self.wrapper = row

        def get_invalidity_error(key: str):
            v = self.get_setting(key, self.get_default(option))
            if v in valid_choices:
                return None
            return _("The setting '%s' is no longer available. You should select another choice.") % v

        if value not in valid_choices:
            self.warning_messages.append(ConfigWarningBox(get_invalidity_error))

        if callable(choices_src) and hasattr(choices_src, "register_reload_callback"):

            def reload_choices():
                nonlocal choices, row_values
                choices = self.evaluate_option_value(choices_src, option=option)
                expanded, _, _valid = expand_combobox_choices()
                row_values = self._populate_combo_row(row, expanded, value, default)

            choices_src.register_reload_callback(reload_choices)

        return row

    def _generate_choice_with_entry(self, option, value, default):
        return self._generate_choice(option, value, default, has_entry=True)

    def _generate_choice_with_search(self, option, value, default):
        def on_changed(_widget, new_value):
            self.changed.fire(option_key, new_value)

        option_key = option["option"]
        choices_src = option["choices"]
        entrybox = SearchableEntrybox(choices_src, value or default)
        entrybox.connect("changed", on_changed)

        if callable(choices_src) and hasattr(choices_src, "register_reload_callback"):
            choices_src.register_reload_callback(entrybox.repopulate)

        return self.build_option_widget(option, entrybox)

    def _generate_file(self, option, value, default, shell_quoting=False):
        def on_changed(entry):
            self.changed.fire(option_key, entry.get_text())

        option_key = option["option"]
        warn_if_non_writable_parent = bool(option.get("warn_if_non_writable_parent"))

        if not value:
            value = default

        if "default_path" in option:
            lutris_config = LutrisConfig()
            chooser_default_path = lutris_config.system_config.get(option["default_path"])
        else:
            chooser_default_path = self.default_directory

        file_chooser = FileChooserEntry(
            title=_("Select file"),
            action=Gtk.FileChooserAction.OPEN,
            warn_if_non_writable_parent=warn_if_non_writable_parent,
            text=value,
            default_path=chooser_default_path,
            shell_quoting=shell_quoting,
        )

        if value:
            if not os.path.isabs(value):
                value = os.path.expanduser(value)
                if not os.path.isabs(value):
                    value = os.path.join(self.default_directory, value)
            file_chooser.entry.set_text(value)

        file_chooser.set_valign(Gtk.Align.CENTER)
        file_chooser.connect("changed", on_changed)
        return self.build_option_widget(option, file_chooser)

    def _generate_command_line(self, option, value, default):
        return self._generate_file(option, value, default, shell_quoting=True)

    def _generate_multiple_file(self, option, value, default):
        def on_add_files_clicked(_widget):
            dialog = Gtk.FileDialog(title=_("Select files"))
            dialog.set_initial_folder(Gio.File.new_for_path(first_file_dir or self.default_directory))

            parent = get_widget_window(self.parent)
            if parent:
                dialog.set_transient_for(parent)

            def on_files_selected(_dlg, result):
                try:
                    files = dialog.open_multiple_finish(result)
                except GLib.Error:
                    return
                for gfile in files:
                    filename = gfile.get_path()
                    if filename and filename not in files_paths:
                        files_list_store.append([filename])
                        files_paths.append(filename)
                self.changed.fire(option_key, files_paths)

            dialog.open_multiple(parent, None, on_files_selected)

        def on_files_treeview_keypress(_treeview, keyval, _keycode, _state):
            if keyval == Gdk.KEY_Delete:
                selection = files_treeview.get_selection()
                model, treepaths = selection.get_selected_rows()
                for treepath in treepaths:
                    treeiter = model.get_iter(treepath)
                    model.remove(treeiter)
                self.changed.fire(option_key, [row[0] for row in files_list_store])

        option_key = option["option"]
        label = option["label"]

        files_list_store = Gtk.ListStore(str)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        label_widget = Label(label + ":")
        label_widget.set_halign(Gtk.Align.START)
        button = Gtk.Button(label=_("Add Files"))
        button.connect("clicked", on_add_files_clicked)
        button.set_margin_start(10)
        vbox.append(label_widget)
        vbox.append(button)

        if not value:
            value = default

        if value:
            files_paths = [value] if isinstance(value, str) else list(value)
        else:
            files_paths = []

        for filename in files_paths:
            files_list_store.append([filename])

        first_file_dir = os.path.dirname(files_paths[0]) if files_paths else None

        cell_renderer = Gtk.CellRendererText()
        files_treeview = Gtk.TreeView(model=files_list_store)
        files_column = Gtk.TreeViewColumn(_("Files"), cell_renderer, text=0)
        files_treeview.append_column(files_column)
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", on_files_treeview_keypress)
        files_treeview.add_controller(key_controller)
        treeview_scroll = Gtk.ScrolledWindow()
        treeview_scroll.set_min_content_height(130)
        treeview_scroll.set_margin_start(10)
        treeview_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        treeview_scroll.set_child(files_treeview)
        vbox.append(treeview_scroll)
        return self.build_option_widget(option, vbox, no_label=True)

    def _generate_directory(self, option, value, default):
        def on_changed(entry):
            self.changed.fire(option_key, entry.get_text())

        option_key = option["option"]
        warn_if_non_writable_parent = bool(option.get("warn_if_non_writable_parent"))

        if not value:
            value = default

        directory_chooser = FileChooserEntry(
            title=_("Select folder"),
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            warn_if_non_writable_parent=warn_if_non_writable_parent,
            text=value,
            default_path=self.default_directory if not value else None,
        )
        directory_chooser.connect("changed", on_changed)
        directory_chooser.set_valign(Gtk.Align.CENTER)
        return self.build_option_widget(option, directory_chooser)

    def _generate_mapping(self, option, value, default):
        def on_changed(widget):
            values = dict(widget.get_data())
            self.changed.fire(option_key, values)

        option_key = option["option"]
        value = value or default or {}
        try:
            value = list(value.items())
        except AttributeError:
            logger.error("Invalid value of type %s passed to grid widget: %s", type(value), value)
            value = []

        grid = EditableGrid(value, columns=["Key", "Value"])
        grid.connect("changed", on_changed)
        return self.build_option_widget(option, grid)

    @staticmethod
    def _prevent_combobox_scroll(combobox: Gtk.ComboBox) -> None:
        controller = Gtk.EventControllerScroll()
        controller.connect("scroll", lambda *_args: True)
        combobox.add_controller(controller)

    # Option access

    @abstractmethod
    def get_setting(self, option_key: str, default: Any) -> Any:
        raise NotImplementedError()

    def get_default(self, option: dict[str, Any]) -> Any:
        return self._evaluate_option("default", default=None, option=option)

    def get_visibility(self, option: dict[str, Any]) -> bool:
        return self._evaluate_flag_option("visible", option)

    def get_condition(self, option: dict[str, Any]) -> bool:
        condition = self._evaluate_flag_option("condition", option)
        conditional_on = option.get("conditional_on")

        if conditional_on:
            conditional_on_default = self.get_default(self.options[conditional_on])
            if not self.get_setting(conditional_on, conditional_on_default):
                return False

        container = self.option_containers[option["option"]]
        child = container.get_first_child()
        while child:
            if hasattr(child, "blocks_sensitivity") and child.blocks_sensitivity:
                return False
            child = child.get_next_sibling()

        return condition

    def _evaluate_flag_option(self, key: str, option: dict[str, Any]) -> bool:
        flag = self._evaluate_option(key, default=True, option=option)
        return bool(flag) if flag is not None else True

    def _evaluate_option(self, key: str, default: Any, option: dict[str, Any]) -> Any:
        if key not in option:
            return default
        value = option[key]
        return self.evaluate_option_value(value, option=option)

    def evaluate_option_value(self, value: Any, option: dict[str, Any]) -> Any:
        if callable(value):
            sig = signature(value)
            argcount = len(sig.parameters)
            option_key = option["option"]
            argsneeded = 1 + len(self.callback_args)

            if argcount >= argsneeded:
                return value(option_key, *self.callback_args, **self.callback_kwargs)
            if any(p.kind == Parameter.VAR_POSITIONAL for p in sig.parameters.values()):
                return value(option_key, *self.callback_args, **self.callback_kwargs)
            if argcount == 0:
                return value(**self.callback_kwargs)
            args = list(self.callback_args)
            args.insert(0, option_key)
            args = args[:argcount]
            return value(*args, **self.callback_kwargs)

        return value


class SectionFrame(Adw.PreferencesGroup):
    """A preferences group for a configuration section."""

    def __init__(self, section, **kwargs):
        super().__init__(title=section, **kwargs)
        self.section = section

    def has_visible_children(self):
        child = self.get_first_child()
        while child:
            if child.get_visible():
                return True
            child = child.get_next_sibling()
        return False


class WidgetWarningMessageBox(Gtk.Box):
    """A box to display a message with an icon inside the configuration dialog."""

    def __init__(self, icon_name, margin_left=18, margin_right=18, margin_bottom=6):
        super().__init__(
            spacing=6,
            visible=False,
            margin_start=margin_left,
            margin_end=margin_right,
            margin_bottom=margin_bottom,
        )

        self.image = Gtk.Image(visible=True)
        self.image.set_from_icon_name(icon_name)
        self.append(self.image)
        self.label = Gtk.Label(visible=True, xalign=0)
        self.label.set_wrap(True)
        self.append(self.label)

    def show_markup(self, markup, icon_name=None) -> bool:
        visible = bool(markup)

        if markup:
            self.label.set_markup(str(markup))
            if icon_name:
                self.image.set_from_icon_name(icon_name)

        self.set_visible(visible)
        return visible


class ConfigMessageBox(WidgetWarningMessageBox):
    def __init__(self, message, icon_name, **kwargs):
        self.message = message
        super().__init__(icon_name, **kwargs)

        if not callable(message):
            text = gtk_safe(message)
            if text:
                self.label.set_markup(str(text))

    def update_message(self, option: dict[str, Any], generator: WidgetGenerator) -> bool:
        try:
            text = generator.evaluate_option_value(self.message, option)
        except Exception as err:
            logger.exception("Unable to generate configuration warning: %s", err)
            text = gtk_safe(str(err))

        return self.show_markup(text)


class ConfigWarningBox(ConfigMessageBox):
    def __init__(self, warning):
        super().__init__(warning, icon_name="dialog-warning")


class ConfigErrorBox(ConfigMessageBox):
    def __init__(self, error):
        super().__init__(error, icon_name="dialog-error")

    @property
    def blocks_sensitivity(self):
        return self.get_visible()
