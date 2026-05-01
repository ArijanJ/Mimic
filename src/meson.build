pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'mimic'
gnome = import('gnome')

gnome.compile_resources('mimic',
  'mimic.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)

python = import('python')

conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('VERSION', meson.project_version())
conf.set('localedir', get_option('prefix') / get_option('localedir'))
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'mimic.in',
  output: 'mimic',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x'
)

mimic_sources = [
  'main.py',
  'mimeapps.py',
  'dialogs.py',
  'utils.py',
  'widgets.py',
]

install_data(mimic_sources, install_dir: moduledir)
