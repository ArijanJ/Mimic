import re
from dataclasses import dataclass

import gi
from gi.repository import Adw, Gio, GLib, Gtk, Pango

from .utils import (
    _load_app_icon,
    _setup_dialog_shortcuts,
    _trim_path,
)
from .widgets import AppList, MimeTypeList

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")


@dataclass
class DialogState:
    """Holds shared state for dialog callbacks."""

    apps_list_widget: object
    grouped_apps: dict
    desktop_id: str
    mime_apps: object


class MimeTypeDialog:
    """Dialog for selecting default application for a MIME type."""

    def __init__(self, parent, mime_type, mime_apps, icon_theme, grouped_apps):
        self.parent = parent
        self.mime_type = mime_type
        self.mime_apps = mime_apps
        self.icon_theme = icon_theme
        self.grouped_apps = grouped_apps
        self.associated_apps = mime_apps.get_apps_for_mime_type(mime_type)
        self.default_info = mime_apps.get_default_info_for_mime_type(mime_type)
        self.current_default = (
            self.default_info["desktop_id"] if self.default_info else None
        )
        self.is_implicit = (
            self.default_info["is_implicit"] if self.default_info else False
        )
        self.app_selection_widget = None
        self.dialog = None

    def _build_content(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_vexpand(False)
        content.set_valign(Gtk.Align.CENTER)

        content.append(
            Gtk.Label(
                label="Select default application:",
                halign=Gtk.Align.CENTER,
                valign=Gtk.Align.START,
            )
        )

        if not self.associated_apps:
            content.append(Gtk.Label(label="No applications found for this file type."))
        else:
            self.app_selection_widget = AppList(
                mime_apps=self.mime_apps,
                icon_theme=self.icon_theme,
                mime_type=self.mime_type,
                mode="selectable",
                on_add_association=self._on_add_association,
            )
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_vexpand(False)
            scrolled.set_valign(Gtk.Align.START)
            scrolled.set_propagate_natural_height(True)
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_size_request(350, -1)
            scrolled.set_max_content_height(520)
            scrolled.set_child(self.app_selection_widget)
            content.append(scrolled)

        return content

    def _on_add_association(self):
        def on_app_selected(desktop_id):
            self.mime_apps.add_association(self.mime_type, desktop_id)
            GLib.idle_add(self.mime_apps.save)

            self.app_selection_widget._items.append(desktop_id)
            self.app_selection_widget.clear()
            self.app_selection_widget._populate_selectable()

        SelectAppDialog(
            self.parent.get_root(),
            self.mime_type,
            self.mime_apps,
            self.icon_theme,
            self.grouped_apps,
            on_app_selected,
        ).present()

    def _on_cancel(self, btn):
        self.dialog.close()

    def _on_apply(self, btn):
        if not self.associated_apps:
            self.dialog.close()
            return

        selected_desktop = (
            self.app_selection_widget.get_selection()
            if self.app_selection_widget
            else None
        )

        if selected_desktop:
            if self.is_implicit:
                self.mime_apps.add_default(self.mime_type, selected_desktop)
            elif selected_desktop != self.current_default:
                if self.current_default:
                    self.mime_apps.remove_default(self.mime_type)
                self.mime_apps.add_default(self.mime_type, selected_desktop)

            GLib.idle_add(self.mime_apps.save)
        self.dialog.close()

    def present(self):
        heading_label = Gtk.Label(
            label=self.mime_type,
            wrap=True,
            xalign=0,
            hexpand=True,
            halign=Gtk.Align.START,
            css_classes=["heading"],
        )
        heading_label.set_max_width_chars(40)

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        title_box.set_hexpand(False)
        title_box.set_halign(Gtk.Align.CENTER)
        title_box.set_valign(Gtk.Align.START)
        title_box.append(heading_label)

        cancel_btn = Gtk.Button(label="Cancel", css_classes=["pill"])
        apply_btn = Gtk.Button(label="Apply", css_classes=["pill", "suggested-action"])

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_hexpand(False)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.set_valign(Gtk.Align.END)
        btn_box.append(cancel_btn)
        btn_box.append(apply_btn)

        dialog_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        dialog_content.set_margin_top(18)
        dialog_content.set_margin_bottom(18)
        dialog_content.set_margin_start(18)
        dialog_content.set_margin_end(18)
        dialog_content.set_vexpand(False)
        dialog_content.set_valign(Gtk.Align.CENTER)
        dialog_content.append(title_box)
        dialog_content.append(self._build_content())
        dialog_content.append(btn_box)

        self.dialog = Adw.Dialog()
        self.dialog.set_follows_content_size(True)
        self.dialog.set_child(dialog_content)

        _setup_dialog_shortcuts(self.dialog, self.dialog.close)

        cancel_btn.connect("clicked", self._on_cancel)
        apply_btn.connect("clicked", self._on_apply)
        self.dialog.present(self.parent.get_root())


class SelectAppDialog:
    """Dialog for selecting an app to associate with a MIME type."""

    def __init__(
        self, parent, mime_type, mime_apps, icon_theme, grouped_apps, on_select
    ):
        self.parent = parent
        self.mime_type = mime_type
        self.mime_apps = mime_apps
        self.icon_theme = icon_theme
        self.grouped_apps = grouped_apps
        self.on_select = on_select
        self.dialog = None

    def _on_app_activated(self, row, app_data):
        self.dialog.close()
        self.on_select(app_data.desktop_id)

    def _on_cancel(self, btn):
        self.dialog.close()

    def present(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)

        heading_label = Gtk.Label(
            label="Select an application:",
            halign=Gtk.Align.CENTER,
            css_classes=["heading"],
        )

        app_list = AppList(
            icon_theme=self.icon_theme,
            mime_apps=self.mime_apps,
            mime_type=self.mime_type,
            mode="grouped",
            show_all_apps=True,
        )
        app_list.populate(self.grouped_apps, self._on_app_activated)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(False)
        scrolled.set_valign(Gtk.Align.START)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_max_content_height(400)
        scrolled.set_child(app_list)

        cancel_btn = Gtk.Button(label="Cancel", css_classes=["pill"])

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_hexpand(False)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.append(cancel_btn)

        content.append(heading_label)
        content.append(scrolled)
        content.append(btn_box)

        self.dialog = Adw.Dialog()
        self.dialog.set_follows_content_size(True)
        self.dialog.set_child(content)
        self.dialog.set_size_request(500, -1)

        cancel_btn.connect("clicked", self._on_cancel)
        self.dialog.present(self.parent.get_root())

        return self.dialog


class AppDetailsDialog:
    """Dialog showing app details and MIME type associations."""

    def __init__(
        self, row, app_data, mime_apps, icon_theme, apps_list_widget, grouped_apps
    ):
        self.row = row
        self.icon_theme = icon_theme
        self.mime_apps = mime_apps
        self.apps_list_widget = apps_list_widget
        self.grouped_apps = grouped_apps
        self.dialog = None
        self.checkboxes = None

        app_info = mime_apps.get_desktop_app_info_by_id(app_data.desktop_id)
        if not app_info:
            return

        self.app_data = app_info
        self.desktop_id = app_info.desktop_id
        self.base_types = set(app_info.base_mime_types)
        self.custom_types = set(app_info.added_mime_types)
        self.supported_types = sorted(self.base_types | self.custom_types)
        self.active_types = mime_apps.get_defaults_for_desktop_file(self.desktop_id)

    def _build_info_box(self):
        executable = self.app_data.exec or "N/A"
        desktop_path = _trim_path(self.app_data.path)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.set_margin_bottom(4)

        executable_label = Gtk.Label(
            label=executable,
            xalign=0.5,
            hexpand=True,
            halign=Gtk.Align.CENTER,
            css_classes=["caption"],
        )
        executable_label.set_ellipsize(Pango.EllipsizeMode.START)
        executable_label.set_max_width_chars(50)
        executable_label.set_tooltip_text(executable)
        info_box.append(executable_label)

        desktop_path_label = Gtk.Label(
            label=desktop_path,
            hexpand=True,
            halign=Gtk.Align.CENTER,
            css_classes=["caption"],
        )
        desktop_path_label.set_ellipsize(Pango.EllipsizeMode.START)
        desktop_path_label.set_max_width_chars(50)
        desktop_path_label.set_tooltip_text(desktop_path)
        info_box.append(desktop_path_label)

        return info_box

    def _on_delete_mime_type(self, mime_type, check, row_widget):
        if check.get_active():
            self.mime_apps.remove_default(mime_type)
        self.mime_apps.remove_association(mime_type, self.desktop_id)
        self.mime_apps.save()
        row_widget.set_visible(False)

        def update_app(app):
            app.added_mime_types = [
                mt for mt in app.added_mime_types if mt != mime_type
            ]
            if mime_type in app.default_mime_types:
                app.default_mime_types.remove(mime_type)
            app.refresh_mime_types()

        self._update_app_and_refresh(update_app)

    def _on_add_association(self):
        add_dialog = AddAssociationDialog(
            self.row,
            self.desktop_id,
            self.mime_apps,
            self.mime_type_list,
            self.apps_list_widget,
            self.grouped_apps,
        )
        add_dialog.present(self.row.get_root())

    def _update_app_and_refresh(self, update_fn):
        for _, apps_in_group in self.grouped_apps.items():
            for app in apps_in_group:
                if app.desktop_id == self.desktop_id:
                    if self.apps_list_widget:
                        update_fn(app)
                        self.apps_list_widget.update_app_row(self.desktop_id)
                    return

    def _on_app_details_applied(self):
        to_add = []
        to_remove = []
        for mime_type, check in self.checkboxes.items():
            was_active = mime_type in self.active_types
            is_active = check.get_active()

            if is_active and not was_active:
                to_add.append(mime_type)
            elif not is_active and was_active:
                to_remove.append(mime_type)

        def do_save():
            if to_add:
                for mt in to_add:
                    self.mime_apps.add_default(mt, self.desktop_id)
            if to_remove:
                for mt in to_remove:
                    self.mime_apps.remove_default(mt)

            try:
                self.mime_apps.save()
            except Exception as e:
                print(f"Error saving: {e}")

            def update_app(app):
                app.default_mime_types = self.mime_apps.defaults.get(self.desktop_id, [])
                app.refresh_mime_types()

            self._update_app_and_refresh(update_app)
            return False

        GLib.idle_add(do_save)

    def _on_cancel(self, btn):
        self.dialog.close()

    def _on_apply(self, btn):
        self._on_app_details_applied()
        self.dialog.close()

    def _build_select_all_button(self, content):
        select_all_btn = Gtk.Button(
            label="Select All Types", hexpand=True, css_classes=["pill"]
        )
        content.append(select_all_btn)

        def update_select_all_label():
            all_checked = all(check.get_active() for check in self.checkboxes.values())
            select_all_btn.set_label("Deselect all" if all_checked else "Select all")

        def on_select_all_clicked(*_):
            all_checked = all(check.get_active() for check in self.checkboxes.values())
            for check in self.checkboxes.values():
                check.set_active(not all_checked)
            update_select_all_label()

        select_all_btn.connect("clicked", on_select_all_clicked)

        for check in self.checkboxes.values():
            check.connect("notify::active", lambda *_: update_select_all_label())

        update_select_all_label()

    def present(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_vexpand(False)
        content.set_valign(Gtk.Align.START)
        content.append(self._build_info_box())

        label = Gtk.Label(
            label=f"{self.app_data.name} is the default for:",
            wrap=True,
            justify=Gtk.Justification.CENTER,
            hexpand=True,
            halign=Gtk.Align.CENTER,
        )
        label.set_max_width_chars(40)
        content.append(label)

        self.mime_type_list = MimeTypeList(
            mime_apps=self.mime_apps,
            desktop_id=self.desktop_id,
            initial_selection=self.active_types,
            on_delete=self._on_delete_mime_type,
            on_add=self._on_add_association,
        )
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(False)
        scrolled.set_valign(Gtk.Align.START)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_max_content_height(550)
        scrolled.set_child(self.mime_type_list)
        content.append(scrolled)
        self.checkboxes = self.mime_type_list._selections

        if len(self.supported_types) >= 5:
            self._build_select_all_button(content)

        heading_label = Gtk.Label(
            label=self.app_data.name,
            wrap=True,
            justify=Gtk.Justification.CENTER,
            halign=Gtk.Align.CENTER,
            css_classes=["heading"],
        )
        heading_label.set_max_width_chars(30)

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        title_box.set_hexpand(True)
        title_box.set_halign(Gtk.Align.CENTER)
        title_box.append(_load_app_icon(self.app_data, self.icon_theme))
        title_box.append(heading_label)

        cancel_btn = Gtk.Button(label="Cancel", css_classes=["pill"])
        apply_btn = Gtk.Button(label="Apply", css_classes=["pill", "suggested-action"])

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_hexpand(True)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.append(cancel_btn)
        btn_box.append(apply_btn)

        dialog_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        dialog_content.set_margin_top(24)
        dialog_content.set_margin_bottom(24)
        dialog_content.set_margin_start(24)
        dialog_content.set_margin_end(24)
        dialog_content.append(title_box)
        dialog_content.append(content)
        dialog_content.append(btn_box)

        self.dialog = Adw.Dialog()
        self.dialog.set_follows_content_size(True)
        self.dialog.set_child(dialog_content)
        self.dialog.set_size_request(450, -1)

        _setup_dialog_shortcuts(self.dialog, self.dialog.close)

        cancel_btn.connect("clicked", self._on_cancel)
        apply_btn.connect("clicked", self._on_apply)
        self.dialog.present(self.row.get_root())


class AddAssociationDialog:
    """Dialog for adding a new MIME type association."""

    def __init__(
        self, row, desktop_id, mime_apps, mime_type_list, apps_list_widget, grouped_apps
    ):
        self.row = row
        self.desktop_id = desktop_id
        self.mime_apps = mime_apps
        self.mime_type_list = mime_type_list
        self.apps_list_widget = apps_list_widget
        self.grouped_apps = grouped_apps
        self.dialog = None
        self.add_apply_btn = None

    def _validate_entry(self, entry, status_label, revealer):
        text = entry.get_text().strip()
        if not text:
            revealer.set_reveal_child(False)
            self.add_apply_btn.set_sensitive(False)
            return
        if re.match(r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9.+_-]+$", text):
            desc = Gio.content_type_get_description(text)
            status_label.set_text(desc)
            status_label.remove_css_class("error")
            status_label.add_css_class("success")
            revealer.set_reveal_child(True)
            self.add_apply_btn.set_sensitive(True)
        else:
            status_label.set_text("Invalid MIME format")
            status_label.remove_css_class("success")
            status_label.add_css_class("error")
            revealer.set_reveal_child(True)
            self.add_apply_btn.set_sensitive(False)

    def _on_add_association_saved(self, text, set_as_default):
        try:
            self.mime_apps.save()

            def update_app(app):
                if text not in app.added_mime_types:
                    app.added_mime_types.append(text)
                if set_as_default and text not in app.default_mime_types:
                    app.default_mime_types.append(text)
                app.refresh_mime_types()

            for _, apps_in_group in self.grouped_apps.items():
                for app in apps_in_group:
                    if app.desktop_id == self.desktop_id:
                        if self.apps_list_widget:
                            update_app(app)
                            self.apps_list_widget.update_app_row(self.desktop_id)
                        return
        except Exception as e:
            print(f"Error while saving: {e}")

    def _on_cancel(self, btn):
        self.dialog.close()

    def _on_apply(self, entry):
        if not self.add_apply_btn.get_sensitive():
            return
        text = entry.get_text().strip()
        if text and re.match(r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9.+_-]+$", text):
            set_as_default_switch = self.dialog._set_as_default_switch
            set_as_default = set_as_default_switch.get_active()

            self.mime_apps.add_association(text, self.desktop_id)
            if set_as_default:
                self.mime_apps.add_default(text, self.desktop_id)

            GLib.idle_add(lambda: self._on_add_association_saved(text, set_as_default))
            self.dialog.close()
            self.mime_type_list.add_item(text, set_as_default)
        self.dialog.close()

    def present(self, parent):
        entry = Gtk.Entry()
        entry.set_placeholder_text("e.g. image/png")
        entry.set_hexpand(True)
        entry.set_margin_top(0)
        entry.set_margin_bottom(0)
        entry.set_margin_start(12)
        entry.set_margin_end(12)

        status_label = Gtk.Label(css_classes=["caption"])
        status_label.set_halign(Gtk.Align.CENTER)

        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.FADE_SLIDE_UP)
        revealer.set_transition_duration(200)
        revealer.set_child(status_label)

        entry.connect(
            "changed", lambda e: self._validate_entry(e, status_label, revealer)
        )

        set_as_default_switch = Gtk.Switch()
        set_as_default_switch.set_active(True)
        set_as_default_switch.set_valign(Gtk.Align.CENTER)

        set_as_default_row = Adw.ActionRow(title="Set as default")
        set_as_default_row.add_suffix(set_as_default_switch)
        set_as_default_row.set_activatable_widget(set_as_default_switch)

        self.add_apply_btn = Gtk.Button(
            label="Add", css_classes=["pill", "suggested-action"]
        )
        self.add_apply_btn.set_sensitive(False)

        add_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_btn_box.set_hexpand(True)
        add_btn_box.set_halign(Gtk.Align.CENTER)
        add_btn_box.append(Gtk.Button(label="Cancel", css_classes=["pill"]))
        add_btn_box.append(self.add_apply_btn)

        add_dialog_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        add_dialog_content.set_margin_top(24)
        add_dialog_content.set_margin_bottom(24)
        add_dialog_content.set_margin_start(24)
        add_dialog_content.set_margin_end(24)
        add_dialog_content.append(
            Gtk.Label(
                label="Enter MIME type:",
                halign=Gtk.Align.CENTER,
                css_classes=["heading"],
            )
        )
        add_dialog_content.append(entry)
        add_dialog_content.append(revealer)
        add_dialog_content.append(set_as_default_row)
        add_dialog_content.append(add_btn_box)

        self.dialog = Adw.Dialog()
        self.dialog.set_follows_content_size(True)
        self.dialog._set_as_default_switch = set_as_default_switch
        self.dialog.set_child(add_dialog_content)

        _setup_dialog_shortcuts(self.dialog, self.dialog.close)

        add_btn_box.get_first_child().connect("clicked", self._on_cancel)
        self.add_apply_btn.connect("clicked", lambda _: self._on_apply(entry))
        entry.connect("activate", lambda e: self._on_apply(e))

        self.dialog.present(parent.get_root())

        return self.dialog


def create_mime_type_dialog(parent, mime_type, mime_apps, icon_theme, grouped_apps):
    """Create dialog for selecting default application for a MIME type."""
    MimeTypeDialog(parent, mime_type, mime_apps, icon_theme, grouped_apps).present()


def create_app_details_dialog(
    row, app_data, mime_apps, icon_theme, apps_list_widget, grouped_apps
):
    """Create dialog showing app details and MIME type associations."""
    AppDetailsDialog(
        row, app_data, mime_apps, icon_theme, apps_list_widget, grouped_apps
    ).present()
