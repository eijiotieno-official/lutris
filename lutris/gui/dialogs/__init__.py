"""Commonly used dialogs"""

import builtins
import inspect
import os
import traceback
from collections.abc import Callable
from gettext import gettext as _
from typing import TYPE_CHECKING, Any, Dict, TypeVar, cast

from gi.repository import Adw, Gdk, GLib, Gio, GObject, Gtk

from lutris import api, settings
from lutris.exceptions import LutrisError
from lutris.gui.widgets.log_text_view import LogTextView
from lutris.gui.widgets.utils import get_widget_window
from lutris.util import datapath
from lutris.util.jobs import schedule_at_idle
from lutris.util.log import get_log_contents, logger
from lutris.util.strings import gtk_safe

if TYPE_CHECKING:
    from lutris.config import LaunchConfigDict
    from lutris.game import Game

_DIALOG_MODAL = getattr(Gtk.DialogFlags, "MODAL", 1) if hasattr(Gtk, "DialogFlags") else 1


def _run_adw_message_dialog(dialog: Adw.MessageDialog) -> str:
    """Run an Adw.MessageDialog synchronously for backward compatibility."""
    result: list[str | None] = [None]
    loop = GLib.MainLoop()

    def on_chosen(_dialog: Adw.MessageDialog, async_result) -> None:
        result[0] = dialog.choose_finish(async_result)
        loop.quit()

    dialog.choose(None, on_chosen)
    loop.run()
    return result[0] or ""


class Dialog(Gtk.Dialog):
    """A base class for dialogs that provides handling for the response signal;
    you can override its on_response() methods, but that method will record
    the response for you via 'response_type' or 'confirmed' and destory this
    dialog if it isn't NONE."""

    vbox: Gtk.Box

    def __init__(
        self,
        title: str | None = None,
        parent: Gtk.Widget | None = None,
        flags: int = 0,
        buttons: Gtk.ButtonsType | None = None,
        **kwargs: Any,
    ):
        use_header_bar = kwargs.pop("use_header_bar", None)
        border_width = kwargs.pop("border_width", None)

        init_kwargs: dict[str, Any] = {}
        if title:
            init_kwargs["title"] = title
        if use_header_bar is not None:
            init_kwargs["use_header_bar"] = use_header_bar

        super().__init__(**init_kwargs, **kwargs)

        parent_window = get_widget_window(parent)
        if parent_window:
            self.set_transient_for(parent_window)
        if flags & _DIALOG_MODAL:
            self.set_modal(True)

        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(self.vbox)

        if border_width is not None:
            self.vbox.set_margin_top(border_width)
            self.vbox.set_margin_bottom(border_width)
            self.vbox.set_margin_start(border_width)
            self.vbox.set_margin_end(border_width)

        self._response_type = Gtk.ResponseType.NONE
        self._run_loop: GLib.MainLoop | None = None
        self.connect("response", self.on_response)

        if buttons is not None:
            self._add_buttons_type(buttons)

    def get_content_area(self) -> Gtk.Box:
        return self.vbox

    def run(self) -> Gtk.ResponseType:
        self.present()
        self._run_loop = GLib.MainLoop()
        self._run_loop.run()
        return self._response_type

    def _add_buttons_type(self, buttons: Gtk.ButtonsType) -> None:
        if buttons == Gtk.ButtonsType.OK:
            self.add_button(_("_OK"), Gtk.ResponseType.OK)
        elif buttons == Gtk.ButtonsType.OK_CANCEL:
            self.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
            self.add_button(_("_OK"), Gtk.ResponseType.OK)
        elif buttons == Gtk.ButtonsType.YES_NO:
            self.add_button(_("_No"), Gtk.ResponseType.NO)
            self.add_button(_("_Yes"), Gtk.ResponseType.YES)

    @property
    def response_type(self) -> Gtk.ResponseType:
        """The response type of the response that occurred; initially this is NONE.
        Use the GTK response() method to artificially generate a response, rather than
        setting this."""
        return self._response_type

    @property
    def confirmed(self) -> bool:
        """True if 'response_type' is OK or YES."""
        return self.response_type in (Gtk.ResponseType.OK, Gtk.ResponseType.YES)

    def on_response(self, _dialog: Gtk.Dialog, response: Gtk.ResponseType) -> None:
        """Handles the dialog response; you can override this but by default
        this records the response for 'response_type'."""
        self._response_type = response
        if self._run_loop and self._run_loop.is_running():
            self._run_loop.quit()

    def destroy_at_idle(self, condition: Callable[[], bool] | None = None) -> None:
        """Adds as idle task to destroy this window at idle time;
        it can do so conditionally if you provide a callable to check,
        but it checks only once. You can still explicitly destroy the
        dialog after calling this. This is used to ensure destruction of
        ModalDialog after run()."""

        def idle_destroy() -> None:
            if not condition or condition():
                self.destroy()

        def on_destroy(*_args: Any) -> None:
            self.disconnect(on_destroy_id)
            idle_destroy_task.unschedule()

        self.hide()
        idle_destroy_task = schedule_at_idle(idle_destroy)
        on_destroy_id = self.connect("destroy", on_destroy)

    def add_styled_button(self, button_text: str, response_id: Gtk.ResponseType, css_class: str) -> Gtk.Button:
        button: Gtk.Button = self.add_button(button_text, response_id)
        if css_class:
            button.add_css_class(css_class)
        return button

    def add_default_button(
        self, button_text: str, response_id: Gtk.ResponseType, css_class: str = "suggested-action"
    ) -> Gtk.Button:
        """Adds a button to the dialog with a particular response id, but
        also makes it the default and styles it as the suggested action."""
        button = self.add_styled_button(button_text, response_id, css_class)
        self.set_default_response(response_id)
        return button


class ModalDialog(Dialog):
    """A base class of modal dialogs, which sets the flag for you.

    Unlike plain Gtk.Dialog, these destroy themselves (at idle-time) after
    you call run(), even if you forget to. They aren't meant to be reused."""

    def __init__(
        self,
        title: str | None = None,
        parent: Gtk.Widget | None = None,
        flags: int = 0,
        buttons: Gtk.ButtonsType | None = None,
        **kwargs: Any,
    ):
        super().__init__(title, parent, flags | _DIALOG_MODAL, buttons, **kwargs)
        self.set_destroy_with_parent(True)

    def on_response(self, dialog: Gtk.Dialog, response: Gtk.ResponseType) -> None:
        super().on_response(dialog, response)
        # Model dialogs do return from run() in response from respose() but the
        # dialog is visible and locks out its parent. So we hide it. Watch out-
        # self.destroy() changes the run() result to NONE.
        if response != Gtk.ResponseType.NONE:
            self.hide()
            self.destroy_at_idle(condition=lambda: not self.get_visible())


class ModelessDialog(Dialog):
    """A base class for modeless dialogs. They have a parent only temporarily, so
    they can be centered over it during creation. But each modeless dialog gets
    its own window group, so it treats its own modal dialogs separately, and it resets
    its transient-for after being created."""

    def __init__(
        self,
        title: str | None = None,
        parent: Gtk.Widget | None = None,
        flags: int = 0,
        buttons: Gtk.ButtonsType | None = None,
        **kwargs: Any,
    ):
        super().__init__(title, parent, flags, buttons, **kwargs)
        # These are not stuck above the 'main' window, but can be
        # re-ordered freely.

        # These are independent windows, but start centered over
        # a parent like a dialog. Not modal, not really transient,
        # and does not share modality with other windows - so it
        # needs its own window group.
        Gtk.WindowGroup().add_window(self)
        schedule_at_idle(self._clear_transient_for)

    def _clear_transient_for(self) -> None:
        # we need the parent set to be centered over the parent, but
        # we don't want to be transient really - we want other windows
        # able to come to the front.
        self.set_transient_for(None)

    def on_response(self, dialog: Gtk.Dialog, response: Gtk.ResponseType) -> None:
        super().on_response(dialog, response)
        # Modal dialogs self-destruct, but modeless ones must commit
        # suicide more explicitly.
        if response != Gtk.ResponseType.NONE:
            self.destroy()


class SavableModelessDialog(ModelessDialog):
    """This is a modeless dialog that has a Cancel and a Save button in the header-bar,
    with a ctrl-S keyboard shortcut to save."""

    def __init__(self, title: str, parent: Gtk.Widget | None = None, **kwargs: Any):
        super().__init__(title, parent=parent, use_header_bar=True, **kwargs)

        self.cancel_button = self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        self.cancel_button.set_valign(Gtk.Align.CENTER)

        self.save_button = self.add_styled_button(_("Save"), Gtk.ResponseType.NONE, css_class="suggested-action")
        self.save_button.set_valign(Gtk.Align.CENTER)
        self.save_button.connect("clicked", self.on_save)

        controller = Gtk.ShortcutController()
        shortcut = Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Primary>s"),
            Gtk.CallbackAction.new(lambda *_args: self.on_save() or True),
        )
        controller.add_shortcut(shortcut)
        self.add_controller(controller)

    def on_save(self, _button: Gtk.Button) -> bool | None:
        pass


class GtkBuilderDialog(GObject.Object):
    dialog_object = NotImplemented
    glade_file = NotImplemented

    __gsignals__ = {
        "destroy": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self, parent: Gtk.Window | None = None, **kwargs: Any):
        # pylint: disable=no-member
        super().__init__()
        ui_filename = os.path.join(datapath.get(), "ui", self.glade_file)
        if not os.path.exists(ui_filename):
            raise ValueError("ui file does not exists: %s" % ui_filename)

        self.builder = Gtk.Builder()
        self.builder.add_from_file(ui_filename)
        self.dialog: Gtk.Dialog = self.builder.get_object(self.dialog_object)

        self.builder.connect_signals(self)
        if parent:
            self.dialog.set_transient_for(parent)
        self.dialog.connect("close-request", self.on_close)
        self.initialize(**kwargs)
        self.dialog.present()

    def initialize(self, **kwargs: Any) -> None:
        """Implement further customizations in subclasses"""

    def present(self) -> None:
        self.dialog.present()

    def on_close(self, *_args: Any) -> bool:
        """Propagate the destroy event after closing the dialog"""
        self.dialog.destroy()
        self.emit("destroy")
        return False

    def on_response(self, _widget: Gtk.Dialog, response: Gtk.ResponseType) -> None:
        if response == Gtk.ResponseType.DELETE_EVENT:
            try:
                self.dialog.hide()
            except AttributeError:
                pass


class AboutDialog(GtkBuilderDialog):
    glade_file = "about-dialog.ui"
    dialog_object = "about_dialog"
    dialog: Gtk.AboutDialog

    def initialize(self, **kwargs: Any) -> None:
        self.dialog.set_version(settings.VERSION)


class NoticeDialog:
    """Display a message to the user."""

    def __init__(self, message_markup: str, secondary: str | None = None, parent: Gtk.Widget | None = None):
        dialog = Adw.MessageDialog(transient_for=get_widget_window(parent))
        dialog.set_heading(message_markup[:256])
        dialog.set_heading_use_markup(True)
        if secondary:
            dialog.set_body(secondary[:256])
        dialog.add_response("ok", _("_OK"))
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        _run_adw_message_dialog(dialog)


class WarningDialog:
    """Display a warning to the user, who responds with whether to proceed, like
    a QuestionDialog."""

    def __init__(self, message_markup: str, secondary: str | None = None, parent: Gtk.Widget | None = None):
        dialog = Adw.MessageDialog(transient_for=get_widget_window(parent))
        dialog.set_heading(message_markup[:256])
        dialog.set_heading_use_markup(True)
        if secondary:
            dialog.set_body(secondary[:256])
        dialog.add_response("cancel", _("_Cancel"))
        dialog.add_response("ok", _("_OK"))
        dialog.set_default_response("ok")
        dialog.set_close_response("cancel")
        response = _run_adw_message_dialog(dialog)
        self.result = Gtk.ResponseType.OK if response == "ok" else Gtk.ResponseType.CANCEL


class ErrorDialog:
    """Display an error message."""

    def __init__(
        self,
        error: str | builtins.BaseException,
        message_markup: str | None = None,
        secondary_markup: str | None = None,
        parent: Gtk.Widget | None = None,
    ):
        def get_message_markup(err: BaseException | str) -> str:
            if isinstance(err, LutrisError):
                return err.message_markup or gtk_safe(str(err))
            else:
                return gtk_safe(str(err))

        if isinstance(error, builtins.BaseException):
            if secondary_markup:
                message_markup = message_markup or get_message_markup(error)
            elif not message_markup:
                message_markup = "<span weight='bold'>%s</span>" % _("Lutris has encountered an error")
                secondary_markup = get_message_markup(error)
        elif not message_markup:
            message_markup = get_message_markup(error)

        dialog = Adw.MessageDialog(transient_for=get_widget_window(parent))
        if message_markup:
            dialog.set_heading(message_markup[:256])
            dialog.set_heading_use_markup(True)
        if secondary_markup:
            dialog.set_body(secondary_markup[:256])
            dialog.set_body_use_markup(True)

        if isinstance(error, BaseException):
            extra_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            copy_button = Gtk.Button(label=_("Copy Details to Clipboard"))
            copy_button.connect("clicked", self.on_copy_clicked, error, dialog)
            extra_box.append(copy_button)
            extra_box.append(self.get_details_expander(error))
            dialog.set_extra_child(extra_box)

        dialog.add_response("ok", _("_OK"))
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        _run_adw_message_dialog(dialog)

    def on_copy_clicked(self, _button: Gtk.Button, error: BaseException, _dialog: Adw.MessageDialog) -> None:
        details = self.format_error(error)
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(details)

    def get_details_expander(self, error: BaseException) -> Gtk.Widget:
        details = self.format_error(error, include_message=False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        label = Gtk.Label(xalign=0.0, wrap=True, margin_start=6, margin_end=6, margin_bottom=6)
        label.set_markup(
            _(
                "You can get support from "
                "<a href='https://github.com/lutris/lutris'>GitHub</a> or "
                "<a href='https://discordapp.com/invite/Pnt5CuY'>Discord</a>. "
                "Make sure to provide the error details;\n"
                "use the 'Copy Details to Clipboard' button to get them."
            )
        )
        box.append(label)

        expander = Gtk.Expander.new(_("Error details"))

        details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        details_box.append(Gtk.Separator())

        details_textview = Gtk.TextView(editable=False)
        details_textview.get_buffer().set_text(details)

        details_scrolledwindow = Gtk.ScrolledWindow(width_request=800, height_request=400)
        details_scrolledwindow.set_child(details_textview)
        details_box.append(details_scrolledwindow)
        expander.set_child(details_box)

        box.append(expander)
        return box

    @staticmethod
    def format_error(error: BaseException, include_message: bool = True) -> str:
        formatted = traceback.format_exception(type(error), error, error.__traceback__)
        if include_message:
            formatted = [str(error), ""] + formatted
        text = "\n".join(formatted).strip()
        log = get_log_contents()

        if log:
            text = f"{text}\n\nLutris log:\n{log}".strip()

        return text


class QuestionDialog:
    """Ask the user a yes or no question."""

    YES = Gtk.ResponseType.YES
    NO = Gtk.ResponseType.NO

    def __init__(self, dialog_settings: Dict[str, Any]) -> None:
        dialog = Adw.MessageDialog()
        dialog.set_heading(dialog_settings["question"])
        dialog.set_heading_use_markup(True)
        dialog.set_title(dialog_settings["title"])
        if "parent" in dialog_settings:
            parent_window = get_widget_window(dialog_settings["parent"])
            if parent_window:
                dialog.set_transient_for(parent_window)
        if "widgets" in dialog_settings:
            widget_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            for widget in dialog_settings["widgets"]:
                widget_box.append(widget)
            dialog.set_extra_child(widget_box)
        dialog.add_response("no", _("_No"))
        dialog.add_response("yes", _("_Yes"))
        dialog.set_default_response("yes")
        dialog.set_close_response("no")
        response = _run_adw_message_dialog(dialog)
        self.result = Gtk.ResponseType.YES if response == "yes" else Gtk.ResponseType.NO


class InputDialog(ModalDialog):
    """Ask the user for a text input"""

    def __init__(self, dialog_settings: dict[str, Any]):
        super().__init__(parent=dialog_settings["parent"])
        self.user_value = ""
        self.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
        self.ok_button = self.add_default_button(_("_OK"), Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.ok_button.set_sensitive(False)
        self.set_title(dialog_settings["title"])
        label = Gtk.Label()
        label.set_markup(dialog_settings["question"])
        content = self.get_content_area()
        label.set_margin_bottom(12)
        content.append(label)
        self.entry = Gtk.Entry(activates_default=True)
        self.entry.connect("changed", self.on_entry_changed)
        self.entry.set_margin_bottom(12)
        content.append(self.entry)
        self.entry.set_text(dialog_settings.get("initial_value") or "")

    def on_entry_changed(self, widget: Gtk.Entry) -> None:
        self.user_value = widget.get_text()
        self.ok_button.set_sensitive(bool(self.user_value))


class ComponentUpdateWaitDialog(ModalDialog):
    """Shown while in-progress Lutris component downloads (runtime, wine, etc.)
    finish before launching a game. Auto-resolves to OK once the download queue
    empties; the user can also override with 'Launch Anyway' or cancel."""

    def __init__(
        self,
        is_queue_empty: Callable[[], bool],
        parent: Gtk.Widget | None = None,
    ):
        from lutris.gui.download_queue import DOWNLOAD_QUEUE_COMPLETED  # noqa: PLC0415

        super().__init__(title=_("Waiting for Lutris components"), parent=parent)
        self.set_default_size(420, -1)

        content = self.get_content_area()
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(18)
        content.set_margin_end(18)

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        heading_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        heading = Gtk.Label(
            label=_("A Lutris component update is in progress."),
            xalign=0,
            wrap=True,
        )
        heading_row.append(heading)

        spinner = Gtk.Spinner()
        spinner.start()
        heading_row.append(spinner)
        column.append(heading_row)

        detail = Gtk.Label(
            label="<small>%s</small>"
            % _("Games can crash or corrupt their Wine prefix if launched before updates finish."),
            use_markup=True,
            xalign=0,
            wrap=True,
        )
        detail.add_css_class("dim-label")
        column.append(detail)

        content.append(column)

        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        self.add_default_button(_("Launch Anyway"), Gtk.ResponseType.OK)

        self._is_queue_empty = is_queue_empty
        self._registration = DOWNLOAD_QUEUE_COMPLETED.register(self._on_queue_done)

    def _on_queue_done(self, *_args: Any) -> None:
        if self._is_queue_empty():
            self.response(Gtk.ResponseType.OK)

    def on_response(self, dialog: Gtk.Dialog, response: Gtk.ResponseType) -> None:
        self._registration.unregister()
        super().on_response(dialog, response)


class DirectoryDialog:
    """Ask the user to select a directory."""

    def __init__(self, message: str, default_path: str | None = None, parent: Gtk.Window | None = None):
        self.folder = None
        dialog = Gtk.FileDialog(title=message)
        if default_path:
            dialog.set_initial_folder(Gio.File.new_for_path(default_path))

        loop = GLib.MainLoop()

        def on_select(_dialog: Gtk.FileDialog, result: GLib.AsyncResult) -> None:
            try:
                folder = _dialog.select_folder_finish(result)
                self.folder = folder.get_path()
            except GLib.GError:
                pass
            loop.quit()

        dialog.select_folder(parent, None, on_select)
        loop.run()


class FileDialog:
    """Ask the user to select a file."""

    def __init__(
        self,
        message: str | None = None,
        default_path: str | None = None,
        mode: str = "open",
        parent: Gtk.Window | None = None,
    ):
        self.filename = None
        if not message:
            message = _("Please choose a file")
        dialog = Gtk.FileDialog(title=message)
        if default_path and os.path.exists(default_path):
            dialog.set_initial_folder(Gio.File.new_for_path(default_path))

        loop = GLib.MainLoop()

        def on_finished(_dialog: Gtk.FileDialog, result: GLib.AsyncResult) -> None:
            try:
                if mode == "save":
                    file = _dialog.save_finish(result)
                else:
                    file = _dialog.open_finish(result)
                self.filename = file.get_path()
            except GLib.GError:
                pass
            loop.quit()

        if mode == "save":
            dialog.save(parent, None, on_finished)
        else:
            dialog.open(parent, None, on_finished)
        loop.run()


class InstallOrPlayDialog(ModalDialog):
    def __init__(self, game_name: str, parent: Gtk.Widget | None = None):
        super().__init__(title=_("%s is already installed") % game_name, parent=parent, border_width=10)
        self.action = "play"
        self.action_confirmed = False

        self.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
        self.add_default_button(_("_OK"), Gtk.ResponseType.OK)

        self.set_size_request(320, 120)
        vbox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)
        self.get_content_area().append(vbox)
        play_button = Gtk.CheckButton(label=_("Launch game"))
        play_button.set_active(True)
        play_button.connect("toggled", self.on_button_toggled, "play")
        vbox.append(play_button)
        install_button = Gtk.CheckButton(label=_("Install the game again"))
        install_button.set_group(play_button)
        install_button.connect("toggled", self.on_button_toggled, "install")
        vbox.append(install_button)

        self.run()

    def on_button_toggled(self, button: Gtk.CheckButton, action: str) -> None:
        if button.get_active():
            logger.debug("Action set to %s", action)
            self.action = action

    def on_response(self, _widget: Gtk.Dialog, response: Gtk.ResponseType) -> None:
        if response == Gtk.ResponseType.CANCEL:
            self.action = None
        super().on_response(_widget, response)


class LaunchConfigSelectDialog(ModalDialog):
    def __init__(self, game: "Game", configs: list["LaunchConfigDict"], title: str, parent: Gtk.Widget | None = None):
        super().__init__(title=title, parent=parent, border_width=10)
        self.config_index = 0
        self.dont_show_again = False

        self.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
        self.add_default_button(_("_OK"), Gtk.ResponseType.OK)

        self.set_size_request(320, 120)
        vbox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)
        self.get_content_area().append(vbox)

        primary_game_radio = Gtk.CheckButton(label=game.name)
        primary_game_radio.set_active(True)
        primary_game_radio.connect("toggled", self.on_button_toggled, 0)
        vbox.append(primary_game_radio)
        for i, config in enumerate(configs):
            _button = Gtk.CheckButton(label=config["name"])
            _button.set_group(primary_game_radio)
            _button.connect("toggled", self.on_button_toggled, i + 1)
            vbox.append(_button)

        dont_show_checkbutton = Gtk.CheckButton(label=_("Do not ask again for this game."))
        dont_show_checkbutton.set_margin_top(6)
        dont_show_checkbutton.connect("toggled", self.on_dont_show_checkbutton_toggled)
        vbox.append(dont_show_checkbutton)

        self.run()

    def on_button_toggled(self, button: Gtk.CheckButton, index: int) -> None:
        if button.get_active():
            self.config_index = index

    def on_dont_show_checkbutton_toggled(self, _button: Gtk.CheckButton) -> None:
        self.dont_show_again = _button.get_active()


class ClientLoginDialog(GtkBuilderDialog):
    glade_file = "dialog-lutris-login.ui"
    dialog_object = "lutris-login"
    __gsignals__ = {
        "connected": (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT,)),
        "cancel": (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT,)),
    }

    def __init__(self, parent: Gtk.Window):
        super().__init__(parent=parent)

        self.parent = parent
        self.username_entry: Gtk.Entry = self.builder.get_object("username_entry")
        self.password_entry: Gtk.Entry = self.builder.get_object("password_entry")

        cancel_button: Gtk.Button = self.builder.get_object("cancel_button")
        cancel_button.connect("clicked", self.on_close)
        connect_button: Gtk.Button = self.builder.get_object("connect_button")
        connect_button.connect("clicked", self.on_connect)
        self.username_entry.connect("activate", self.on_username_entry_activate)
        self.password_entry.connect("activate", self.on_password_entry_activate)

    def get_credentials(self) -> tuple[str, str]:
        username = self.username_entry.get_text()
        password = self.password_entry.get_text()
        return username, password

    def on_username_entry_activate(self, _widget: Gtk.Entry) -> None:
        if all(self.get_credentials()):
            self.on_connect(None)
        else:
            self.password_entry.grab_focus()

    def on_password_entry_activate(self, _widget: Gtk.Entry) -> None:
        if all(self.get_credentials()):
            self.on_connect(None)
        else:
            self.username_entry.grab_focus()

    def on_connect(self, _widget: Gtk.Button | None) -> None:
        username, password = self.get_credentials()
        token = api.connect(username, password)
        if not token:
            NoticeDialog(_("Login failed"), parent=self.parent)
        else:
            self.dialog.destroy()
            self.emit("connected", username)


class InstallerSourceDialog(ModelessDialog):
    """Show install script source"""

    def __init__(self, code: str, name: str, parent: Gtk.Widget):
        super().__init__(title=_("Install script for {}").format(name), parent=parent, border_width=0)
        self.set_default_size(800, 750)

        ok_button = self.add_default_button(_("_OK"), Gtk.ResponseType.OK)
        ok_button.set_margin_end(10)
        ok_button.set_margin_top(10)
        ok_button.set_margin_bottom(10)

        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_hexpand(True)
        self.scrolled_window.set_vexpand(True)

        source_buffer = Gtk.TextBuffer()
        source_buffer.set_text(code)

        source_box = LogTextView(source_buffer, autoscroll=False)

        self.get_content_area().set_margin_start(0)
        self.get_content_area().set_margin_end(0)
        self.get_content_area().set_margin_top(0)
        self.get_content_area().set_margin_bottom(0)
        self.get_content_area().append(self.scrolled_window)
        self.scrolled_window.set_child(source_box)


class HumbleBundleCookiesDialog(ModalDialog):
    def __init__(self, parent: Gtk.Widget | None = None):
        super().__init__(_("Humble Bundle Cookie Authentication"), parent)
        self.cookies_content = None
        self.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
        self.add_default_button(_("_OK"), Gtk.ResponseType.OK)

        self.set_size_request(640, 512)

        vbox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)
        self.get_content_area().append(vbox)
        label = Gtk.Label()
        label.set_markup(
            _(
                "<b>Humble Bundle Authentication via cookie import</b>\n"
                "\n"
                "<b>In Firefox</b>\n"
                "- Install the following extension: "
                "<a href='https://addons.mozilla.org/en-US/firefox/addon/export-cookies-txt/'>"
                "https://addons.mozilla.org/en-US/firefox/addon/export-cookies-txt/"
                "</a>\n"
                "- Open a tab to humblebundle.com and make sure you are logged in.\n"
                "- Click the cookie icon in the top right corner, next to the settings menu\n"
                "- Check 'Prefix HttpOnly cookies' and click 'humblebundle.com'\n"
                "- Open the generated file and paste the contents below. Click OK to finish.\n"
                "- You can delete the cookies file generated by Firefox\n"
                "- Optionally, <a href='https://support.humblebundle.com/hc/en-us/requests/new'>"
                "open a support ticket</a> to ask Humble Bundle to fix their configuration."
            )
        )
        label.set_margin_top(24)
        label.set_margin_bottom(24)
        vbox.append(label)
        self.textview = Gtk.TextView()
        self.textview.set_left_margin(12)
        self.textview.set_right_margin(12)
        scrolledwindow = Gtk.ScrolledWindow()
        scrolledwindow.set_hexpand(True)
        scrolledwindow.set_vexpand(True)
        scrolledwindow.set_child(self.textview)
        scrolledwindow.set_margin_start(24)
        scrolledwindow.set_margin_end(24)
        scrolledwindow.set_margin_bottom(24)
        vbox.append(scrolledwindow)
        self.run()

    def on_response(self, dialog: Gtk.Dialog, response: Gtk.ResponseType) -> None:
        if response == Gtk.ResponseType.CANCEL:
            self.cookies_content = None
        else:
            buffer = self.textview.get_buffer()
            self.cookies_content = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

        super().on_response(dialog, response)


def _call_when_destroyed(self: Gtk.Widget, callback: Callable[[], None]) -> Callable[[], None]:
    handler_id = self.connect("destroy", lambda *x: callback())
    return lambda: self.disconnect(handler_id)


# call_when_destroyed is a utility that hooks up the 'destroy' signal to call your callback,
# and returns a callable that unhooks it. This is used by AsyncJob to avoid sending a callback
# to a destroyed widget.
Gtk.Widget.call_when_destroyed = _call_when_destroyed  # type: ignore[attr-defined]

_error_handlers: dict[type[BaseException], Callable[[BaseException, Gtk.Window], Any]] = {}
TError = TypeVar("TError", bound=BaseException)


def display_error(error: BaseException, parent: Gtk.Widget) -> None:
    """Displays an error in a modal dialog. This can be customized via
    register_error_handler(), but displays an ErrorDialog by default.

    This allows custom error handling to be invoked anywhere that can show an
    ErrorDialog, instead of having to bounce exceptions off the backstop."""
    handler = get_error_handler(type(error))

    if isinstance(parent, Gtk.Window):
        handler(error, parent)
    else:
        handler(error, cast(Gtk.Window, parent.get_root()))


def register_error_handler(error_class: type[TError], handler: Callable[[TError, Gtk.Window], Any]) -> None:
    """Records a function to call to handle errors of a particular class or its subclasses. The
    function is given the error and a parent window, and can display a modal dialog."""
    _error_handlers[error_class] = handler


def get_error_handler(error_class: type[TError]) -> Callable[[TError, Gtk.Window], Any]:
    """Returns the register error handler for an exception class. If none is registered,
    this returns a default handler that shows an ErrorDialog."""
    if not isinstance(error_class, type):
        if isinstance(error_class, BaseException):
            logger.debug("An error was passed where an error class should be passed.")
            error_class = type(error_class)
        else:
            raise ValueError(f"'{error_class}' was passed to get_error_handler, but an error class is required here.")

    if error_class in _error_handlers:
        return _error_handlers[error_class]

    for base_class in inspect.getmro(error_class):
        if base_class in _error_handlers:
            return _error_handlers[base_class]

    return lambda e, p: ErrorDialog(e, parent=p)


def _handle_keyerror(error: KeyError, parent: Gtk.Window) -> None:
    message = _("The key '%s' could not be found.") % error.args[0]
    ErrorDialog(error, message_markup=gtk_safe(message), parent=parent)


register_error_handler(KeyError, _handle_keyerror)
