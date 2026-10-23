"""Locate and configure the DaVinci Resolve scripting API on this computer."""

import os
import sys
from pathlib import Path


def _default_locations():
    """Return the standard API and Fusion library locations for this OS."""
    if sys.platform == "win32":
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        api = (
            program_data
            / "Blackmagic Design"
            / "DaVinci Resolve"
            / "Support"
            / "Developer"
            / "Scripting"
        )
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        library = (
            program_files
            / "Blackmagic Design"
            / "DaVinci Resolve"
            / "fusionscript.dll"
        )
    elif sys.platform == "darwin":
        api = Path(
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve"
            "/Developer/Scripting"
        )
        library = Path(
            "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/"
            "Libraries/Fusion/fusionscript.so"
        )
    else:
        api = Path("/opt/resolve/Developer/Scripting")
        library = Path("/opt/resolve/libs/Fusion/fusionscript.so")

    return api, library


def configure_resolve_api():
    """Add Resolve's Python modules and Fusion library to this process.

    Standard install locations are detected automatically. Non-standard
    installs can be configured with RESOLVE_SCRIPT_API and
    RESOLVE_SCRIPT_LIB, as documented by Blackmagic Design.
    """
    default_api, default_library = _default_locations()
    api_root = Path(os.environ.get("RESOLVE_SCRIPT_API", default_api)).expanduser()
    library = Path(os.environ.get("RESOLVE_SCRIPT_LIB", default_library)).expanduser()
    modules = api_root / "Modules"

    if modules.is_dir():
        module_path = str(modules)
        if module_path not in sys.path:
            sys.path.insert(0, module_path)

    # The API module loads this shared library when it is imported.
    if library.is_file():
        os.environ.setdefault("RESOLVE_SCRIPT_LIB", str(library))
        if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            # Keep the handle alive for as long as this module is loaded.
            _dll_directory_handle = os.add_dll_directory(str(library.parent))
            globals()["_dll_directory_handle"] = _dll_directory_handle

    os.environ.setdefault("RESOLVE_SCRIPT_API", str(api_root))
    return api_root, modules, library


def import_resolve_script():
    """Configure paths and import DaVinciResolveScript with useful errors."""
    api_root, modules, library = configure_resolve_api()
    try:
        import DaVinciResolveScript as dvr
    except Exception as exc:
        raise RuntimeError(
            "Could not load DaVinciResolveScript. Confirm DaVinci Resolve is "
            "installed and its scripting API is available. Checked:\n"
            f"  API modules: {modules}\n"
            f"  Fusion library: {library}\n\n"
            "For a custom install, set RESOLVE_SCRIPT_API to the Scripting "
            "folder and RESOLVE_SCRIPT_LIB to the fusionscript library. "
            f"\n\nDetails: {exc}"
        ) from exc
    return dvr
