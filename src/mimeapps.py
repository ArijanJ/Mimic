import configparser
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DesktopAppInfo:
    """Represents a desktop application with its MIME type associations."""

    desktop_id: str
    path: str
    name: str
    icon_name: str
    exec: str
    icon_file: Optional[str] = None
    base_mime_types: list = field(default_factory=list)
    added_mime_types: list = field(default_factory=list)
    default_mime_types: list = field(default_factory=list)
    _all_mime_types: list = field(default_factory=list, init=False, repr=False)

    def __post_init__(self):
        """Compute cached all_mime_types after initialization."""
        self._compute_all_mime_types()

    def _compute_all_mime_types(self):
        """Recompute the cached all_mime_types."""
        self._all_mime_types = list(
            dict.fromkeys(
                self.base_mime_types + self.added_mime_types + self.default_mime_types
            )
        )

    @property
    def all_mime_types(self) -> list:
        """All MIME types this app handles (base + added + default)."""
        return self._all_mime_types

    def refresh_mime_types(self):
        """Refresh mime type lists and recompute cache. Call after modifying mime lists."""
        self._compute_all_mime_types()

    def is_custom_association(self, mime_type: str) -> bool:
        """Check if a MIME type is only in added associations, not in the desktop file."""
        return (
            mime_type in self.added_mime_types and mime_type not in self.base_mime_types
        )


def _is_flatpak() -> bool:
    return os.path.exists("/.flatpak-info") or "FLATPAK_ID" in os.environ


def _get_host_prefix() -> str:
    if _is_flatpak():
        return "/run/host"
    return ""


class MimeApps:
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.expanduser("~/.config/mimeapps.list")
        self.config_path = config_path
        self.defaults: dict = {}
        self.added_associations: dict = {}
        self._other_sections: dict = {}
        self._mime_associations: Optional[dict] = None
        self._mime_defaults_effective: Optional[dict] = None

    def _get_applications_dirs(self) -> list:
        """Get all applications directories in XDG order."""
        host = _get_host_prefix()

        xdg_data_dirs = os.environ.get(
            "XDG_DATA_DIRS", "/usr/local/share:/usr/share"
        ).split(":")

        dirs = [
            os.path.expanduser("~/.local/share/applications"),
            os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
            os.path.join(host, "usr", "share", "applications"),
            os.path.join(host, "usr", "local", "share", "applications"),
            "/var/lib/flatpak/exports/share/applications",
            "/var/lib/snapd/desktop/applications/",
            "/run/current-system/sw/share/applications",  # NixOS (symlinks in here)
        ]

        for d in xdg_data_dirs:
            dirs.append(os.path.join(d, "applications"))

        return [d for d in dirs if os.path.isdir(d)]

    def _get_desktop_file_paths(self) -> dict:
        """Get all desktop file paths, handling symlinks."""
        desktop_file_paths = {}
        host = _get_host_prefix()

        for apps_dir in self._get_applications_dirs():
            if not os.path.isdir(apps_dir):
                continue
            for filename in os.listdir(apps_dir):
                if filename.endswith(".desktop") and filename not in desktop_file_paths:
                    path = os.path.join(apps_dir, filename)
                    if os.path.islink(path):
                        link_target = os.readlink(path)
                        if not os.path.isabs(link_target):
                            link_target = os.path.join(apps_dir, link_target)
                        if (
                            host
                            and not link_target.startswith("/run/host")
                            and not link_target.startswith("/var/")
                            and not link_target.startswith("/nix/store")
                        ):
                            link_target = os.path.join(host, link_target.lstrip("/"))
                        path = link_target
                    if os.path.isfile(path):
                        desktop_file_paths[filename] = path

        return desktop_file_paths

    def _parse_desktop_file(self, path: str) -> Optional[dict]:
        """Parse a desktop file and return all relevant data."""
        config = configparser.ConfigParser(interpolation=None)
        try:
            config.read(path)
        except Exception:
            return None

        if not config.has_section("Desktop Entry"):
            return None

        entry = config["Desktop Entry"]

        name = entry.get("Name", os.path.basename(path))
        icon_name = entry.get("Icon", "application-x-executable")
        exec_line = entry.get("Exec", "")

        mime_types = []
        if config.has_option("Desktop Entry", "MimeType"):
            value = config.get("Desktop Entry", "MimeType")
            mime_types = [m.strip() for m in value.split(";") if m.strip()]

        return {
            "desktop_id": os.path.basename(path),
            "path": path,
            "name": name,
            "icon_name": icon_name,
            "exec": exec_line,
            "mime_types": mime_types,
        }

    def _load_icon(self, icon_name: str, icon_file: Optional[str] = None):
        """Load icon as file path or themed icon name."""
        if not os.path.isabs(icon_name):
            # Themed icon - return the name for later lookup
            return icon_name, None

        icon_path = icon_name
        host = _get_host_prefix()
        if host and not icon_path.startswith("/run/host"):
            remapped = os.path.join(host, icon_path.lstrip("/"))
            if os.path.exists(remapped):
                icon_path = remapped

        if not os.path.exists(icon_path):
            return "application-x-executable", None

        supported_exts = {".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp"}
        if any(icon_path.lower().endswith(ext) for ext in supported_exts):
            return None, icon_path

        return "application-x-executable", None

    def get_associations_for_desktop_file(self, desktop_id: str) -> list:
        """Get all MIME types associated with a desktop file via Added Associations."""
        return [mt for mt, ids in self.added_associations.items() if desktop_id in ids]

    def build_mime_associations(self) -> dict:
        """Build mime-to-apps mapping from mimeinfo.cache and desktop files."""
        mime_to_apps = {}

        for apps_dir in self._get_applications_dirs():
            cache_path = os.path.join(apps_dir, "mimeinfo.cache")
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r") as f:
                        for line in f:
                            line = line.strip()
                            if not line or "=" not in line:
                                continue
                            mime_type, desktop_list = line.split("=", 1)
                            desktop_ids = [
                                d.strip() for d in desktop_list.split(";") if d.strip()
                            ]
                            if desktop_ids:
                                if mime_type not in mime_to_apps:
                                    mime_to_apps[mime_type] = []
                                for desktop_id in desktop_ids:
                                    if desktop_id not in mime_to_apps[mime_type]:
                                        mime_to_apps[mime_type].append(desktop_id)
                except Exception:
                    pass

        desktop_file_paths = self._get_desktop_file_paths()
        for desktop_id, path in desktop_file_paths.items():
            data = self._parse_desktop_file(path)
            if data is None:
                continue
            for mime_type in data["mime_types"]:
                if mime_type not in mime_to_apps:
                    mime_to_apps[mime_type] = []
                if data["desktop_id"] not in mime_to_apps[mime_type]:
                    mime_to_apps[mime_type].append(data["desktop_id"])

        # Merge in added associations from mimeapps.list
        for mime_type, desktop_ids in self.added_associations.items():
            if mime_type not in mime_to_apps:
                mime_to_apps[mime_type] = []
            for desktop_id in desktop_ids:
                if desktop_id not in mime_to_apps[mime_type]:
                    mime_to_apps[mime_type].append(desktop_id)

        self._mime_associations = mime_to_apps
        return mime_to_apps

    def build_mime_defaults(self) -> dict:
        """Build effective defaults with fallback to first association."""
        self._ensure_associations_cache()

        desktop_file_paths = self._get_desktop_file_paths()
        mime_defaults_effective = {}

        for desktop_id, mime_types in self.defaults.items():
            if desktop_id not in desktop_file_paths:
                continue
            for mime_type in mime_types:
                if mime_type not in mime_defaults_effective:
                    mime_defaults_effective[mime_type] = {
                        "desktop_id": desktop_id,
                        "is_implicit": False,
                    }

        for mime_type, apps in self._mime_associations.items():
            if mime_type in mime_defaults_effective:
                continue
            if apps:
                mime_defaults_effective[mime_type] = {
                    "desktop_id": apps[0],
                    "is_implicit": True,
                }

        self._mime_defaults_effective = mime_defaults_effective
        return mime_defaults_effective

    def parse(self) -> None:
        """Parse the user's mimeapps.list file."""
        self.defaults = {}
        self.added_associations = {}
        self._other_sections = {}
        self._mime_associations = None
        self._mime_defaults_effective = None

        if not os.path.exists(self.config_path):
            return

        config = configparser.ConfigParser(interpolation=None)
        try:
            config.read(self.config_path)
            if config.has_section("Default Applications"):
                for mime_type, desktop_file in config.items("Default Applications"):
                    desktop_id = desktop_file.strip().split(";")[0]
                    if desktop_id not in self.defaults:
                        self.defaults[desktop_id] = []
                    self.defaults[desktop_id].append(mime_type)
            if config.has_section("Added Associations"):
                for mime_type, value in config.items("Added Associations"):
                    desktop_ids = [d.strip() for d in value.split(";") if d.strip()]
                    self.added_associations[mime_type] = desktop_ids

            # Preserve other sections
            for section in config.sections():
                if section not in ("Default Applications", "Added Associations"):
                    self._other_sections[section] = dict(config.items(section))
        except Exception as e:
            print(f"Error parsing mimeapps.list: {e}")

    def get_defaults_for_desktop_file(self, desktop_id: str) -> list:
        """Get mime types this desktop file is the default for."""
        return self.defaults.get(desktop_id, [])

    def _ensure_associations_cache(self) -> None:
        """Ensure the associations cache is built."""
        if self._mime_associations is None:
            self.build_mime_associations()

    def _ensure_defaults_cache(self) -> None:
        """Ensure the defaults cache is built."""
        if self._mime_defaults_effective is None:
            self.build_mime_defaults()

    def get_default_for_mime_type(self, mime_type: str) -> Optional[str]:
        """Get the default desktop ID for a mime type."""
        self._ensure_defaults_cache()
        result = self._mime_defaults_effective.get(mime_type)
        return result["desktop_id"] if result else None

    def get_default_info_for_mime_type(self, mime_type: str) -> Optional[dict]:
        """Get default info dict with desktop_id and is_implicit flag."""
        self._ensure_defaults_cache()
        return self._mime_defaults_effective.get(mime_type)

    def get_apps_for_mime_type(self, mime_type: str) -> list:
        """Get all apps that can handle a mime type."""
        self._ensure_associations_cache()
        apps = self._mime_associations.get(mime_type, []).copy()

        default_app = self.get_default_for_mime_type(mime_type)
        if default_app and default_app not in apps:
            apps.insert(0, default_app)

        return apps

    def get_all_mime_types_from_installed_apps(self) -> list:
        """Get all known mime types from installed applications."""
        self._ensure_associations_cache()
        return sorted(self._mime_associations.keys())

    def _clear_default_for_mime_type(self, mime_type: str) -> None:
        """Clear existing default for a mime type."""
        for existing_id in list(self.defaults.keys()):
            if mime_type in self.defaults[existing_id]:
                self.defaults[existing_id].remove(mime_type)
                if not self.defaults[existing_id]:
                    del self.defaults[existing_id]

    def add_default(self, mime_type: str, desktop_id: str) -> None:
        """Set a desktop as the default for a mime type."""
        self._clear_default_for_mime_type(mime_type)

        if desktop_id not in self.defaults:
            self.defaults[desktop_id] = []
        if mime_type not in self.defaults[desktop_id]:
            self.defaults[desktop_id].append(mime_type)

    def remove_default(self, mime_type: str) -> None:
        """Remove default association for a mime type."""
        self._clear_default_for_mime_type(mime_type)

    def _add_association(self, mime_type: str, desktop_id: str) -> None:
        """Add a desktop to a mime type's added associations."""
        if mime_type not in self.added_associations:
            self.added_associations[mime_type] = [desktop_id]
        elif desktop_id not in self.added_associations[mime_type]:
            self.added_associations[mime_type].append(desktop_id)

    def _remove_association(self, mime_type: str, desktop_id: str) -> None:
        """Remove a desktop from a mime type's added associations."""
        if mime_type not in self.added_associations:
            return

        if desktop_id in self.added_associations[mime_type]:
            self.added_associations[mime_type].remove(desktop_id)
            if not self.added_associations[mime_type]:
                del self.added_associations[mime_type]

    def add_association(self, mime_type: str, desktop_id: str) -> None:
        """Add a custom association between mime type and desktop."""
        self._add_association(mime_type, desktop_id)

    def remove_association(self, mime_type: str, desktop_id: str) -> None:
        """Remove a custom association."""
        self._remove_association(mime_type, desktop_id)

    def is_custom_association(self, desktop_id: str, mime_type: str) -> bool:
        """Check if an association is custom (only in added_associations)."""
        return (
            mime_type in self.added_associations
            and desktop_id in self.added_associations[mime_type]
        )

    def _build_default_map(self) -> dict:
        """Build a mime_type -> desktop_id mapping from defaults."""
        current_map = {}
        for desktop_id, mime_types in self.defaults.items():
            for mt in mime_types:
                current_map[mt] = desktop_id
        return current_map

    def save(self) -> None:
        """Write changes to mimeapps.list."""
        sections = dict(self._other_sections)
        current_map = self._build_default_map()

        sections["Default Applications"] = current_map

        sections["Added Associations"] = {
            mt: ";".join(desktop_ids) + ";"
            for mt, desktop_ids in self.added_associations.items()
            if desktop_ids
        }

        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            for section_name in ["Added Associations", "Default Applications"]:
                if section_name in sections and sections[section_name]:
                    f.write(f"[{section_name}]\n")
                    for key, value in sections[section_name].items():
                        f.write(f"{key}={value}\n")
                    f.write("\n")

            for section_name, items in sections.items():
                if section_name not in ("Added Associations", "Default Applications"):
                    f.write(f"[{section_name}]\n")
                    for key, value in items.items():
                        f.write(f"{key}={value}\n")
                    f.write("\n")

        self._mime_defaults_effective = None
        self._mime_associations = None

    def _build_desktop_app_info(
        self, desktop_id: str, path: str, data: dict
    ) -> DesktopAppInfo:
        """Build a DesktopAppInfo object from parsed desktop file data."""
        icon_name, icon_file = self._load_icon(data["icon_name"])
        added = self.get_associations_for_desktop_file(desktop_id)
        defaults = self.defaults.get(desktop_id, [])

        return DesktopAppInfo(
            desktop_id=desktop_id,
            path=path,
            name=data["name"],
            icon_name=icon_name,
            icon_file=icon_file,
            exec=data["exec"],
            base_mime_types=data["mime_types"],
            added_mime_types=added,
            default_mime_types=defaults,
        )

    def get_all_desktop_app_infos(self, include_useless_apps: bool = False) -> list:
        """Get all desktop applications as DesktopAppInfo objects."""
        results = []
        desktop_file_paths = self._get_desktop_file_paths()

        for desktop_id, path in desktop_file_paths.items():
            data = self._parse_desktop_file(path)
            if data is None:
                continue
            if not data["mime_types"] and not include_useless_apps:
                continue

            results.append(self._build_desktop_app_info(desktop_id, path, data))

        return results

    def get_desktop_app_info_by_id(self, desktop_id: str) -> Optional[DesktopAppInfo]:
        """Get a single desktop application as DesktopAppInfo object."""
        desktop_file_paths = self._get_desktop_file_paths()
        if desktop_id not in desktop_file_paths:
            return None

        path = desktop_file_paths[desktop_id]
        data = self._parse_desktop_file(path)
        if data is None:
            return None

        return self._build_desktop_app_info(desktop_id, path, data)
