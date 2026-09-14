import pickle
from collections.abc import Iterable
from pathlib import Path
from typing import Any, BinaryIO


class DataOnlyUnpickler(pickle.Unpickler):
    """Decode cached data using only explicitly supplied, inert value classes.

    Unknown globals are rejected before they can be imported or invoked. Callers must not allow
    classes with executable deserialisation hooks or constructors with side effects.
    """

    def __init__(self, file: BinaryIO, allowed_classes: Iterable[type] = ()) -> None:
        super().__init__(file)
        self._allowed_classes = {(cls.__module__, cls.__qualname__): cls for cls in allowed_classes}

    def find_class(self, module: str, name: str) -> Any:
        cls = self._allowed_classes.get((module, name))
        if cls is None:
            raise pickle.UnpicklingError(f"Forbidden cache global: {module}.{name}")
        return cls

    @classmethod
    def load_file(cls, path: str | Path, allowed_classes: Iterable[type] = ()) -> Any:
        """Load cached values while rejecting executable pickle globals."""
        with open(path, "rb") as stream:
            return cls(stream, allowed_classes).load()
