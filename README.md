# Heat Insert Connections for Autodesk Fusion

Heat Insert Connections creates and edits a managed pair of native Fusion Hole features at one or more sketch-point locations:

- a blind heat-insert pocket with a lead-in countersink;
- a through screw-clearance hole in a second body; and
- a Button Head or Cap Head clearance pocket.

The head-seat surface does not need to exist. The add-in creates it at the selected **Head Seat Distance from Screw-to-Insert Face**.

## Command and selections

Open **Solid > Create > Insert Connection**. The **Action** dropdown switches the same dialog between **Create New** and **Edit Existing**.

For Create New, select:

- **Insert Entry Face**: the outside face where the insert is installed;
- **Screw-to-Insert Face**: the face where the screw leaves the screw-side body and continues toward the insert body; and
- **Locations**: one or more sketch points defining the connection axes.

For Edit Existing, select the managed Connection Set and change its Thread Size, Insert Profile, Screw Profile, Head Shape, Head Seat Distance, or Additional Insert Clearance Depth. The original faces and points are reused.

**Preview** is available for both actions and is off by default. During preview, the two affected bodies use a temporary 35% opacity override so internal cuts are easier to inspect. The original opacity is restored when preview is disabled or the dialog closes. Orphaned metadata is excluded from Edit Existing when its timeline group or managed features no longer exist.

## Hardware library

`hardware_library.json` contains separate insert and screw profiles. Thread Size filters both profile dropdowns, so mismatched profiles cannot be selected. Each screw profile supplies distinct Button Head and Cap Head clearance diameters.

**Add Insert Clearance** is off by default. When enabled, **Additional Insert Clearance Depth** extends the insert-side blind hole beyond the nominal insert length. When disabled, the profile depth is used unchanged.

The library includes M2 and M4 example profiles with intentionally approximate starter values, plus the initial M3 example. These are not standards or manufacturing recommendations. Verify every value against the actual hardware datasheet, screw standard, printer/material process, and required tolerances.

Restart the add-in after editing the library so its dropdowns reload the data.

### Lightweight profile editor

Open `hardware_library_editor.html` in a Chromium-based browser. When browser permissions allow it, the editor automatically loads an adjacent `hardware_library.json` or reopens the previously authorized file. On the first `file://` launch, browser security can require choosing **Open Library** once. The self-contained editor supports:

- creating, editing, duplicating, and deleting Insert and Screw profiles;
- filtering profiles by thread size;
- validating required fields, unique IDs, positive dimensions, and clearance relationships; and
- saving through the browser's File System Access API or downloading a replacement `hardware_library.json` when direct file access is unavailable.

Browser security requires an explicit file selection and save confirmation. Restart the Fusion add-in after saving profile changes.

For the simplest Windows workflow, double-click `Open Hardware Library Editor.cmd`. It opens a visible, loopback-only local server window and launches the editor with the adjacent library already loaded. **Save** writes the validated JSON directly back to the same folder. Close the server window to stop it. No administrator rights or installation are required when the Windows Python launcher is available.

## MVP constraints

- Capture Design History must be enabled.
- Both targets must be different solid bodies in the same component.
- Insert Entry Face, Screw-to-Insert Face, and the location sketch must be parallel.
- All locations must be sketch points from the same sketch.
- Assembly occurrence proxies, curved faces, arbitrary cutter bodies, and automatic reference repair are not supported yet.
- Connection Sets use native Hole features, linked projection sketches, a construction plane, User Parameters, Design Attributes, and a named timeline group.
- Helper sketches share a numbered `HIC <id>` name prefix so they remain adjacent in the Sketches folder. Fusion's public modeling API does not currently expose custom Sketches subfolders.

## Installation

Keep the Git repository outside Fusion so it can be updated normally with Git. On Windows, clone it for example to:

```text
%USERPROFILE%\Documents\GitHub\FusionHeatInsertAddIn
```

### Easiest Windows installation from a ZIP

1. Download **Code > Download ZIP** from the [GitHub repository](https://github.com/KidCe/FusionHeatInsertAddIn).
2. Extract the ZIP to a normal folder. Do not run the files from inside the ZIP archive.
3. Double-click **Install Fusion Add-in.cmd**.

The script copies only the Fusion runtime files to the current user's Fusion Add-ins directory. It does not require Git, Python, administrator rights, or a fixed Windows user name.

### Installation from a Git clone

From the repository directory, double-click **Install Fusion Add-in.cmd**, or run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install-FusionAddIn.ps1 -Clean
```

The script copies only the Fusion runtime files to:

```text
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\FusionHeatInsertAddIn
```

`%APPDATA%` resolves to the current Windows user's profile, so the script does not contain a fixed user name. Use `-FusionAddInsRoot` only when Fusion uses a non-default add-in location.

The profile editor remains in the repository. Double-click **Open Hardware Library Editor.cmd** to start a small loopback-only PowerShell server and open the self-contained HTML editor in the default browser. Python is not required for this normal workflow, and the editor can load and save the adjacent `hardware_library.json` directly. Close the PowerShell window to stop the local server. Save the updated library there, then double-click **Install Fusion Add-in.cmd** again to copy it into Fusion. The `-Clean` switch removes repository-only files left by older direct-copy installations.

The Python loopback server remains available for development, but it is not needed for normal users.

The manifest enables startup loading. If Fusion is already running, restart Fusion or reload **FusionHeatInsertAddIn** from **Utilities > Scripts and Add-Ins** after replacing its files.

## Validation boundary

Local tests cover the library, metadata, syntax, and configured Hole directions. These checks do not prove geometry inside Fusion. Before production use, create and edit a Connection Set and visually verify direction, dimensions, save/reopen behavior, and feature health.

## AI assistance disclosure

This project was created and maintained with substantial assistance from OpenAI Codex. The repository maintainer directed the work, made the project decisions, and is responsible for reviewing and using the result.
