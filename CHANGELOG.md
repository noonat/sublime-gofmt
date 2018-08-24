# Changelog

## v0.1.6

- When formatting doesn't change the code, don't modify the buffer to avoid wrecking "undo" (⌘⇪Z or ^⇪Z).

- The palette command is enabled only when editing a Go buffer.

## v0.1.5

- The palette command now works in anonymous buffers.

## v0.1.4

- When running `goimports`, use the current file's directory as PWD. This prevents it from occasionally failing to add imports.

## v0.1.3

- Saves and restores the scroll position to avoid the view jumping.

## v0.1.2

- Adds a missing dependency on shellenv.
- Removes trailing commas in Main.sublime-menu.

## v0.1.1

- Removes debug code printing when hovering over text.

## v0.1.0

- Initial release.
