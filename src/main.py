import os
import sys
import threading

import gi
from gi.repository import Adw, Gio, GLib, Gtk

from .dialogs import create_app_details_dialog, create_mime_type_dialog
from .mimeapps import MimeApps, _get_host_prefix, _is_flatpak
from .utils import _get_app_group_key
from .widgets import AppList

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

Adw.init()


class MimicApplication(Adw.Application):
    def on_about_action(self, *args):
        about = Adw.AboutDialog(
            application_name="Mimic",
            application_icon="io.github.arijanj.Mimic",
            developer_name="arijanj",
            version="0.1.0",
            copyright="© 2026 arijanj",
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/arijanj/Mimic",
            issue_url="https://github.com/arijanj/Mimic/issues",
        )
        about.present(self.props.active_window)

    def on_shortcuts_action(self, *args):
        dialog = Adw.ShortcutsDialog()
        dialog.set_title("Keyboard Shortcuts")

        sections = [
            (
                "General",
                [
                    ("<Control>q", "Quit"),
                    ("<Control>f", "Search"),
                ],
            ),
            (
                "Navigation",
                [
                    ("<Control>Tab", "Switch Tab"),
                    ("Escape", "Close Dialog"),
                ],
            ),
        ]

        for title, shortcuts in sections:
            section = Adw.ShortcutsSection(title=title)
            for accel, shortcut_title in shortcuts:
                section.add(Adw.ShortcutsItem(title=shortcut_title, accelerator=accel))
            dialog.add(section)

        dialog.present()

    def on_toggle_show_all_apps(self, action, _):
        self.show_all_apps = not self.show_all_apps
        self.apps_list_widget.set_show_all_apps(self.show_all_apps)
        label = "_Hide Other Apps" if self.show_all_apps else "_Show Other Apps"
        self.menu_model.remove(1)
        self.menu_model.insert_item(
            1, Gio.MenuItem.new(label, "app.toggle_show_all_apps")
        )
        msg = (
            "Showing apps with no MIME associations"
            if self.show_all_apps
            else "Hiding apps with no MIME associations"
        )
        toast = Adw.Toast(title=msg, timeout=2)
        self.toast_overlay.add_toast(toast)

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
            resource_base_path="/io.github.arijanj.Mimic",
        )
        self.create_action("quit", lambda *_: self.quit(), ["<control>q"])
        self.create_action("about", self.on_about_action)
        self.create_action("shortcuts", self.on_shortcuts_action, ["<Control>question"])
        self.create_action("toggle_show_all_apps", self.on_toggle_show_all_apps)

        self.show_all_apps = False
        self.display = None
        self.icon_theme = None
        self.mime_apps = MimeApps()
        self.mime_apps.parse()

        self.internal_filetypes_rows = []
        self.filetypes_listbox = None
        self.filetypes_expanders = []

        self.apps_listbox = None
        self.apps_list_widget = None

    def do_activate(self):
        window = self.props.active_window
        if not window:
            window = Adw.ApplicationWindow(application=self)

        window.set_title("Mimic")
        window.set_default_size(500, 700)

        window.present()

        self.display = Gtk.Widget.get_display(window)
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

        main_stack = Adw.ViewStack()
        main_stack.set_margin_start(12)
        main_stack.set_margin_end(12)
        main_stack.set_margin_bottom(12)
        main_stack.set_margin_top(9)

        apps_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        apps_search_bar = Gtk.SearchEntry()
        apps_search_bar.set_placeholder_text("Search applications…")
        apps_search_bar.connect("search-changed", self.on_apps_search_changed)
        apps_page.append(apps_search_bar)
        self.apps_search_bar = apps_search_bar

        self.apps_list_widget = AppList(
            icon_theme=self.icon_theme,
            mode="grouped",
            show_all_apps=self.show_all_apps,
        )

        scrolled_apps_container = Gtk.ScrolledWindow()
        scrolled_apps_container.set_vexpand(True)
        scrolled_apps_container.set_child(self.apps_list_widget)
        apps_page.append(scrolled_apps_container)

        self.apps_listbox = self.apps_list_widget._listbox
        self.apps_listbox.set_filter_func(self.filter_apps_row)

        apps_overlay = Gtk.Overlay()
        apps_overlay.set_child(apps_page)
        self.apps_overlay = apps_overlay

        # --------------------------------------------------------------------- #

        filetypes_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        filetypes_search_bar = Gtk.SearchEntry()
        filetypes_search_bar.set_placeholder_text("Search mime types…")
        filetypes_search_bar.connect("search-changed", self.on_filetypes_search_changed)
        filetypes_page.append(filetypes_search_bar)
        self.filetypes_search_bar = filetypes_search_bar

        filetypes_listbox = Gtk.ListBox()
        filetypes_listbox.add_css_class("boxed-list")
        filetypes_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.filetypes_listbox = filetypes_listbox

        scrolled_filetypes_container = Gtk.ScrolledWindow()
        scrolled_filetypes_container.set_vexpand(True)
        scrolled_filetypes_container.set_child(filetypes_listbox)
        filetypes_page.append(scrolled_filetypes_container)

        filetypes_overlay = Gtk.Overlay()
        filetypes_overlay.set_child(filetypes_page)
        self.filetypes_overlay = filetypes_overlay

        main_stack.add_titled_with_icon(
            apps_overlay, "apps", "Applications", "system-run"
        )
        main_stack.add_titled_with_icon(
            filetypes_overlay, "filetypes", "Filetypes", "text-x-generic"
        )

        # --------------------------------------------------------------------- #

        self.menu_model = Gio.Menu()
        self.menu_model.append("_Keyboard Shortcuts", "app.shortcuts")
        self.menu_model.append("_Show Other Apps", "app.toggle_show_all_apps")
        self.menu_model.append("_About Mimic", "app.about")

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_button.set_menu_model(self.menu_model)

        view_switcher_title = Adw.ViewSwitcherTitle(stack=main_stack)

        header_bar = Adw.HeaderBar()
        header_bar.set_title_widget(view_switcher_title)
        header_bar.pack_end(menu_button)

        main_layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_layout.append(header_bar)
        main_layout.append(main_stack)

        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(main_layout)

        window.set_content(self.toast_overlay)
        window.present()

        self._setup_shortcuts(window, main_stack, apps_overlay, filetypes_overlay)

        self._setup_loading_states(apps_page, filetypes_page)
        GLib.idle_add(self._populate_apps_listbox_async)
        GLib.idle_add(self._populate_filetypes_listbox_async)

    def _setup_shortcuts(self, window, stack, apps_overlay, filetypes_overlay):
        controller = Gtk.ShortcutController()

        controller.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string("<Control>f"),
                action=Gtk.CallbackAction.new(
                    lambda *_: (
                        self.apps_search_bar.grab_focus()
                        if stack.get_visible_child() == apps_overlay
                        else self.filetypes_search_bar.grab_focus(),
                        True,
                    )[1]
                ),
            )
        )

        for trigger in ["<Control>Tab", "<Control><Shift>Tab"]:
            controller.add_shortcut(
                Gtk.Shortcut(
                    trigger=Gtk.ShortcutTrigger.parse_string(trigger),
                    action=Gtk.CallbackAction.new(
                        lambda *_: (
                            stack.set_visible_child(
                                filetypes_overlay
                                if stack.get_visible_child() == apps_overlay
                                else apps_overlay
                            ),
                            True,
                        )[1]
                    ),
                )
            )

        window.add_controller(controller)

    def _create_loading_overlay(self, overlay, label_text):
        """Create a loading spinner overlay for a page."""
        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        loading_box.set_halign(Gtk.Align.CENTER)
        loading_box.set_valign(Gtk.Align.CENTER)

        spinner = Adw.Spinner()
        spinner.set_size_request(48, 48)
        loading_box.append(spinner)

        label = Gtk.Label(label=label_text)
        label.add_css_class("heading")
        loading_box.append(label)

        overlay.add_overlay(loading_box)
        return loading_box, spinner

    def _setup_loading_states(self, apps_page, filetypes_page):
        self.apps_loading_box, self.apps_spinner = self._create_loading_overlay(
            self.apps_overlay, "Loading applications…"
        )

        self.filetypes_loading_box, self.filetypes_spinner = (
            self._create_loading_overlay(self.filetypes_overlay, "Loading file types…")
        )

    def _populate_apps_listbox_async(self):
        def load_apps():
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

        threading.Thread(target=load_apps, daemon=True).start()

    def _build_apps_ui(self, grouped):
        self.apps_list_widget.populate(grouped, self.on_app_row_activated)
        self._grouped_apps = grouped

        if hasattr(self, "apps_loading_box"):
            self.apps_loading_box.set_visible(False)

    # --------------------------------------------------------------------- #

    def _populate_filetypes_listbox_async(self):
        def load_filetypes():
            mime_types = self.mime_apps.get_all_mime_types_from_installed_apps()

            grouped = {}
            for mime_type in mime_types:
                category = mime_type.split("/")[0]
                if category not in grouped:
                    grouped[category] = []
                grouped[category].append(mime_type)

            GLib.idle_add(self._build_filetypes_ui, grouped)

        threading.Thread(target=load_filetypes, daemon=True).start()

    def _build_filetypes_ui(self, grouped):
        category_names = {
            "application": "Application",
            "audio": "Audio",
            "font": "Fonts",
            "image": "Images",
            "inode": "Inode",
            "message": "Messages",
            "model": "Models",
            "multipart": "Multipart",
            "text": "Text",
            "video": "Video",
            "x-content": "Media",
            "x-epoc": "Epoc",
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

        if hasattr(self, "filetypes_loading_box"):
            self.filetypes_loading_box.set_visible(False)

    def on_apps_search_changed(self, entry):
        self.apps_list_widget.filter(entry.get_text())

    def filter_apps_row(self, row):
        return self.apps_list_widget.get_filter_func()(row)

    def on_filetypes_search_changed(self, entry):
        search_text = entry.get_text().lower()

        for expander in self.filetypes_expanders:
            if search_text:
                expander.set_expanded(True)
            else:
                expander.set_expanded(False)

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


def main(version):
    """The application's entry point."""

    app = MimicApplication()
    return app.run(sys.argv)
