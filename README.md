# Sublime Gofmt

This Sublime Text 3 package adds support for running gofmt on your Go source
files. It runs on save by default, but that can be disabled. You can run it
manually via a palette command (`Gofmt: Format this file`).

If gofmt encounters errors, the plugin will mark the lines and highlight those
errors in your source file.

## Goimports

If you want to use [goimports] instead, open to Sublime Text -> Preferences ->
Package Settings -> Gofmt -> Settings - User and enter a config like this:

```json
{
  "cmds": [
    ["goimports", "-e"]
  ]
}
```

Note that `cmds` is an array, so you can put multiple commands in there, if
you want to run the file through more than one formatter for some reason.

[goimports]: https://godoc.org/golang.org/x/tools/cmd/goimports
