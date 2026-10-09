# DaVinci Project Organizer

DaVinci Project Organizer is a Python desktop application I made a while back to make media organization and project management in DaVinci Resolve easier for myself

The application helps users organize their media files, verify copied files, and manage media linked to their video editing projects, all through a simple graphical interface.

### Features

* **Media Organization:** Automatically sorts files into categories such as Video, Audio, Images, Projects, and Documents.
* **File Verification:** Uses SHA-256 checksums to verify copied files and skips identical files to avoid unnecessary duplicates.
* **DaVinci Resolve Integration:** Connects to Resolve to inspect the current project's media.
* **Media Importing:** Imports organized media files directly into the current Resolve project.
* **Missing Media Relinking:** Attempts to reconnect missing clips by matching filenames.
* **Project Backups:** Saves projects and exports `.drp` backups.
* **Operation History:** Keeps a record of file-management operations.

### How It Works

Choose a source folder and a destination, and the application scans and organizes the files while preserving their folder structure. It verifies copies to help ensure file integrity and avoids overwriting existing files.

Through the DaVinci Resolve integration, users can inspect project media, import organized files, attempt to relink missing clips, and export project backups.

### Built With

* Python
* PySide6
* DaVinci Resolve Scripting API
* SHA-256 file verification

**The goal of this project is to make media organization easier, reduce repetitive tasks, and create a smoother workflow for video editing in DaVinci Resolve.**
