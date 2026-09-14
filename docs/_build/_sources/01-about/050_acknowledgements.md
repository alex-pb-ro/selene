# Acknowledgements

## Community Contributions

A significant part of Selene, especially support for various languages, was contributed by the open source community.
We are very grateful for the many contributors who made this possible and who played an important role in making Selene
what it is today.

## Technologies

We built Selene on top of multiple existing open-source technologies, the most important ones being:

1. [multilspy](https://github.com/microsoft/multilspy).
   A library which wraps language server implementations and adapts them for interaction via Python
   and which provided the basis for our library Solid-LSP (src/solidlsp).
   Solid-LSP provides pure synchronous LSP calls and extends the original library with the symbolic logic
   that Selene required.
2. [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)
3. All the language servers that we use through Solid-LSP.

Without these projects, Selene would not have been possible (or would have been significantly more difficult to build).
