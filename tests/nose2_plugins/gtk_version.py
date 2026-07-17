"""nose2 plugin that pins GTK/GDK versions before any test module is imported."""

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
