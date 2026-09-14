# Language-server adapter review inventory

Every tracked adapter/resource under `src/solidlsp/language_servers` is listed below. Domains are literal URLs appearing in source, including comments; they are **not** a list of destinations contacted in every run. Version pins, download helpers, package-manager commands and configurable launch paths were reviewed alongside these candidates. Other network destinations can be assembled from project configuration or dependency code. This inventory is an aid to source review, not a certification of the downloaded binaries.

| Adapter/resource | Version/package/download references | Literal URL domains |
| --- | --- | --- |
| [ada_language_server.py](../src/solidlsp/language_servers/ada_language_server.py) | DEFAULT_ALS_VERSION=2026.2.202604091; RuntimeDependency | github.com |
| [al_language_server.py](../src/solidlsp/language_servers/al_language_server.py) | INITIAL_AL_EXTENSION_VERSION=18.0.2242655; DEFAULT_AL_EXTENSION_VERSION=18.0.2242655; DEFAULT_AL_EXTENSION_SHA256=3971995e61a59dc4fcce4a65053072a67991ed624a16635c4f2911f12564b2b9; download_and_extract | marketplace.visualstudio.com |
| [angular_language_server.py](../src/solidlsp/language_servers/angular_language_server.py) | DEFAULT_ANGULAR_LANGUAGE_SERVER_VERSION=21.2.10; DEFAULT_ANGULAR_LANGUAGE_SERVICE_VERSION=21.2.10; DEFAULT_TYPESCRIPT_VERSION=5.9.3; DEFAULT_TYPESCRIPT_LANGUAGE_SERVER_VERSION=5.1.3; build_npm_install_command; RuntimeDependency |  |
| [ansible_language_server.py](../src/solidlsp/language_servers/ansible_language_server.py) | INITIAL_ANSIBLE_LANGUAGE_SERVER_VERSION=1.2.3; DEFAULT_ANSIBLE_LANGUAGE_SERVER_VERSION=1.2.3; build_npm_install_command; RuntimeDependency |  |
| [basedpyright_server.py](../src/solidlsp/language_servers/basedpyright_server.py) | BASEDPYRIGHT_VERSION=1.39.9 |  |
| [bash_language_server.py](../src/solidlsp/language_servers/bash_language_server.py) | INITIAL_BASH_LANGUAGE_SERVER_VERSION=5.6.0; DEFAULT_BASH_LANGUAGE_SERVER_VERSION=5.6.0; _SHELLCHECK_VERSION=0.10.0; build_npm_install_command; download_and_extract; RuntimeDependency | github.com |
| [bsl_language_server.py](../src/solidlsp/language_servers/bsl_language_server.py) | DEFAULT_BSL_LS_VERSION=0.29.0; subprocess_run; RuntimeDependency | github.com |
| [ccls_language_server.py](../src/solidlsp/language_servers/ccls_language_server.py) | No matching literal version/download marker; see source. | github.com |
| [clangd_language_server.py](../src/solidlsp/language_servers/clangd_language_server.py) | RuntimeDependency | clang.llvm.org, clangd.llvm.org, github.com |
| [clojure_lsp.py](../src/solidlsp/language_servers/clojure_lsp.py) | INITIAL_CLOJURE_LSP_VERSION=2026.02.20-16.08.58; DEFAULT_CLOJURE_LSP_VERSION=2026.02.20-16.08.58; subprocess_run; RuntimeDependency | clojure.org, github.com |
| [common.py](../src/solidlsp/language_servers/common.py) | build_npm_install_command; subprocess_run; download_and_extract; RuntimeDependency |  |
| [crystal_language_server.py](../src/solidlsp/language_servers/crystal_language_server.py) | No matching literal version/download marker; see source. | github.com |
| [csharp_language_server.py](../src/solidlsp/language_servers/csharp_language_server.py) | DEFAULT_CSHARP_LANGUAGE_SERVER_VERSION=5.5.0-2.26078.4; download_and_extract; RuntimeDependency | example.com, www.nuget.org |
| [cue_language_server.py](../src/solidlsp/language_servers/cue_language_server.py) | DEFAULT_CUE_VERSION=v0.16.1; RuntimeDependency | github.com |
| [dart_language_server.py](../src/solidlsp/language_servers/dart_language_server.py) | INITIAL_DART_SDK_VERSION=3.7.1; DEFAULT_DART_SDK_VERSION=3.7.1; RuntimeDependency | storage.googleapis.com |
| [deno_language_server.py](../src/solidlsp/language_servers/deno_language_server.py) | No matching literal version/download marker; see source. | docs.deno.com |
| [eclipse_jdtls.py](../src/solidlsp/language_servers/eclipse_jdtls.py) | INITIAL_VSCODE_JAVA_VERSION=1.42.0-561; DEFAULT_GRADLE_VERSION=8.14.2; DEFAULT_VSCODE_JAVA_VERSION=1.54.0-923; subprocess_run; RuntimeDependency | download.eclipse.org, github.com, projectlombok.org, services.gradle.org |
| [README.md](../src/solidlsp/language_servers/elixir_tools/README.md) | No matching literal version/download marker; see source. | elixir-lang.org, github.com |
| [__init__.py](../src/solidlsp/language_servers/elixir_tools/__init__.py) | No matching literal version/download marker; see source. |  |
| [elixir_tools.py](../src/solidlsp/language_servers/elixir_tools/elixir_tools.py) | EXPERT_VERSION=v0.1.0-rc.6; subprocess_run; RuntimeDependency | elixir-lang.org, github.com |
| [elm_language_server.py](../src/solidlsp/language_servers/elm_language_server.py) | INITIAL_ELM_LANGUAGE_SERVER_VERSION=2.8.0; DEFAULT_ELM_LANGUAGE_SERVER_VERSION=2.8.0; INITIAL_ELM_COMPILER_VERSION=0.19.1-6; DEFAULT_ELM_COMPILER_VERSION=0.19.1-6; build_npm_install_command; RuntimeDependency |  |
| [erlang_language_server.py](../src/solidlsp/language_servers/erlang_language_server.py) | subprocess_run | github.com, www.erlang.org |
| [fatou_language_server.py](../src/solidlsp/language_servers/fatou_language_server.py) | FATOU_VERSION=0.18.0 |  |
| [fortran_language_server.py](../src/solidlsp/language_servers/fortran_language_server.py) | FORTLS_VERSION=3.2.2 |  |
| [fsharp_language_server.py](../src/solidlsp/language_servers/fsharp_language_server.py) | INITIAL_FSAUTOCOMPLETE_VERSION=0.83.0; DEFAULT_FSAUTOCOMPLETE_VERSION=0.83.0; subprocess_run; RuntimeDependency |  |
| [gleam_language_server.py](../src/solidlsp/language_servers/gleam_language_server.py) | subprocess_run | gleam.run |
| [godot_language_server.py](../src/solidlsp/language_servers/godot_language_server.py) | No matching literal version/download marker; see source. |  |
| [gopls.py](../src/solidlsp/language_servers/gopls.py) | subprocess_run | golang.org, pkg.go.dev |
| [groovy_language_server.py](../src/solidlsp/language_servers/groovy_language_server.py) | INITIAL_VSCODE_JAVA_VERSION=1.42.0-561; DEFAULT_VSCODE_JAVA_VERSION=1.42.0-561; download_and_extract; RuntimeDependency | github.com |
| [haskell_language_server.py](../src/solidlsp/language_servers/haskell_language_server.py) | No matching literal version/download marker; see source. | www.haskell.org |
| [haxe_language_server.py](../src/solidlsp/language_servers/haxe_language_server.py) | INITIAL_VSHAXE_VERSION=2.34.2; DEFAULT_VSHAXE_VERSION=2.34.2; DEFAULT_VSHAXE_SHA256=104d785e3f7b57a7f3debf520d9751f7e7abf3a7e78d203db1a8ff3dc7ca30e2; urlretrieve | open-vsx.org |
| [hlsl_language_server.py](../src/solidlsp/language_servers/hlsl_language_server.py) | _INITIAL_VERSION=1.3.1; _DEFAULT_VERSION=1.3.1; RuntimeDependency | github.com, rustup.rs |
| [intelephense.py](../src/solidlsp/language_servers/intelephense.py) | INITIAL_INTELEPHENSE_VERSION=1.14.4; DEFAULT_INTELEPHENSE_VERSION=1.14.4; build_npm_install_command; RuntimeDependency |  |
| [jedi_server.py](../src/solidlsp/language_servers/jedi_server.py) | No matching literal version/download marker; see source. | github.com |
| [json_language_server.py](../src/solidlsp/language_servers/json_language_server.py) | INITIAL_JSON_LANGUAGE_SERVER_VERSION=1.3.4; DEFAULT_JSON_LANGUAGE_SERVER_VERSION=1.3.4; build_npm_install_command; RuntimeDependency |  |
| [julia_server.py](../src/solidlsp/language_servers/julia_server.py) | subprocess_run | julialang.org |
| [kotlin_language_server.py](../src/solidlsp/language_servers/kotlin_language_server.py) | DEFAULT_KOTLIN_JVM_OPTIONS=-Xmx2G; INITIAL_KOTLIN_LSP_VERSION=261.13587.0; DEFAULT_KOTLIN_LSP_VERSION=262.9593.0 | download-cdn.jetbrains.com |
| [lean4_language_server.py](../src/solidlsp/language_servers/lean4_language_server.py) | subprocess_run | github.com, raw.githubusercontent.com |
| [lua_ls.py](../src/solidlsp/language_servers/lua_ls.py) | INITIAL_LUA_LS_VERSION=3.15.0; DEFAULT_LUA_LS_VERSION=3.15.0; download_and_extract | github.com |
| [luau_lsp.py](../src/solidlsp/language_servers/luau_lsp.py) | INITIAL_LUAU_LSP_VERSION=1.63.0; DEFAULT_LUAU_LSP_VERSION=1.63.0; LUAU_DOCS_URL=https://luau-lsp.pages.dev/api-docs/luau-en-us.json; ROBLOX_DOCS_URL=https://luau-lsp.pages.dev/api-docs/en-us.json; download_and_extract | github.com, luau-lsp.pages.dev |
| [marksman.py](../src/solidlsp/language_servers/marksman.py) | INITIAL_MARKSMAN_VERSION=2024-12-18; DEFAULT_MARKSMAN_VERSION=2024-12-18; RuntimeDependency | github.com |
| [matlab_language_server.py](../src/solidlsp/language_servers/matlab_language_server.py) | INITIAL_MATLAB_EXTENSION_VERSION=1.3.9; DEFAULT_MATLAB_EXTENSION_VERSION=1.3.9; DEFAULT_MATLAB_EXTENSION_SHA256=1da3add2c3a593fa0ebcdf1d15231faee8014de10f549c36915ab9d4f18390f2; download_and_extract | marketplace.visualstudio.com |
| [msl_language_server.py](../src/solidlsp/language_servers/msl_language_server.py) | No matching literal version/download marker; see source. |  |
| [msl_lsp_server.py](../src/solidlsp/language_servers/msl_lsp_server.py) | No matching literal version/download marker; see source. |  |
| [nextflow_language_server.py](../src/solidlsp/language_servers/nextflow_language_server.py) | DEFAULT_NEXTFLOW_LS_VERSION=26.04.3 | github.com |
| [nixd_ls.py](../src/solidlsp/language_servers/nixd_ls.py) | subprocess_run | nixos.org |
| [ocaml_lsp_server.py](../src/solidlsp/language_servers/ocaml_lsp_server.py) | subprocess_run | discuss.ocaml.org, fdopen.github.io, github.com, opam.ocaml.org |
| [initialize_params.json](../src/solidlsp/language_servers/omnisharp/initialize_params.json) | No matching literal version/download marker; see source. | microsoft.github.io |
| [runtime_dependencies.json](../src/solidlsp/language_servers/omnisharp/runtime_dependencies.json) | No matching literal version/download marker; see source. | download.visualstudio.microsoft.com, github.com, roslynomnisharp.blob.core.windows.net |
| [workspace_did_change_configuration.json](../src/solidlsp/language_servers/omnisharp/workspace_did_change_configuration.json) | No matching literal version/download marker; see source. |  |
| [omnisharp.py](../src/solidlsp/language_servers/omnisharp.py) | INITIAL_OMNISHARP_VERSION=1.39.10; INITIAL_RAZOR_OMNISHARP_VERSION=7.0.0-preview.23363.1; DEFAULT_OMNISHARP_VERSION=1.39.10; DEFAULT_RAZOR_OMNISHARP_VERSION=7.0.0-preview.23363.1; download_and_extract | stackoverflow.com |
| [pascal_server.py](../src/solidlsp/language_servers/pascal_server.py) | INITIAL_PASLS_VERSION=v0.2.0; DEFAULT_PASLS_VERSION=v0.2.0; RuntimeDependency | api.github.com, github.com |
| [perl_language_server.py](../src/solidlsp/language_servers/perl_language_server.py) | subprocess_run | metacpan.org, www.perl.org |
| [phpactor.py](../src/solidlsp/language_servers/phpactor.py) | INITIAL_PHPACTOR_VERSION=2025.12.21.1; DEFAULT_PHPACTOR_VERSION=2025.12.21.1; DEFAULT_PHPACTOR_PHAR_SHA256=53bbe9625cd9b5e9b394bc2f595fbad13dbbe6dfc96950c56dea3b5d9a246cc3; subprocess_run; download_and_extract | github.com |
| [phpantom.py](../src/solidlsp/language_servers/phpantom.py) | INITIAL_PHPANTOM_VERSION=0.8.0; DEFAULT_PHPANTOM_VERSION=0.8.0; RuntimeDependency | github.com |
| [powershell_language_server.py](../src/solidlsp/language_servers/powershell_language_server.py) | INITIAL_PSES_VERSION=4.4.0; DEFAULT_PSES_VERSION=4.4.0; DEFAULT_PSES_SHA256=690b91092989a0f66e6f43986166aaef69d64b559a9fda51feed882e1103fbcc; PSSCRIPTANALYZER_VERSION=1.25.0; subprocess_run; download_and_extract | github.com |
| [pyrefly_server.py](../src/solidlsp/language_servers/pyrefly_server.py) | PYREFLY_VERSION=1.1.1; PYREFLY_CONFIG_DOC_URL=https://pyrefly.org/en/docs/configuration/ | pyrefly.org |
| [pyright_server.py](../src/solidlsp/language_servers/pyright_server.py) | PYRIGHT_VERSION=1.1.403 |  |
| [qml_language_server.py](../src/solidlsp/language_servers/qml_language_server.py) | No matching literal version/download marker; see source. | doc.qt.io |
| [r_language_server.py](../src/solidlsp/language_servers/r_language_server.py) | subprocess_run | www.r-project.org |
| [regal_server.py](../src/solidlsp/language_servers/regal_server.py) | No matching literal version/download marker; see source. | github.com |
| [ruby_lsp.py](../src/solidlsp/language_servers/ruby_lsp.py) | RUBY_LSP_VERSION=0.26.8; subprocess_run | mise.jdx.dev |
| [rust_analyzer.py](../src/solidlsp/language_servers/rust_analyzer.py) | subprocess_run | github.com |
| [scala_language_server.py](../src/solidlsp/language_servers/scala_language_server.py) | DEFAULT_METALS_VERSION=1.6.4; DEFAULT_CLIENT_NAME=Selene; DEFAULT_ON_STALE_LOCK=auto-clean; subprocess_run |  |
| [solargraph.py](../src/solidlsp/language_servers/solargraph.py) | subprocess_run | rubygems.org |
| [solidity_homedir_preload.cjs](../src/solidlsp/language_servers/solidity_homedir_preload.cjs) | No matching literal version/download marker; see source. |  |
| [solidity_language_server.py](../src/solidlsp/language_servers/solidity_language_server.py) | INITIAL_SOLIDITY_LANGUAGE_SERVER_VERSION=0.8.4; DEFAULT_SOLIDITY_LANGUAGE_SERVER_VERSION=0.8.4; INITIAL_FORGE_VERSION=1.5.1; DEFAULT_FORGE_VERSION=1.5.1; build_npm_install_command; RuntimeDependency |  |
| [some_sass_language_server.py](../src/solidlsp/language_servers/some_sass_language_server.py) | DEFAULT_PACKAGE_VERSION=2.3.8; build_npm_install_command; RuntimeDependency | github.com, wkillerud.github.io |
| [sourcekit_lsp.py](../src/solidlsp/language_servers/sourcekit_lsp.py) | subprocess_run | github.com |
| [svelte_language_server.py](../src/solidlsp/language_servers/svelte_language_server.py) | build_npm_install_command; RuntimeDependency |  |
| [systemverilog_server.py](../src/solidlsp/language_servers/systemverilog_server.py) | subprocess_run; RuntimeDependency | github.com |
| [taplo_server.py](../src/solidlsp/language_servers/taplo_server.py) | INITIAL_TAPLO_VERSION=0.10.0; DEFAULT_TAPLO_VERSION=0.10.0; download_and_extract | github.com |
| [terraform_ls.py](../src/solidlsp/language_servers/terraform_ls.py) | INITIAL_TERRAFORM_LS_VERSION=0.36.5; DEFAULT_TERRAFORM_LS_VERSION=0.36.5; RuntimeDependency | developer.hashicorp.com, releases.hashicorp.com |
| [texlab_language_server.py](../src/solidlsp/language_servers/texlab_language_server.py) | TEXLAB_VERSION=5.25.1; RuntimeDependency | github.com |
| [ty_server.py](../src/solidlsp/language_servers/ty_server.py) | TY_VERSION=0.0.25 |  |
| [typescript_language_server.py](../src/solidlsp/language_servers/typescript_language_server.py) | INITIAL_TYPESCRIPT_VERSION=5.9.3; DEFAULT_TYPESCRIPT_VERSION=5.9.3; INITIAL_TYPESCRIPT_LANGUAGE_SERVER_VERSION=5.1.3; DEFAULT_TYPESCRIPT_LANGUAGE_SERVER_VERSION=5.1.3; build_npm_install_command; RuntimeDependency |  |
| [vscode_html_language_server.py](../src/solidlsp/language_servers/vscode_html_language_server.py) | DEFAULT_PACKAGE_NAME=vscode-langservers-extracted; DEFAULT_PACKAGE_VERSION=4.10.0; build_npm_install_command; RuntimeDependency |  |
| [vts_language_server.py](../src/solidlsp/language_servers/vts_language_server.py) | INITIAL_VTSLS_VERSION=0.2.9; DEFAULT_VTSLS_VERSION=0.2.9; build_npm_install_command; RuntimeDependency | github.com |
| [vue_language_server.py](../src/solidlsp/language_servers/vue_language_server.py) | build_npm_install_command; RuntimeDependency |  |
| [wolfram_language_server.py](../src/solidlsp/language_servers/wolfram_language_server.py) | No matching literal version/download marker; see source. | github.com, www.wolfram.com |
| [yaml_language_server.py](../src/solidlsp/language_servers/yaml_language_server.py) | INITIAL_YAML_LANGUAGE_SERVER_VERSION=1.19.2; DEFAULT_YAML_LANGUAGE_SERVER_VERSION=1.19.2; build_npm_install_command; RuntimeDependency |  |
| [zls.py](../src/solidlsp/language_servers/zls.py) | subprocess_run | github.com, ziglang.org |
