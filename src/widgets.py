import gi
from gi.repository import Adw, Gio, GLib, Gtk

from .utils import _load_app_icon, _trim_path

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")


class AppRow(Adw.ActionRow):
    """Reusable row widget for displaying a desktop application."""

    def __init__(
        self,
        app_data,
        icon_theme,
        subtitle=None,
        subtitle_mode=None,
        size=32,
    ):
        """
        Initialize an AppRow.

        Args:
            app_data: DesktopAppInfo instance
            icon_theme: Gtk.IconTheme for loading icons
            subtitle: Optional custom subtitle string (overrides subtitle_mode)
            subtitle_mode: One of None, "path", "mime_count", "desktop_id"
                - None: No subtitle
                - "path": Shows trimmed desktop file path
                - "mime_count": Shows number of MIME types
                - "desktop_id": Shows the .desktop file ID
            size: Icon size in pixels (default 32)
        """
        super().__init__()

        self.app_data = app_data
        self.icon_theme = icon_theme
        self._size = size

        self.set_title(GLib.markup_escape_text(app_data.name or app_data.desktop_id))

        if subtitle:
            self.set_subtitle(GLib.markup_escape_text(subtitle))
        elif subtitle_mode == "path":
            self.set_subtitle(GLib.markup_escape_text(_trim_path(app_data.path)))
        elif subtitle_mode == "mime_count":
            count = len(app_data.all_mime_types)
            self.set_subtitle(f"{count} MIME type{'s' if count != 1 else ''}")
        elif subtitle_mode == "desktop_id":
            self.set_subtitle(GLib.markup_escape_text(app_data.desktop_id))

        self.add_prefix(_load_app_icon(app_data, icon_theme, size))
        self.set_hexpand(True)

        self._desktop_id = app_data.desktop_id
        self._exec = app_data.exec
        self._subtitle_mode = subtitle_mode
        self._has_mime = False

        self.refresh()

    def refresh(self):
        """Refresh subtitle and visibility based on current app_data state."""
        if self._subtitle_mode == "mime_count":
            count = len(self.app_data.all_mime_types)
            self.set_subtitle(f"{count} MIME type{'s' if count != 1 else ''}")
            self._has_mime = count > 0
        elif self._subtitle_mode == "path":
            self.set_subtitle(GLib.markup_escape_text(_trim_path(self.app_data.path)))
            self._has_mime = bool(self.app_data.all_mime_types)
        elif self._subtitle_mode == "desktop_id":
            self.set_subtitle(GLib.markup_escape_text(self.app_data.desktop_id))
            self._has_mime = bool(self.app_data.all_mime_types)

    def get_mime_count(self):
        """Get the number of MIME types for this app."""
        return len(self.app_data.all_mime_types)


class AppList(Gtk.Box):
    """
    Reusable widget for displaying a list of applications.

    Supports two modes:
    - "grouped": Display apps grouped by name with expanders (for main apps view)
    - "selectable": Display apps with radio buttons for selection (for filetypes dialog)
    """

    def __init__(
        self,
        icon_theme,
        mime_apps=None,
        mime_type=None,
        mode="grouped",
        show_all_apps=False,
        on_add_association=None,
    ):
        """
        Initialize the AppList widget.

        Args:
            icon_theme: Gtk.IconTheme for loading icons
            mime_apps: MimeApps instance (required for "selectable" mode)
            mime_type: MIME type to get apps for (for "selectable" mode)
            mode: One of "grouped" or "selectable"
            show_all_apps: Whether to show apps without MIME associations (for "grouped" mode)
            on_add_association: Optional callback() when add association row is clicked (for "selectable" mode)
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.icon_theme = icon_theme
        self.mime_apps = mime_apps
        self.mime_type = mime_type
        self.mode = mode
        self.show_all_apps = show_all_apps
        self._listbox = None
        self._rows = []
        self._selections = {}
        self._radio_group = None
        self._search_text = ""
        self._on_add_association = on_add_association

        if mode == "selectable" and mime_apps and mime_type:
            self._items = mime_apps.get_apps_for_mime_type(mime_type)
        else:
            self._items = []

        self._build_ui()

        if mode == "selectable":
            self._populate_selectable()

    def _build_ui(self):
        """Build the internal UI structure."""
        self._listbox = Gtk.ListBox()
        self._listbox.add_css_class("boxed-list")
        self._listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._listbox.set_hexpand(True)
        self._listbox.set_vexpand(False)
        self._listbox.set_valign(Gtk.Align.START)
        self.append(self._listbox)
        self.set_vexpand(False)
        self.set_valign(Gtk.Align.START)

    def clear(self):
        """Clear all rows from the list."""
        child = self._listbox.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._listbox.remove(child)
            child = next_child
        self._rows = []
        self._selections = {}
        self._radio_group = None
        self._rows_by_desktop_id = {}

    def update_app_row(self, desktop_id):
        """Update a specific app row's MIME count and visibility."""
        if not hasattr(self, "_rows_by_desktop_id"):
            return

        row_data = self._rows_by_desktop_id.get(desktop_id)
        if not row_data:
            return

        # Handle both single rows and grouped rows (tuple with expander)
        if isinstance(row_data, tuple):
            row, expander = row_data
            row.refresh()

            # Recalculate expander stats from child rows
            total_mime_count = sum(r.get_mime_count() for r in expander._child_rows)
            has_any_mime = any(r._has_mime for r in expander._child_rows)
            expander.set_subtitle(
                f"{total_mime_count} MIME type{'s' if total_mime_count != 1 else ''}"
            )
            expander._has_any_mime_handler = has_any_mime
            expander.set_visible(self.show_all_apps or expander._has_any_mime_handler)
        else:
            # Single app (not in expander)
            row = row_data
            row.refresh()
            row.set_visible(self.show_all_apps or row._has_mime)

    def populate(self, grouped_apps=None, on_activated=None):
        """
        Populate the list based on the mode.

        For "grouped" mode:
            Args:
                grouped_apps: Dict of {(name, exec_base): [app_data, ...]}
                on_activated: Optional callback(row, app_data) when a row is activated

        For "selectable" mode:
            Populates automatically based on mime_type from init.
        """
        self.clear()

        if self.mode == "grouped":
            self._populate_grouped(grouped_apps, on_activated)
        elif self.mode == "selectable":
            self._populate_selectable()

    def _populate_grouped(self, grouped_apps, on_activated):
        """Populate with grouped applications."""
        self._rows_by_desktop_id = {}

        for (name, _), apps_in_group in grouped_apps.items():
            if len(apps_in_group) == 1:
                app_data = apps_in_group[0]
                row = AppRow(app_data, self.icon_theme, subtitle_mode="mime_count")
                row.set_visible(self.show_all_apps or row._has_mime)
                row.set_activatable(True)
                if on_activated:
                    row.connect("activated", on_activated, app_data)
                self._listbox.append(row)
                self._rows.append(row)
                self._rows_by_desktop_id[app_data.desktop_id] = row
            else:
                expander = Adw.ExpanderRow(title=GLib.markup_escape_text(name))
                expander._child_rows = []

                from .utils import _load_first_valid_icon

                expander.add_prefix(
                    _load_first_valid_icon(apps_in_group, self.icon_theme)
                )

                for app_data in apps_in_group:
                    row = AppRow(app_data, self.icon_theme, subtitle_mode="mime_count")
                    row.set_title(GLib.markup_escape_text(app_data.desktop_id))
                    row.set_visible(self.show_all_apps or row._has_mime)
                    row.set_activatable(True)
                    if on_activated:
                        row.connect("activated", on_activated, app_data)
                    expander.add_row(row)
                    expander._child_rows.append(row)
                    self._rows.append(row)
                    self._rows_by_desktop_id[app_data.desktop_id] = (row, expander)

                # Calculate expander stats from child rows
                total_mime_count = sum(r.get_mime_count() for r in expander._child_rows)
                has_any_mime = any(r._has_mime for r in expander._child_rows)
                expander.set_subtitle(
                    f"{total_mime_count} MIME type{'s' if total_mime_count != 1 else ''}"
                )
                expander._has_any_mime_handler = has_any_mime
                expander.set_visible(
                    self.show_all_apps or expander._has_any_mime_handler
                )

                self._listbox.append(expander)
                self._rows.append(expander)

    def _populate_selectable(self):
        """Populate with apps for a MIME type (selection mode with radio buttons)."""
        if not self.mime_apps or not self.mime_type:
            return

        default_info = self.mime_apps.get_default_info_for_mime_type(self.mime_type)
        current_default = default_info["desktop_id"] if default_info else None
        is_implicit = default_info["is_implicit"] if default_info else False

        for desktop_id in self._items:
            app_data = self.mime_apps.get_desktop_app_info_by_id(desktop_id)
            if not app_data:
                continue

            row = AppRow(app_data, self.icon_theme)
            row.set_subtitle(GLib.markup_escape_text(desktop_id))

            is_current = desktop_id == current_default
            if is_current and is_implicit:
                row.set_subtitle(f"{desktop_id}\nSystem default (not explicitly set)")
            elif self.mime_type not in app_data.all_mime_types:
                row.set_subtitle(
                    f"{desktop_id}\nDoes not advertise support for this type"
                )

            radio = Gtk.CheckButton()
            if self._radio_group is None:
                self._radio_group = radio
            else:
                radio.set_group(self._radio_group)

            radio.set_active(is_current)
            radio.set_valign(Gtk.Align.CENTER)
            row.add_suffix(radio)
            row.set_activatable_widget(radio)

            self._selections[desktop_id] = radio
            self._rows.append(row)
            self._listbox.append(row)

        if self._on_add_association:
            add_row = Adw.ActionRow()
            add_row.set_title("Associate an app")
            add_row.set_subtitle("Add another application to handle this file type")

            add_icon = Gtk.Image(icon_name="list-add-symbolic")
            add_icon.set_valign(Gtk.Align.CENTER)
            add_row.add_prefix(add_icon)

            add_row.set_activatable(True)
            add_row.connect("activated", lambda r: self._on_add_association())

            self._listbox.append(add_row)

    def filter(self, search_text):
        """Filter visible rows based on search text (grouped mode only)."""
        if self.mode != "grouped":
            return

        self._search_text = search_text.lower()
        for row in self._rows:
            row._search_text = self._search_text
        if self._listbox:
            self._listbox.invalidate_filter()

    def get_filter_func(self):
        """Return a filter function for the Gtk.ListBox (grouped mode only)."""
        if self.mode != "grouped":
            return lambda row: True

        def filter_func(row):
            if isinstance(row, Adw.ExpanderRow):
                if not hasattr(row, "_search_text"):
                    return True
                search_text = row._search_text
                if not search_text:
                    return True
                for child_row in getattr(row, "_child_rows", []):
                    title = child_row.get_title().lower()
                    exec_text = getattr(child_row, "_exec", "").lower()
                    if search_text in title or search_text in exec_text:
                        return True
                return False
            search_text = getattr(row, "_search_text", "")
            if not search_text:
                return True
            title = row.get_title().lower()
            exec_text = getattr(row, "_exec", "").lower()
            return search_text in title or search_text in exec_text

        return filter_func

    def set_show_all_apps(self, show_all):
        """Toggle showing apps without MIME associations (grouped mode only)."""
        if self.mode != "grouped":
            return

        self.show_all_apps = show_all
        for row in self._rows:
            if isinstance(row, Adw.ExpanderRow):
                row.set_visible(show_all or row._has_any_mime_handler)
            else:
                row.set_visible(show_all or row._has_mime)

    def get_selection(self):
        """Get the selected desktop_id (selectable mode only)."""
        if self.mode != "selectable":
            return None
        for desktop_id, widget in self._selections.items():
            if widget.get_active():
                return desktop_id
        return None


class MimeTypeList(Gtk.Box):
    """
    Reusable widget for displaying and selecting MIME type associations for an app.

    Shows MIME types with checkboxes, and delete buttons for custom associations.
    """

    def __init__(
        self,
        mime_apps,
        desktop_id,
        initial_selection=None,
        on_delete=None,
        on_add=None,
    ):
        """
        Initialize the MimeTypeList widget.

        Args:
            mime_apps: MimeApps instance
            desktop_id: Desktop ID to show MIME associations for
            initial_selection: List of initially selected MIME types
            on_delete: Optional callback(mime_type) when a custom association is deleted
            on_add: Optional callback() when add association button is clicked
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.mime_apps = mime_apps
        self.desktop_id = desktop_id
        self._selections = {}
        self._rows = {}
        self._listbox = None
        self._on_delete = on_delete
        self._on_add = on_add

        self._app_info = mime_apps.get_desktop_app_info_by_id(desktop_id)
        self._items = (
            sorted(
                set(self._app_info.base_mime_types)
                | set(self._app_info.added_mime_types)
            )
            if self._app_info
            else []
        )
        self._active_types = set(initial_selection or [])

        self._build_ui()
        self._populate()

    def _build_ui(self):
        """Build the internal UI structure."""
        self._listbox = Gtk.ListBox()
        self._listbox.add_css_class("boxed-list")
        self._listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._listbox.set_hexpand(True)
        self._listbox.set_vexpand(False)
        self._listbox.set_valign(Gtk.Align.START)
        self.append(self._listbox)
        self.set_vexpand(False)
        self.set_valign(Gtk.Align.START)

    def _create_mime_type_row(self, mime_type, is_active):
        """Create a row for a MIME type with checkbox and optional delete button."""
        description = Gio.content_type_get_description(mime_type)
        is_custom = (
            self._app_info.is_custom_association(mime_type) if self._app_info else False
        )

        row = Adw.ActionRow()
        row.set_title(GLib.markup_escape_text(description))
        row.set_hexpand(True)
        subtitle = mime_type + (" (custom)" if is_custom else "")
        row.set_subtitle(subtitle)

        check = Gtk.CheckButton()
        check.set_active(is_active)
        check.set_valign(Gtk.Align.CENTER)

        if is_custom and self._on_delete:
            delete_btn = Gtk.Button(
                icon_name="user-trash-symbolic", css_classes=["flat"]
            )
            delete_btn.set_valign(Gtk.Align.CENTER)

            def on_delete_clicked(btn, mt=mime_type, cb=check, r=row):
                self._on_delete(mt, cb, r)
                if mt in self._selections:
                    del self._selections[mt]
                if mt in self._rows:
                    del self._rows[mt]

            delete_btn.connect("clicked", on_delete_clicked)
            row.add_suffix(delete_btn)

        check.set_valign(Gtk.Align.CENTER)
        row.add_suffix(check)
        row.set_activatable_widget(check)

        return row, check

    def _create_add_row(self):
        """Create the add association row."""
        add_row = Adw.ActionRow()
        add_row.set_title("Add association")
        add_row.set_subtitle("Add a new MIME type association")

        add_icon = Gtk.Image(icon_name="list-add-symbolic")
        add_icon.set_valign(Gtk.Align.CENTER)
        add_row.add_prefix(add_icon)

        add_row.set_activatable(True)
        add_row.connect("activated", lambda r: self._on_add())

        return add_row

    def _populate(self):
        """Populate the list with MIME types."""
        for mime_type in self._items:
            row, check = self._create_mime_type_row(
                mime_type, mime_type in self._active_types
            )
            self._selections[mime_type] = check
            self._rows[mime_type] = row
            self._listbox.append(row)

        if self._on_add:
            add_row = self._create_add_row()
            self._rows["_add"] = add_row
            self._listbox.append(add_row)

    def get_selections(self):
        """Get all selected MIME types."""
        return [mt for mt, widget in self._selections.items() if widget.get_active()]

    def set_selections(self, items):
        """Set selected MIME types."""
        for item, widget in self._selections.items():
            widget.set_active(item in items)

    def add_item(self, mime_type, is_active=True):
        """Add a new MIME type to the list."""
        if self._on_add and "_add" in self._rows:
            self._listbox.remove(self._rows["_add"])
            del self._rows["_add"]

        # Refresh app_info to pick up the new association
        self._app_info = self.mime_apps.get_desktop_app_info_by_id(self.desktop_id)
        if mime_type not in self._items:
            self._items.append(mime_type)

        row, check = self._create_mime_type_row(mime_type, is_active)
        self._selections[mime_type] = check
        self._rows[mime_type] = row
        self._listbox.append(row)

        if self._on_add:
            add_row = self._create_add_row()
            self._rows["_add"] = add_row
            self._listbox.append(add_row)
