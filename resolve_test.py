
import os
import sys
from pathlib import Path

PROGRAM_DATA = Path(
    os.environ.get("PROGRAMDATA", r"C:\ProgramData")
)

API_ROOT = (
    PROGRAM_DATA
    / "Blackmagic Design"
    / "DaVinci Resolve"
    / "Support"
    / "Developer"
    / "Scripting"
)

MODULES = API_ROOT / "Modules"

# Common Windows install location; adjust if Resolve is installed elsewhere.
LIBRARY = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "Blackmagic Design"
    / "DaVinci Resolve"
    / "fusionscript.dll"
)

if MODULES.is_dir():
    sys.path.insert(0, str(MODULES))

if LIBRARY.is_file():
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", str(LIBRARY))

os.environ.setdefault("RESOLVE_SCRIPT_API", str(API_ROOT))

print("Checking DaVinci Resolve scripting setup...")
print(f"Python: {sys.executable}")
print(f"API modules: {MODULES}")
print(f"Modules folder exists: {MODULES.is_dir()}")
print(f"Scripting library exists: {LIBRARY.is_file()}")

try:
    import DaVinciResolveScript as dvr
except Exception as error:
    print("\nCould not load the Resolve scripting module.")
    print(f"{type(error).__name__}: {error}")
    print("\nCheck the scripting paths and Python compatibility.")
    raise SystemExit(1)

try:
    resolve = dvr.scriptapp("Resolve")

    if resolve is None:
        print("\nResolve did not return a connection.")
        print("Make sure Resolve is running and scripting access is enabled.")
        raise SystemExit(2)

    print("\nConnected to DaVinci Resolve!")

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject()

    if project is None:
        print("No project is currently open.")
        raise SystemExit(0)

    print(f"Project: {project.GetName()}")

    timeline = project.GetCurrentTimeline()

    if timeline is None:
        print("No active timeline. The project connection is working.")
    else:
        print(f"Timeline: {timeline.GetName()}")

    # Read-only inspection of Media Pool folders and clips.
    media_pool = project.GetMediaPool()
    root_folder = media_pool.GetRootFolder()

    total_clips = 0
    missing_paths = []
    visited = set()

    def inspect_folder(folder, folder_path=""):
        global total_clips

        folder_name = folder.GetName() or "Untitled"
        current_path = f"{folder_path}/{folder_name}"

        for clip in folder.GetClipList() or []:
            total_clips += 1

            name = clip.GetName() or "Unnamed clip"
            props = clip.GetClipProperty() or {}

            # Property labels can vary across Resolve versions.
            file_path = (
                props.get("File Path")
                or props.get("File path")
                or props.get("FileName")
                or ""
            )

            if file_path:
                exists = Path(file_path).is_file()
                state = "OK" if exists else "PATH NOT FOUND"

                print(f"{state}: {name} — {file_path}")

                if not exists:
                    missing_paths.append((name, file_path))
            else:
                print(
                    f"INSPECT: {name} — no file path exposed "
                    f"in the expected property"
                )

        for subfolder in folder.GetSubFolderList() or []:
            # Guard against accidentally revisiting a folder.
            try:
                folder_id = subfolder.GetUniqueId()
            except Exception:
                folder_id = id(subfolder)

            if folder_id in visited:
                continue

            visited.add(folder_id)
            inspect_folder(subfolder, current_path)

    inspect_folder(root_folder)

    print("\n--- READ-ONLY REPORT ---")
    print(f"Media Pool items inspected: {total_clips}")
    print(f"Paths not found: {len(missing_paths)}")
    print("No project changes were made.")

except SystemExit:
    raise
except Exception as error:
    print(f"\nConnection or inspection failed: {type(error).__name__}: {error}")
    raise