"""Regression tests for core package decoupling and import hygiene."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path


_DECOUPLED_PACKAGES = ("core", "services", "extractors", "schemas", "utils")
_FORBIDDEN_WEB_MODULES = {"fastapi", "starlette", "uvicorn"}


def test_core_package_imports_without_fastapi_handler() -> None:
    """app.core must import cleanly and must not re-export FastAPI exception handlers."""
    core_pkg = importlib.import_module("app.core")
    core_exceptions = importlib.import_module("app.core.exceptions")
    core_config = importlib.import_module("app.core.config")

    assert hasattr(core_config, "Settings")
    assert not hasattr(core_pkg, "register_exception_handlers")
    assert "register_exception_handlers" not in getattr(core_pkg, "__all__", [])
    assert not hasattr(core_exceptions, "register_exception_handlers")


def test_core_preserves_domain_exception_exports() -> None:
    """All domain exceptions must remain exported from app.core and app.core.exceptions."""
    import app.core as core_pkg
    import app.core.exceptions as core_exceptions

    expected_exceptions = [
        "MemoriaReaderError",
        "UnsupportedFormatError",
        "FileTooLargeError",
        "EmptyDocumentError",
        "CorruptedDocumentError",
        "PasswordProtectedDocumentError",
        "InvalidEncodingError",
        "DocumentNotFoundError",
        "DocumentStatusNotFoundError",
        "RequestTimeoutError",
        "ExtractionError",
        "StorageError",
        "OcrNotConfiguredError",
        "ObsidianPersistenceError",
    ]
    for name in expected_exceptions:
        assert hasattr(core_pkg, name), f"{name} missing from app.core"
        assert name in core_pkg.__all__, f"{name} missing from app.core.__all__"
        assert getattr(core_pkg, name) is getattr(core_exceptions, name)


def test_api_layer_owns_exception_handler_registration() -> None:
    """register_exception_handlers must live in app.api.exception_handlers and wire into app.main."""
    api_handlers = importlib.import_module("app.api.exception_handlers")
    main_module = importlib.import_module("app.main")

    assert callable(getattr(api_handlers, "register_exception_handlers", None))
    assert getattr(main_module, "app", None) is not None


def test_decoupled_packages_have_no_web_framework_imports() -> None:
    """Core, services, extractors, schemas, and utils must remain free of web dependencies."""
    app_root = Path(__file__).resolve().parent.parent / "app"
    violations: list[str] = []

    for package_name in _DECOUPLED_PACKAGES:
        package_dir = app_root / package_name
        for py_file in sorted(package_dir.rglob("*.py")):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in _FORBIDDEN_WEB_MODULES:
                            violations.append(f"{py_file}:{node.lineno} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.split(".")[0] in _FORBIDDEN_WEB_MODULES:
                        violations.append(f"{py_file}:{node.lineno} imports from {node.module}")

    assert violations == [], f"Forbidden web framework imports found: {violations}"
