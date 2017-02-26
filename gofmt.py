from __future__ import print_function

import os
import platform
import re
import subprocess
import traceback

import sublime
import sublime_plugin

import golangconfig


REQUIRED_VARS = ['GOPATH']
OPTIONAL_VARS = [
    'GO386',
    'GOARCH',
    'GOARM',
    'GOBIN',
    'GOHOSTOS',
    'GOHOSTARCH',
    'GOOS',
    'GORACE',
    'GOROOT',
    'GOROOT_FINAL',
]

is_windows = platform.system() == 'Windows'
startup_info = None
if is_windows:
    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW

error_re = re.compile(r'.*:(\d+):(\d+):')
settings = sublime.load_settings('Gofmt.sublime-settings')


class Command(object):

    """Command is used to run a subcommand.

    Note that this formatter plugin runs commands synchronously, rather than
    running them in separate threads, as it's often painful if you continue
    editing after saving and then your code is later replaced by a command
    that was running in the background.

    :param list(str) cmd: Command to run. This is a list of the name of the
        binary and any arguments to pass (e.g. ["gofmt", "-e", "-s"]).
    :param sublime.View view: View that the command is attached to.
    :param sublime.Window window: Window that the command is attached to.
    """

    def __init__(self, cmd, view, window):
        self.view = view
        self.window = window
        self.name = cmd[0]
        self.args = cmd[1:]
        self.path, self.env = golangconfig.subprocess_info(
            self.name, REQUIRED_VARS, OPTIONAL_VARS, self.view,
            self.window)

    def run(self, stdin):
        """Run the command.

        :param str stdin: This string is passed to the command as stdin.
        :returns: str, str, int. Returns the stdout, stderr, and return code
            of the process.
        """
        proc = subprocess.Popen(
            [self.path], stdin=subprocess.PIPE, stderr=subprocess.PIPE,
            stdout=subprocess.PIPE, env=self.env, startupinfo=startup_info)
        if isinstance(stdin, str):
            stdin = stdin.encode()
        stdout, stderr = proc.communicate(stdin)
        return stdout, stderr, proc.returncode


class Formatter(object):

    """Formatter is used to format Go code.

    :param sublime.View view: View containing the code to be formatted.
    """

    def __init__(self, view):
        self.view = view
        self.encoding = self.view.encoding()
        if self.encoding == 'Undefined':
            self.encoding = 'utf-8'
        self.window = view.window()
        self.cmds = [Command(cmd, self.view, self.window)
                     for cmd in settings.get('cmds', ['gofmt', '-e', '-s'])]

    def format(self, region):
        """Format the code in the given region.

        This will format the code with all the configured commands, passing
        the output of the previous command as the input to the next command.
        If any commands fail, this will show the errors and return None.

        :param sublime.Region region: Region of text to format.
        :returns: str or None
        """
        self._clear_errors()
        code = self.view.substr(region)
        for cmd in self.cmds:
            code, stderr, return_code = cmd.run(code)
            if stderr or return_code != 0:
                self._show_errors(return_code, stderr, cmd, region)
                return None
        self._hide_error_panel()
        return code.decode(self.encoding)

    def _clear_errors(self):
        """Clear previously displayed errors."""
        self.view.set_status('gofmt', '')
        self.view.erase_regions('gofmt')

    def _hide_error_panel(self):
        """Hide any previously displayed error panel."""
        self.window.run_command('hide_panel', {'panel': 'output.gofmt'})

    def _show_errors(self, return_code, stderr, cmd, region):
        """Show errors from a failed command.

        :param int return_code: Exit code of the command.
        :param str stderr: Stderr output of the command.
        :param Command cmd: Command object.
        :param sublime.Region region: Formatted region.
        """
        self.view.set_status('gofmt', '{} failed with return code {}'.format(
            cmd.name, return_code))
        if not stderr:
            return
        if not isinstance(stderr, str):
            stderr = stderr.decode('utf-8')
        self._show_error_panel(stderr)
        self._show_error_regions(stderr, region)

    def _show_error_regions(self, stderr, region):
        """Mark the regions which had errors.

        :param str stderr: Stderr output of the command.
        :param sublime.Region: Formatted region.
        """
        region_row, region_col = self.view.rowcol(region.begin())
        regions = []
        for error in stderr.splitlines():
            match = error_re.match(error)
            if not match:
                continue
            row, col = int(match.group(1)) - 1, int(match.group(2)) - 1
            if row == 0:
                col += region_col
            row += region_row
            a = self.view.text_point(row, col)
            b = self.view.line(a).end()
            regions.append(sublime.Region(a, b))
        if regions:
            self.view.add_regions(
                'gofmt', regions, 'invalid.illegal', 'dot',
                (sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE |
                 sublime.DRAW_SQUIGGLY_UNDERLINE | sublime.PERSISTENT))

    def _show_error_panel(self, stderr):
        """Show the stderr of a failed command in an output panel.

        :param str stderr: Stderr output of the command.
        """
        fn = os.path.basename(self.view.file_name())
        p = self.window.create_output_panel('gofmt')
        p.set_scratch(True)
        p.run_command('select_all')
        p.run_command('right_delete')
        p.run_command('insert',
                      {'characters': stderr.replace('<standard input>', fn)})
        self.window.run_command('show_panel', {'panel': 'output.gofmt'})


def is_go_source(view):
    """Return True if the given view contains Go source code.

    :param sublime.View view: View containing the code to be formatted.
    :returns: bool
    """
    return view.score_selector(0, 'source.go') != 0


def run_formatter(edit, view, regions):
    """Run a formatter on regions of the view.

    :param sublime.Edit: Buffer modification group.
    :param sublime.View: View containing the code to be formatted.
    :param sublime.Region: Regions of the view to format.
    """
    try:
        formatter = Formatter(view)
        for region in regions:
            formatted_code = formatter.format(region)
            if formatted_code is None:
                return
            view.replace(edit, region, formatted_code)
    except Exception:
        sublime.error_message(traceback.format_exc())


class GofmtCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        if not is_go_source(self.view):
            return
        run_formatter(edit, self.view, [sublime.Region(0, self.view.size())])


class GofmtListener(sublime_plugin.EventListener):

    def on_pre_save(self, view):
        if not settings.get('format_on_save', True):
            return
        view.run_command('gofmt')
