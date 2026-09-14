# Installation

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and use Python 3.11–3.14.

(install-selene)=
## Installing and initialising Selene

From your local Selene checkout:

```sh
uv sync --locked
uv run --no-sync selene --help
```

To make `selene` available on your PATH:

```sh
uv tool install /absolute/path/to/selene
selene init
```

This fork is distributed as local source. Do not install a similarly named package from a public registry. Language servers may download additional dependencies when first used; see [language support](../01-about/020_programming-languages.md) and the {download}`security audit <../../SECURITY_AUDIT.md>`.

## Updating

Update your trusted local checkout, review its changes, then run `uv sync --locked` again. If installed as a tool, run `uv tool install --reinstall /absolute/path/to/selene`. There is no automatic update check or remote news feed.

## Uninstalling

If installed as a tool, run `uv tool uninstall selene-agent`. Local configuration, memories and logs remain in `~/.selene` and each project's `.selene` directory.
