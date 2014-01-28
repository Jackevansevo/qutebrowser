import sys
import logging
import faulthandler
from signal import signal, SIGINT
from argparse import ArgumentParser

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QUrl, QTimer

import qutebrowser.commands.utils as cmdutils
import qutebrowser.utils.config as config
from qutebrowser.widgets.mainwindow import MainWindow
from qutebrowser.commands.keys import KeyParser
from qutebrowser.utils.appdirs import AppDirs

class QuteBrowser(QApplication):
    """Main object for QuteBrowser"""
    dirs = None # AppDirs - config/cache directories
    config = None # Config(Parser) object
    mainwindow = None
    commandparser = None
    keyparser = None
    args = None # ArgumentParser
    timer = None # QTimer for python hacks

    def __init__(self):
        super().__init__(sys.argv)
        # Exit on exceptions
        sys.excepthook = self.tmp_exception_hook

        # Handle segfaults
        faulthandler.enable()

        args = self.parseopts()
        self.initlog()

        self.dirs = AppDirs('qutebrowser')
        if self.args.confdir is None:
            confdir = self.dirs.user_config_dir
        elif self.args.confdir == '':
            confdir = None
        else:
            confdir = self.args.confdir
        config.init(confdir)

        self.commandparser = cmdutils.CommandParser()
        self.keyparser = KeyParser(self.mainwindow)
        self.init_cmds()
        self.mainwindow = MainWindow()

        self.aboutToQuit.connect(config.config.save)
        self.mainwindow.tabs.keypress.connect(self.keyparser.handle)
        self.keyparser.set_cmd_text.connect(self.mainwindow.status.cmd.set_cmd)
        self.mainwindow.status.cmd.got_cmd.connect(self.commandparser.run)
        self.mainwindow.status.cmd.got_cmd.connect(
            self.mainwindow.tabs.setFocus)
        self.commandparser.error.connect(self.mainwindow.status.disp_error)
        self.keyparser.commandparser.error.connect(
            self.mainwindow.status.disp_error)
        self.keyparser.keystring_updated.connect(
            self.mainwindow.status.txt.set_keystring)

        self.mainwindow.show()
        self.python_hacks()

    def tmp_exception_hook(exctype, value, traceback):
        """Exception hook while initializing, simply exit"""
        sys.__excepthook__(exctype, value, traceback)
        self.exit(1)

    def exception_hook(exctype, value, traceback):
        """Try very hard to write open tabs to a file and exit gracefully"""
        sys.__excepthook__(exctype, value, traceback)
        try:
            for tabidx in range(self.mainwindow.tabs.count()):
                try:
                    # FIXME write to some file
                    print(self.mainwindow.tabs.widget(tabidx).url().url())
                except Exception:
                    pass
        except Exception:
            pass
        self.exit(1)

    def python_hacks(self):
        """Gets around some PyQt-oddities by evil hacks"""
        ## Make python exceptions work
        sys.excepthook = self.exception_hook

        ## Quit on SIGINT
        signal(SIGINT, lambda *args: self.exit(128 + SIGINT))

        ## hack to make Ctrl+C work by passing control to the Python
        ## interpreter once all 500ms (lambda to ignore args)
        self.timer = QTimer()
        self.timer.start(500)
        self.timer.timeout.connect(lambda: None)

    def parseopts(self):
        """Parse command line options"""
        parser = ArgumentParser("usage: %(prog)s [options]")
        parser.add_argument('-l', '--log', dest='loglevel',
                            help='Set loglevel', default='info')
        parser.add_argument('-c', '--confdir', help='Set config directory '
                            '(empty for no config storage)')
        self.args = parser.parse_args()

    def initlog(self):
        """Initialisation of the log"""
        loglevel = self.args.loglevel
        numeric_level = getattr(logging, loglevel.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: {}'.format(loglevel))
        logging.basicConfig(
            level=numeric_level,
            format='%(asctime)s [%(levelname)s] '
                   '[%(module)s:%(funcName)s:%(lineno)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S')

    def init_cmds(self):
        """Initialisation of the qutebrowser commands"""
        cmdutils.register_all()
        for cmd in cmdutils.cmd_dict.values():
            cmd.signal.connect(self.cmd_handler)
        try:
            self.keyparser.from_config_sect(config.config['keybind'])
        except KeyError:
            pass

    def cmd_handler(self, tpl):
        """Handler which gets called from all commands and delegates the
        specific actions.

        tpl -- A tuple in the form (count, argv) where argv is [cmd, arg, ...]

        All handlers supporting a count should have a keyword argument count.
        """
        (count, argv) = tpl
        cmd = argv[0]
        args = argv[1:]

        handlers = {
            'open':          self.mainwindow.tabs.openurl,
            'tabopen':       self.mainwindow.tabs.tabopen,
            'quit':          self.quit,
            'tabclose':      self.mainwindow.tabs.cur_close,
            'tabprev':       self.mainwindow.tabs.switch_prev,
            'tabnext':       self.mainwindow.tabs.switch_next,
            'reload':        self.mainwindow.tabs.cur_reload,
            'stop':          self.mainwindow.tabs.cur_stop,
            'back':          self.mainwindow.tabs.cur_back,
            'forward':       self.mainwindow.tabs.cur_forward,
            'print':         self.mainwindow.tabs.cur_print,
            'scroll':        self.mainwindow.tabs.cur_scroll,
            'scroll_perc_y': self.mainwindow.tabs.cur_scroll_percent_x,
            'scroll_perc_y': self.mainwindow.tabs.cur_scroll_percent_y,
            'undo':          self.mainwindow.tabs.undo_close,
            'pyeval':        self.pyeval,
        }

        handler = handlers[cmd]

        if self.sender().count:
            handler(*args, count=count)
        else:
            handler(*args)

    def pyeval(self, s):
        """Evaluates a python string, handler for the pyeval command"""
        try:
            r = eval(s)
            out = repr(r)
        except Exception as e:
            out = ': '.join([e.__class__.__name__, str(e)])

        # FIXME we probably want some nicer interface to display these about:
        # pages
        tab = self.mainwindow.tabs.currentWidget()
        tab.setUrl(QUrl('about:pyeval'))
        tab.setContent(out.encode('UTF-8'), 'text/plain')
