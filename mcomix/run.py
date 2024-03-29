
import os
import sys
import optparse
import signal

from packaging.version import parse as parse_version

if __name__ == '__main__':
    print('PROGRAM TERMINATED', file=sys.stderr)
    print('Please do not run this script directly! Use mcomixstarter.py instead.', file=sys.stderr)
    sys.exit(1)

# These modules must not depend on GTK, Pillow,
# or any other optional libraries.
from mcomix import (
    constants,
    log,
    portability,
    preferences,
)

def wait_and_exit():
    """ Wait for the user pressing ENTER before closing. This should help
    the user find possibly missing dependencies when starting, since the
    Python window will not close down immediately after the error. """
    if sys.platform == 'win32' and not sys.stdin.closed and not sys.stdout.closed:
        print()
        input("Press ENTER to continue...")
    sys.exit(1)

def print_version(opt, value, parser, *args, **kwargs):
    """Print the version number and exit."""
    print(constants.APPNAME + ' ' + constants.VERSION)
    sys.exit(0)

def parse_arguments(argv):
    """ Parse the command line passed in <argv>. Returns a tuple containing
    (options, arguments). Errors parsing the command line are handled in
    this function. """

    parser = optparse.OptionParser(
            usage="%%prog %s" % _('[OPTION...] [PATH]'),
            description=_('View images and comic book archives.'),
            add_help_option=False)
    parser.add_option('--help', action='help',
            help=_('Show this help and exit.'))
    parser.add_option('-s', '--slideshow', dest='slideshow', action='store_true',
            help=_('Start the application in slideshow mode.'))
    parser.add_option('-l', '--library', dest='library', action='store_true',
            help=_('Show the library on startup.'))
    parser.add_option('-v', '--version', action='callback', callback=print_version,
            help=_('Show the version number and exit.'))

    viewmodes = optparse.OptionGroup(parser, _('View modes'))
    viewmodes.add_option('-f', '--fullscreen', dest='fullscreen', action='store_true',
            help=_('Start the application in fullscreen mode.'))
    viewmodes.add_option('-m', '--manga', dest='manga', action='store_true',
            help=_('Start the application in manga mode.'))
    viewmodes.add_option('-d', '--double-page', dest='doublepage', action='store_true',
            help=_('Start the application in double page mode.'))
    parser.add_option_group(viewmodes)

    fitmodes = optparse.OptionGroup(parser, _('Zoom modes'))
    fitmodes.add_option('-b', '--zoom-best', dest='zoommode', action='store_const',
            const=constants.ZOOM_MODE_BEST,
            help=_('Start the application with zoom set to best fit mode.'))
    fitmodes.add_option('-w', '--zoom-width', dest='zoommode', action='store_const',
            const=constants.ZOOM_MODE_WIDTH,
            help=_('Start the application with zoom set to fit width.'))
    fitmodes.add_option('-h', '--zoom-height', dest='zoommode', action='store_const',
            const=constants.ZOOM_MODE_HEIGHT,
            help=_('Start the application with zoom set to fit height.'))
    parser.add_option_group(fitmodes)

    debugopts = optparse.OptionGroup(parser, _('Debug options'))
    debugopts.add_option('-W', dest='loglevel', action='store',
            choices=('all', 'debug', 'info', 'warn', 'error'), default='warn',
            metavar='[ all | debug | info | warn | error ]',
            help=_('Sets the desired output log level.'))
    # This supresses an error when MComix is used with cProfile
    debugopts.add_option('-o', dest='output', action='store',
            default='', help=optparse.SUPPRESS_HELP)
    parser.add_option_group(debugopts)

    opts, args = parser.parse_args(argv)

    # Fix up log level to use constants from log.
    if opts.loglevel == 'all':
        opts.loglevel = log.DEBUG
    if opts.loglevel == 'debug':
        opts.loglevel = log.DEBUG
    if opts.loglevel == 'info':
        opts.loglevel = log.INFO
    elif opts.loglevel == 'warn':
        opts.loglevel = log.WARNING
    elif opts.loglevel == 'error':
        opts.loglevel = log.ERROR

    return opts, args

def run():
    """Run the program."""

    # Load configuration and setup localisation.
    preferences.read_preferences_file()
    from mcomix import i18n
    i18n.install_gettext()

    # Retrieve and parse command line arguments.
    argv = portability.get_commandline_args()
    opts, args = parse_arguments(argv)

    # First things first: set the log level.
    log.setLevel(opts.loglevel)

    # Reconfigure stdout to replace characters that cannot be printed
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')

    # Check for PyGTK and PIL dependencies.
    try:
        from gi import require_version

        require_version('PangoCairo', '1.0')
        require_version('Gtk', '3.0')
        require_version('Gdk', '3.0')

        from gi.repository import Gdk, Gtk, GObject

        GObject.threads_init()

    except AssertionError:
        log.error( _("You do not have the required versions of GTK+ 3.0 and PyGObject installed.") )
        wait_and_exit()

    except ImportError:
        log.error( _('No version of GObject was found on your system.') )
        log.error( _('This error might be caused by missing GTK+ libraries.') )
        wait_and_exit()

    try:
        import PIL.Image
        if parse_version(PIL.__version__) < parse_version('6.0.0'):
            log.error( _("You don't have the required version of the Python Imaging Library Fork (Pillow) installed."))
            log.error( _('Installed Pillow version is: %s') % PIL.__version__ )
            log.error( _('Required Pillow version is: 6.0.0 or higher') )
            wait_and_exit()

    except ImportError:
        log.error( _('Python Imaging Library Fork (Pillow) 6.0.0 or higher is required.') )
        log.error( _('No version of the Python Imaging Library was found on your system.') )
        wait_and_exit()

    try:
        import jxlpy

    except ImportError:
        log.error( _('jxlpy is required') )
        log.error( _('No version of jxlpy was found on your system.') )
        wait_and_exit()

    if not os.path.exists(constants.DATA_DIR):
        os.makedirs(constants.DATA_DIR, 0o700)

    if not os.path.exists(constants.CONFIG_DIR):
        os.makedirs(constants.CONFIG_DIR, 0o700)

    from mcomix import icons
    icons.load_icons()

    open_path = None
    open_page = 1
    if len(args) == 1:
        open_path = args[0]
    elif len(args) > 1:
        open_path = args

    elif preferences.prefs['auto load last file'] \
        and preferences.prefs['path to last file'] \
        and os.path.isfile(preferences.prefs['path to last file']):
        open_path = preferences.prefs['path to last file']
        open_page = preferences.prefs['page of last file']

    # Some languages require a RTL layout
    if preferences.prefs['language'] in ('he', 'fa'):
        Gtk.widget_set_default_direction(Gtk.TextDirection.RTL)

    Gdk.set_program_class(constants.APPNAME)

    settings = Gtk.Settings.get_default()
    # Enable icons for menu items.
    settings.props.gtk_menu_images = True

    from mcomix import main
    window = main.MainWindow(fullscreen = opts.fullscreen, is_slideshow = opts.slideshow,
            show_library = opts.library, manga_mode = opts.manga,
            double_page = opts.doublepage, zoom_mode = opts.zoommode,
            open_path = open_path, open_page = open_page)
    main.set_main_window(window)

    if 'win32' != sys.platform:
        # Add a SIGCHLD handler to reap zombie processes.
        def on_sigchld(signum, frame):
            try:
                os.waitpid(-1, os.WNOHANG)
            except OSError:
                pass
        signal.signal(signal.SIGCHLD, on_sigchld)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, stack: GObject.idle_add(window.terminate_program))
    try:
        Gtk.main()
    except KeyboardInterrupt: # Will not always work because of threading.
        window.terminate_program()

# vim: expandtab:sw=4:ts=4
