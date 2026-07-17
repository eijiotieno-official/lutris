from gi.repository import GObject, Gtk

from lutris.gui.installer.script_box import InstallerScriptBox


class InstallerPicker(Gtk.ListBox):
    """List box to pick between several installers"""

    __gsignals__ = {"installer-selected": (GObject.SIGNAL_RUN_FIRST, None, (str,))}

    def __init__(self, scripts):
        super().__init__()
        revealed = True
        for script in scripts:
            row = Gtk.ListBoxRow()
            row.set_child(InstallerScriptBox(script, parent=self, revealed=revealed))
            self.append(row)
            revealed = False
        self.connect("row-selected", self.on_activate)

    @staticmethod
    def on_activate(widget, row):
        for list_row in widget:
            script_box = list_row.get_first_child()
            if script_box:
                script_box.reveal(False)
        installer_row = row.get_first_child()
        if installer_row:
            installer_row.reveal()
