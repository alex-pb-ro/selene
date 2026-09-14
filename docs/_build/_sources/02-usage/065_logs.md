# Logs

It can be vital to understand what is happening in Selene, especially when something goes wrong.

You can access Selene's live logs via
  * the [Selene dashboard](060_dashboard) (tab "Logs")
  * the [GUI tool](060_dashboard).

Additionally, logs are persisted in the Selene home directory, which, by default, is located at
  * `%USERPROFILE%\.selene\logs` on Windows
  * `~/.selene/logs` on Linux and macOS.

You can adjust the log level via the [global configuration](global-config).
You additionally have the option of enabling full tracing of language server communication (mostly for development purposes).
