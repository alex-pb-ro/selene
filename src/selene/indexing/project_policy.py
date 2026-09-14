"""Adapt project configuration to index selection without retaining the project owner."""

import json
import weakref
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selene.project import Project


class ProjectIndexPolicy:
    def __init__(self, project: "Project"):
        self._project_ref = weakref.ref(project)

    @property
    def _project(self) -> "Project":
        project = self._project_ref()
        if project is None:
            raise RuntimeError("The project owning this index was released")
        return project

    def includes(self, relative_path: str, *, directory: bool) -> bool:
        if relative_path in {"", "."}:
            return True
        if any(part in {".git", ".selene"} for part in Path(relative_path).parts):
            return False
        normalized = "/" + relative_path.lstrip("/") + ("/" if directory else "")
        return not self._project._ignore_spec.match_file(normalized)

    def is_source(self, relative_path: str) -> bool:
        project = self._project
        return not project.language_backend.is_lsp() or any(
            language.get_source_fn_matcher().is_relevant_filename(relative_path) for language in project.project_config.language_servers
        )

    def signature(self) -> str:
        project = self._project
        return json.dumps(
            [
                project.selene_config.ignored_paths,
                project.project_config.ignored_paths,
                project.project_config.ignore_all_files_in_gitignore,
                [language.get_key() for language in project.project_config.language_servers],
                project.language_backend.value,
            ]
        )

    def refresh(self) -> None:
        self._project.refresh_ignored_paths()
