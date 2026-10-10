
"""Read-only connection and Media Pool inspection for DaVinci Resolve."""

import os
import sys
from pathlib import Path


def _configure_resolve_api():
    program_data = Path(
        os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    )

    api_root = (
        program_data
        / "Blackmagic Design"
        / "DaVinci Resolve"
        / "Support"
        / "Developer"
        / "Scripting"
    )
    modules = api_root / "Modules"

    program_files = Path(
        os.environ.get("ProgramFiles", r"C:\Program Files")
    )
    library = (
        program_files
        / "Blackmagic Design"
        / "DaVinci Resolve"
        / "fusionscript.dll"
    )

    if modules.is_dir() and str(modules) not in sys.path:
        sys.path.insert(0, str(modules))

    if library.is_file():
        os.environ.setdefault("RESOLVE_SCRIPT_LIB", str(library))

    os.environ.setdefault("RESOLVE_SCRIPT_API", str(api_root))


def inspect_resolve():
    """
    Connect to the running Resolve instance and return a read-only report.

    No media is imported, no paths are changed, and no project is saved.
    """
    _configure_resolve_api()

    try:
        import DaVinciResolveScript as dvr
    except Exception as error:
        raise RuntimeError(
            "Could not import DaVinciResolveScript. "
            "Check the Resolve scripting installation.\n\n"
            f"{type(error).__name__}: {error}"
        ) from error

    try:
        resolve = dvr.scriptapp("Resolve")
    except Exception as error:
        raise RuntimeError(
            "The Resolve scripting API could not connect.\n\n"
            f"{type(error).__name__}: {error}"
        ) from error

    if resolve is None:
        raise RuntimeError(
            "Resolve returned no connection. Open DaVinci Resolve, "
            "open a project, and try again."
        )

    manager = resolve.GetProjectManager()
    project = manager.GetCurrentProject()

    if project is None:
        return {
            "project": "(No project open)",
            "timeline": "(No active timeline)",
            "items": [],
            "total": 0,
            "missing": 0,
            "unknown": 0,
        }

    timeline = project.GetCurrentTimeline()
    media_pool = project.GetMediaPool()
    root_folder = media_pool.GetRootFolder()

    items = []
    visited_folders = set()

    def visit_folder(folder, folder_path=""):
        folder_name = folder.GetName() or "Unnamed folder"
        current_folder_path = (
            f"{folder_path}/{folder_name}".strip("/")
        )

        for clip in folder.GetClipList() or []:
            name = clip.GetName() or "Unnamed clip"

            try:
                properties = clip.GetClipProperty() or {}
            except Exception:
                properties = {}

            # Resolve versions may expose the path under different labels.
            path_value = ""
            for key in (
                "File Path",
                "File path",
                "FileName",
                "File Name",
                "Full Path",
            ):
                value = properties.get(key)
                if value:
                    path_value = str(value).strip()
                    break

            if path_value:
                path = Path(path_value)
                if path.is_file():
                    status = "OK"
                else:
                    status = "MISSING"
            else:
                path_value = "(Path not exposed)"
                status = "UNKNOWN"

            items.append({
                "name": name,
                "folder": current_folder_path,
                "path": path_value,
                "status": status,
            })

        for subfolder in folder.GetSubFolderList() or []:
            try:
                folder_id = subfolder.GetUniqueId()
            except Exception:
                folder_id = id(subfolder)

            if folder_id in visited_folders:
                continue

            visited_folders.add(folder_id)
            visit_folder(subfolder, current_folder_path)

    visit_folder(root_folder)

    return {
        "project": project.GetName(),
        "timeline": (
            timeline.GetName() if timeline is not None
            else "(No active timeline)"
        ),
        "items": items,
        "total": len(items),
        "missing": sum(
            item["status"] == "MISSING" for item in items
        ),
        "unknown": sum(
            item["status"] == "UNKNOWN" for item in items
        ),
    }