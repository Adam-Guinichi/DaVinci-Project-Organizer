# DaVinci Project Organizer

DaVinci Project Organizer is a Python desktop application designed to simplify media organization and project management in DaVinci Resolve.

It helps users organize media, verify copied files, manage project media, and automate common editing workflows through a simple graphical interface.

### Features

* **Media Organization:** Automatically sorts files into categories such as Video, Audio, Images, Projects, and Documents.
* **File Verification:** Uses SHA-256 checksums to verify copies and avoid duplicates.
* **DaVinci Resolve Integration:** Inspects current project media and manages linked files.
* **Media Importing:** Imports organized media directly into Resolve.
* **Missing Media Relinking:** Attempts to reconnect missing clips by filename.
* **Project Backups:** Saves projects and exports `.drp` backups.
* **Operation History:** Tracks file-management operations.

### How It Works

Select a source folder and destination, and the application scans, organizes, and copies files while preserving folder structures. It verifies copied files and avoids unnecessary duplicates.

It also connects to DaVinci Resolve to inspect project media, import files, relink missing clips, and export backups.

### Built With

* Python
* PySide6
* DaVinci Resolve Scripting API
* SHA-256 file verification

**The goal is to simplify media management, reduce repetitive tasks, and improve the overall video editing workflow.**
