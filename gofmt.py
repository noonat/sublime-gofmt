from __future__ import print_function

import os
import platform
import re
import subprocess
import traceback

import sublime
import sublime_plugin

import golangconfig


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
REQUIRED_VARS = ['GOPATH']

ERROR_TEMPLATE = """
<div><b>{row}:</b> {text}</div>
"""

is_windows = platform.system() == 'Windows'
startup_info = None
if is_windows:
    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW

settings = None
view_errors = {}


def plugin_loaded():
    global settings
    settings = sublime.load_settings('Gofmt.sublime-settings')


def guess_cwd(view):
    if view.file_name():
        return os.path.dirname(view.file_name())
    elif len(view.window().folders()):
        return view.window().folders()[0]


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

        # The cwd is necessary for correct operation of `goimports`. The PWD is
        # added just in case. It's refreshed here rather than in the
        # constructor, because buffers may be moved between windows.
        cwd = guess_cwd(self.view)
        self.env['PWD'] = cwd

        proc = subprocess.Popen(
            [self.path],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=self.env,
            cwd=cwd,
            startupinfo=startup_info,
        )
        if isinstance(stdin, str):
            stdin = stdin.encode()
        stdout, stderr = proc.communicate(stdin)
        return stdout, stderr, proc.returncode


class Error(object):

    line_re = re.compile(r'\A.*:(\d+):(\d+):\s+(.*)\Z')

    def __init__(self, text, region, row, col, filename):
        self.text = text
        self.region = region
        self.row = row
        self.col = col
        self.filename = filename

    @classmethod
    def parse_stderr(cls, stderr, region, view):
        errors = []
        region_row, region_col = view.rowcol(region.begin())
        if not isinstance(stderr, str):
            stderr = stderr.decode('utf-8')
        fn = '<anonymous buffer>'
        if view.file_name():
            fn = os.path.basename(view.file_name())
            stderr = stderr.replace('<standard input>', fn)
        for raw_text in stderr.splitlines():
            match = cls.line_re.match(raw_text)
            if not match:
                continue
            row = int(match.group(1)) - 1
            col = int(match.group(2)) - 1
            text = match.group(3)
            if row == 0:
                col += region_col
            row += region_row
            a = view.text_point(row, col)
            b = view.line(a).end()
            errors.append(Error(text, sublime.Region(a, b), row, col, fn))
        return errors


class FormatterError(Exception):

    def __init__(self, errors):
        super(FormatterError, self).__init__('error running formatter')
        self.errors = errors


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
        cmds = settings.get('cmds', ['gofmt', '-e', '-s']) or []
        self.cmds = [Command(cmd, self.view, self.window) for cmd in cmds]

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
                errors = Error.parse_stderr(stderr, region, self.view)
                self._show_errors(errors, return_code, cmd)
                raise FormatterError(errors)
        self._hide_error_panel()
        return code.decode(self.encoding)

    def _clear_errors(self):
        """Clear previously displayed errors."""
        self.view.set_status('gofmt', '')
        self.view.erase_regions('gofmt')

    def _hide_error_panel(self):
        """Hide any previously displayed error panel."""
        self.window.run_command('hide_panel', {'panel': 'output.gofmt'})

    def _show_errors(self, errors, return_code, cmd):
        """Show errors from a failed command.

        :param int return_code: Exit code of the command.
        :param str stderr: Stderr output of the command.
        :param Command cmd: Command object.
        :param sublime.Region region: Formatted region.
        """
        self.view.set_status('gofmt', '{} failed with return code {}'.format(
            cmd.name, return_code))
        self._show_error_panel(errors)
        self._show_error_regions(errors)

    def _show_error_regions(self, errors):
        """Mark the regions which had errors.

        :param str stderr: Stderr output of the command.
        :param sublime.Region: Formatted region.
        """
        self.view.add_regions(
            'gofmt', [e.region for e in errors], 'invalid.illegal', 'dot',
            (sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE |
             sublime.DRAW_SQUIGGLY_UNDERLINE))

    def _show_error_panel(self, errors):
        """Show the stderr of a failed command in an output panel.

        :param str stderr: Stderr output of the command.
        """
        characters = '\n'.join([e.text for e in errors])
        p = self.window.create_output_panel('gofmt')
        p.set_scratch(True)
        p.run_command('select_all')
        p.run_command('right_delete')
        p.run_command('insert', {'characters': characters})


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
    global view_errors
    if view.id() in view_errors:
        del view_errors[view.id()]
    try:
        prev_position = view.viewport_position()

        formatter = Formatter(view)

        # Note: after pressing ⌘Z or ^Z to "go back" in the editing history, the
        # "forward" history is kept until the next change. Calling
        # `view.replace` always erases the forward history, even if the buffer
        # hasn't changed. Manually checking for changes avoids this problem and
        # makes the plugin nicer to use.
        for region in regions:
            replacement = formatter.format(region)
            if view.substr(region) != replacement:
                view.replace(edit, region, replacement)

        # Only works on the main thread, hence the timer. Credit:
        # https://github.com/liuhewei/gotools-sublime/blob/2c44f84024f9fd27ca5c347cab080b80397a32c2/gotools_format.py#L77
        restore = lambda: view.set_viewport_position(prev_position, animate=False)
        sublime.set_timeout(restore, 0)

    except FormatterError as e:
        view_errors[view.id()] = e.errors
    except Exception:
        sublime.error_message(traceback.format_exc())


class GofmtCommand(sublime_plugin.TextCommand):
    def is_enabled(self):
        return is_go_source(self.view)

    def run(self, edit):
        run_formatter(edit, self.view, [sublime.Region(0, self.view.size())])


class GofmtListener(sublime_plugin.EventListener):

    def _show_errors_for_row(self, view, row, point):
        if not is_go_source(view):
            return
        errors = view_errors.get(view.id())
        if not errors:
            return
        row_errors = [e for e in errors if e.row == row]
        if not row_errors:
            return
        html = '\n'.join([ERROR_TEMPLATE.format(row=e.row + 1, text=e.text)
                          for e in row_errors])
        view.show_popup(html, flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                        location=point, max_width=600)

    def on_hover(self, view, point, hover_zone):
        if hover_zone != sublime.HOVER_TEXT:
            return
        row, _ = view.rowcol(point)
        self._show_errors_for_row(view, row, point)

    def on_pre_save(self, view):
        if not settings.get('format_on_save', True):
            return
        view.run_command('gofmt')
