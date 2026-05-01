import gi
from gi.repository import Gtk

from .mimeapps import _is_flatpak

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")


def _trim_path(path):
    """Remove /run/host prefix from path if running in Flatpak."""
    if _is_flatpak():
        return path.removeprefix("/run/host")
    return path


def _get_exec_base(app):
    """Extract base executable name from app data."""
    exec_line = app.exec or ""
    if exec_line:
        return exec_line.split()[0]
    return ""


def _get_app_group_key(app):
    """Get grouping key for an app (name + executable)."""
    name = app.name or "Unknown"
    exec_base = _get_exec_base(app)
    if not exec_base:
        return (name, app.desktop_id)
    return (name, exec_base)


def _load_app_icon(app_data, icon_theme, size=32):
    """Load icon from app data using Gtk.IconTheme."""
    if app_data.icon_file:
        try:
            img = Gtk.Image.new_from_file(app_data.icon_file)
            img.set_pixel_size(size)
            return img
        except Exception:
            pass

    icon_name = app_data.icon_name or "application-x-executable"
    paintable = icon_theme.lookup_icon(
        icon_name,
        None,
        size,
        1,
        Gtk.TextDirection.NONE,
        Gtk.IconLookupFlags.PRELOAD,
    )
    img = Gtk.Image.new_from_paintable(paintable)
    img.set_pixel_size(size)
    return img


def _load_first_valid_icon(apps, icon_theme, size=32):
    """Load first non-generic icon from a list of apps."""
    for app_data in apps:
        if app_data.icon_file:
            try:
                img = Gtk.Image.new_from_file(app_data.icon_file)
                img.set_pixel_size(size)
                return img
            except Exception:
                pass

        icon_name = app_data.icon_name
        if icon_name and icon_name != "application-x-executable":
            paintable = icon_theme.lookup_icon(
                icon_name,
                None,
                size,
                1,
                Gtk.TextDirection.NONE,
                Gtk.IconLookupFlags.PRELOAD,
            )
            img = Gtk.Image.new_from_paintable(paintable)
            img.set_pixel_size(size)
            return img

    img = Gtk.Image.new_from_icon_name("application-x-executable")
    img.set_pixel_size(size)
    return img


def _setup_dialog_shortcuts(dialog, close_callback):
    """Add Escape and Ctrl+W shortcuts to close a dialog."""
    controller = Gtk.ShortcutController()
    for trigger_str in ["Escape", "<Control>w"]:
        controller.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string(trigger_str),
                action=Gtk.CallbackAction.new(lambda *_: (close_callback(), True)[1]),
            )
        )
    dialog.add_controller(controller)
