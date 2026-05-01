# Mimic

Manage default applications and file type associations on Linux.

![screenshot](https://raw.githubusercontent.com/ArijanJ/Mimic/refs/heads/main/static/screenshot-1.png)

## Installation

```bash
flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install -y flathub org.flatpak.Builder
git clone https://github.com/ArijanJ/Mimic && cd Mimic
cp ~/.config/mimeapps.list{,-backup} # Back up your mimeapps.list just in case :)
flatpak run --command=flathub-build org.flatpak.Builder --install io.github.arijanj.Mimic.json
flatpak run io.github.arijanj.Mimic # Run the app
```

## Reporting bugs

Due to Flatpak limitations not allowing the use of all appropriate APIs, the majority of the parsing logic is re-implemented in Python. If you notice a bug, please feel free to [open an issue](https://github.com/ArijanJ/Mimic/issues) and describe what is happening.
