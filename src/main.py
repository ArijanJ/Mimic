import os
import sys
import threading

from gi.repository import Adw, Gio, GLib, Gtk

from .dialogs import (
    create_app_details_dialog,
    create_desktop_defaults_dialog,
    create_mime_type_dialog,
)
from .mimeapps import MimeApps, _get_host_prefix, _is_flatpak
from .utils import _format_desktop_environment_name, _get_app_group_key, _show_toast
from .widgets import AppList


@Gtk.Template(resource_path="/io/github/arijanj/Mimic/window.ui")
class MimicWindow(Adw.ApplicationWindow):
    __gtype_name__ = "MimicWindow"

    toast_overlay = Gtk.Template.Child()
    main_stack = Gtk.Template.Child()
    apps_overlay = Gtk.Template.Child()
    apps_search_bar = Gtk.Template.Child()
    apps_scroll = Gtk.Template.Child()
    filetypes_overlay = Gtk.Template.Child()
    filetypes_search_bar = Gtk.Template.Child()
    filetypes_listbox = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.show_all_apps = False
        self.display = None
        self.icon_theme = None

        self.internal_filetypes_rows = []
        self.filetypes_expanders = []

        self.apps_list_widget = None

        self.create_action("focus-search", self._on_focus_search)
        self.create_action("switch-tab", self._on_switch_tab)
        self.show_apps_action = self.create_action(
            "show_all_apps", self._on_show_all_apps
        )
        self.hide_apps_action = self.create_action(
            "hide_all_apps", self._on_hide_all_apps
        )
        self.hide_apps_action.set_enabled(False)

    def create_action(self, name, callback):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        return action

    def setup(self, mime_apps):
        self.mime_apps = mime_apps

        self.display = Gtk.Widget.get_display(self)
        self.icon_theme = Gtk.IconTheme.get_for_display(self.display)

        if _is_flatpak():
            host_prefix = _get_host_prefix()
            for path in [
                os.path.join(host_prefix, "usr", "share", "icons"),
                os.path.join(host_prefix, "usr", "share", "pixmaps"),
                "/var/lib/flatpak/exports/share/icons",
                os.path.expanduser("~/.local/share/flatpak/exports/share/icons"),
                os.path.expanduser("~/.local/share/icons"),
            ]:
                self.icon_theme.add_search_path(path)

        self.apps_list_widget = AppList(
            icon_theme=self.icon_theme,
            mode="grouped",
            show_all_apps=self.show_all_apps,
        )
        self.apps_scroll.set_child(self.apps_list_widget)
        self.apps_list_widget._listbox.set_filter_func(self.filter_apps_row)

        self.apps_search_bar.connect("search-changed", self.on_apps_search_changed)
        self.filetypes_search_bar.connect(
            "search-changed", self.on_filetypes_search_changed
        )

        self._setup_loading_states()
        GLib.idle_add(self._populate_apps_async)
        GLib.idle_add(self._populate_filetypes_async)
        GLib.idle_add(self._maybe_show_desktop_dialogs)

    def _maybe_show_desktop_dialogs(self):
        """Show first-run dialog or desktop defaults toast if applicable."""
        available = self.mime_apps.get_available_desktop_defaults()
        if (
            available
            and self.mime_apps.settings.get_user_value("selected-desktop") is None
        ):
            create_desktop_defaults_dialog(
                self,
                self.mime_apps,
                on_selection_complete=lambda: None,
            )
        elif self.mime_apps.get_selected_desktop():
            desktop_name = _format_desktop_environment_name(
                self.mime_apps.get_selected_desktop()
            )
            _show_toast(self.toast_overlay, f"{desktop_name} defaults loaded")

    def _create_loading_overlay(self, overlay, label_text):
        spinner = Adw.Spinner()
        spinner.set_size_request(64, 64)

        label = Gtk.Label(label=label_text)
        label.add_css_class("title-3")

        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        loading_box.set_halign(Gtk.Align.CENTER)
        loading_box.set_valign(Gtk.Align.CENTER)
        loading_box.append(spinner)
        loading_box.append(label)

        overlay.add_overlay(loading_box)
        return loading_box

    def _setup_loading_states(self):
        self.apps_loading_box = self._create_loading_overlay(
            self.apps_overlay, _("Loading applications…")
        )
        self.filetypes_loading_box = self._create_loading_overlay(
            self.filetypes_overlay, _("Loading file types…")
        )

    def _populate_apps_async(self):
        def load():
            all_apps = self.mime_apps.get_all_desktop_app_infos(
                include_useless_apps=True
            )
            all_apps.sort(key=lambda app: (app.name or "zzzebra").lower())

            grouped = {}
            for app_data in all_apps:
                key = _get_app_group_key(app_data)
                if key not in grouped:
                    grouped[key] = []
                grouped[key].append(app_data)

            GLib.idle_add(self._build_apps_ui, grouped)

        threading.Thread(target=load, daemon=True).start()

    def _build_apps_ui(self, grouped):
        self.apps_list_widget.populate(grouped, self.on_app_row_activated)
        self._grouped_apps = grouped
        self.apps_loading_box.set_visible(False)

    def _populate_filetypes_async(self):
        def load():
            mime_types = self.mime_apps.get_all_mime_types_from_installed_apps()

            grouped = {}
            for mime_type in mime_types:
                category = mime_type.split("/")[0]
                if category not in grouped:
                    grouped[category] = []
                grouped[category].append(mime_type)

            GLib.idle_add(self._build_filetypes_ui, grouped)

        threading.Thread(target=load, daemon=True).start()

    def _build_filetypes_ui(self, grouped):
        category_names = {
            "application": _("Application"),
            "audio": _("Audio"),
            "font": _("Fonts"),
            "image": _("Images"),
            "inode": _("Inode"),
            "message": _("Messages"),
            "model": _("Models"),
            "multipart": _("Multipart"),
            "text": _("Text"),
            "video": _("Video"),
            "x-content": _("Media"),
            "x-epoc": _("Epoc"),
        }

        for category in sorted(grouped.keys()):
            category_name = category_names.get(category, category.capitalize())
            expander = Adw.ExpanderRow()
            expander.set_title(GLib.markup_escape_text(category_name))
            expander.set_subtitle(f"{category}/")
            expander.set_show_enable_switch(False)
            expander._category = category

            for mime_type in sorted(grouped[category]):
                human_readable_description = Gio.content_type_get_description(mime_type)
                row = Adw.ActionRow()
                row.set_title(GLib.markup_escape_text(human_readable_description))
                row.set_subtitle(mime_type)
                row._mime_type = mime_type
                row._expander = expander
                row.set_activatable(True)
                row.connect("activated", self.on_mime_type_row_activated, mime_type)
                expander.add_row(row)
                self.internal_filetypes_rows.append(row)

            self.filetypes_listbox.append(expander)
            self.filetypes_expanders.append(expander)

        self.filetypes_loading_box.set_visible(False)

    def _on_focus_search(self, action, _):
        if self.main_stack.get_visible_child_name() == "apps":
            self.apps_search_bar.grab_focus()
        else:
            self.filetypes_search_bar.grab_focus()

    def _on_switch_tab(self, action, _):
        if self.main_stack.get_visible_child_name() == "apps":
            self.main_stack.set_visible_child_name("filetypes")
        else:
            self.main_stack.set_visible_child_name("apps")

    def _on_show_all_apps(self, action, _):
        self._set_show_all_apps(True)

    def _on_hide_all_apps(self, action, _):
        self._set_show_all_apps(False)

    def _set_show_all_apps(self, show):
        self.show_all_apps = show
        self.apps_list_widget.set_show_all_apps(show)
        self.show_apps_action.set_enabled(not show)
        self.hide_apps_action.set_enabled(show)
        msg = (
            _("Showing apps with no MIME associations")
            if show
            else _("Hiding apps with no MIME associations")
        )
        _show_toast(self.toast_overlay, msg)

    def on_apps_search_changed(self, entry):
        self.apps_list_widget.filter(entry.get_text())

    def on_filetypes_search_changed(self, entry):
        search_text = entry.get_text().lower()

        for expander in self.filetypes_expanders:
            expander.set_expanded(bool(search_text))

            has_visible_rows = False
            for row in self.internal_filetypes_rows:
                if getattr(row, "_expander", None) == expander:
                    if not search_text:
                        row.set_visible(True)
                        has_visible_rows = True
                    else:
                        mime_type = getattr(row, "_mime_type", "").lower()
                        description = row.get_title().lower()
                        visible = search_text in mime_type or search_text in description
                        row.set_visible(visible)
                        if visible:
                            has_visible_rows = True

            expander.set_visible(has_visible_rows)

    def filter_apps_row(self, row):
        return self.apps_list_widget.get_filter_func()(row)

    def on_mime_type_row_activated(self, row, mime_type):
        create_mime_type_dialog(
            row, mime_type, self.mime_apps, self.icon_theme, self._grouped_apps
        )

    def on_app_row_activated(self, row, app_data):
        create_app_details_dialog(
            row,
            app_data,
            self.mime_apps,
            self.icon_theme,
            self.apps_list_widget,
            self._grouped_apps,
        )


class MimicApplication(Adw.Application):
    def on_about_action(self, *args):
        about = Adw.AboutDialog(
            application_name="Mimic",
            application_icon="io.github.arijanj.Mimic",
            developer_name="arijanj",
            version="1.1.2",
            copyright="© 2026 arijanj",
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/arijanj/Mimic",
            issue_url="https://github.com/arijanj/Mimic/issues",
        )
        about.present(self.props.active_window)

    def on_shortcuts_action(self, *args):
        builder = Gtk.Builder.new_from_resource(
            "/io/github/arijanj/Mimic/shortcuts-dialog.ui"
        )
        dialog = builder.get_object("shortcuts_dialog")
        dialog.present(self.props.active_window)

    def on_desktop_defaults_action(self, *args):
        window = self.props.active_window
        if window:
            create_desktop_defaults_dialog(
                window,
                self.mime_apps,
                on_selection_complete=lambda: self._on_desktop_defaults_changed(window),
            )

    def _on_desktop_defaults_changed(self, window):
        self.mime_apps.build_mime_defaults()
        _show_toast(window.toast_overlay, _("Desktop defaults updated"))

    def create_action(self, name, callback, shortcuts=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)

    def __init__(self):
        super().__init__(
            application_id="io.github.arijanj.Mimic",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
            resource_base_path="/io/github/arijanj/Mimic",
        )
        self.create_action("quit", lambda *_: self.quit(), ["<control>q"])
        self.create_action("about", self.on_about_action)
        self.create_action("shortcuts", self.on_shortcuts_action, ["<Control>question"])
        self.create_action("desktop_defaults", self.on_desktop_defaults_action)
        self.settings = Gio.Settings.new("io.github.arijanj.Mimic")
        self.mime_apps = MimeApps(settings=self.settings)
        self.mime_apps.parse()
        self.mime_apps.set_selected_desktop(self.mime_apps.get_selected_desktop())

    def do_activate(self):
        window = self.props.active_window
        if not window:
            window = MimicWindow(application=self)
            window.setup(self.mime_apps)
        window.present()


def main(version):
    """The application's entry point."""

    app = MimicApplication()
    return app.run(sys.argv)
