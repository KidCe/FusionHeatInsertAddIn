# Heat Insert Connections for Autodesk Fusion

Create matching screw holes and heat-insert pockets in Autodesk Fusion 360 from
a few selections. The add-in is designed for 3D-printed parts where two bodies
need to be joined with a screw and a brass heat-set insert.

## See it first

> 🎬 **Demo placeholder** — Add a short GIF or 30–60 second screen recording
> here showing: pick sketch points → let the sketch fill the Screw Entry Face → choose the
> insert profile → preview → create.
>
> Suggested file: `docs/demo.gif` or a short linked YouTube/Loom video.

## What it does

You select the screw-entry surface and one or more sketch points. Heat Insert
Connections then creates and keeps aligned:

- a blind heat-insert pocket with a lead-in countersink;
- a through screw-clearance hole in the second body; and
- a Button Head or Cap Head clearance pocket.

The head-seat surface does not need to exist. The add-in creates it at the
selected **Head Seat Distance from Screw Entry Face**. With automatic face
detection enabled, you only select the screw-entry face; Fusion finds the
matching opposing planar face when the geometry is unambiguous.

## Quick start

1. Install the add-in with **Install Fusion Add-in.cmd**. The repository stays
   outside Fusion so it remains easy to update.
2. In Fusion, open **Solid > Create > Insert Connection**.
3. Select the sketch points first. The sketch automatically fills the Screw Entry
   Face when it is based on a native planar face. Then choose matching insert and
   screw profiles, set the optional hole tolerance, preview, and create.

The default workflow is intentionally short. Detailed manual selection,
editing, profile authoring, automatic-face-detection rules, and limitations are
documented below.

## Is it a good fit?

Use it when two solid bodies in the same Fusion component meet across parallel
planar faces and the connection locations can be represented by sketch points.
It is useful for printed housings, covers, brackets, and other parts that need
repeatable screw-and-insert alignment.

It currently does not infer curved or angled interfaces, arbitrary multi-body
stackups, or broken references after major model changes. Automatic face
detection is limited to a unique opposing planar face within 0.2 mm; manual
face selection is available when the geometry is unusual.

## Command and selections

Open **Solid > Create > Insert Connection**. The **Action** dropdown switches the same dialog between **Create New** and **Edit Existing**.

For the default **Create New** workflow, create a sketch on the face where the screw is inserted, add the connection points there, and select:

- **Locations**: one or more sketch points on that face. This comes first;
- **Auto-fill Screw Entry Face from Sketch**: enabled by default. The face hosting
  the sketch is suggested automatically when Fusion exposes it as a native planar
  face;
- **Screw Entry Face**: review the suggestion. Clear it to turn off the suggestion
  for this dialog, then select another matching planar face manually.

With **Auto-detect Insert Face** enabled, Fusion finds the opposing planar face on another solid body in the same component. The candidate must face the Screw Entry Face, cover every selected location, and be no more than **0.2 mm** away. If multiple candidates are equally close or no unique candidate is found, the command stops safely and explains how to switch to manual selection.

Disable **Auto-detect Insert Face** when the geometry is unusual or ambiguous. The manual fallback then exposes the original two-face workflow: select **Insert Entry Face** and **Screw Entry Face** explicitly. The location points must still lie on the selected Screw Entry Face.

For Create New, select:

- **Insert Entry Face**: the outside face where the insert is installed;
- **Screw Entry Face**: the face where the screw leaves the screw-side body and continues toward the insert body; and
- **Locations**: one or more sketch points defining the connection axes. In the normal workflow this is the sketch-host face used above.

For Edit Existing, select the managed Connection Set and change its Thread Size, Insert Profile, Insert Hole Diameter Tolerance, Screw Profile, Head Shape, Head Seat Distance, or Additional Insert Clearance Depth. The original faces and points are reused.

**Preview** is available for both actions and is off by default. During preview, the two affected bodies use a temporary 35% opacity override so internal cuts are easier to inspect. The original opacity is restored when preview is disabled or the dialog closes. Orphaned metadata is excluded from Edit Existing when its timeline group or managed features no longer exist.

## Hardware library

`hardware_library.json` contains separate insert and screw profiles. Thread Size filters both profile dropdowns, so mismatched profiles cannot be selected. Each screw profile supplies distinct Button Head and Cap Head clearance diameters.

**Insert Hole Diameter Tolerance** adds a positive diameter offset to the selected insert profile. The available values are 0.00, 0.05, 0.10, 0.15 and 0.20 mm; for example, a 4.00 mm M3 profile becomes 4.05 or 4.10 mm. This is a simple hardware-fit allowance, not slicer compensation, and it affects only the cylindrical insert hole.

**Add Insert Clearance** is off by default. When enabled, **Additional Insert Clearance Depth** extends the insert-side blind hole beyond the nominal insert length. When disabled, the profile depth is used unchanged.

The library includes RUTHEX M2, M3, M4 and M6 insert profiles (including Short and VORON variants where applicable), plus researched M2/M3/M4/M6 Button Head and Cap Head screw profiles. The complete RUTHEX metric catalogue and screw-dimension sources are documented in [`RESEARCH_hardware_dimensions.md`](RESEARCH_hardware_dimensions.md). Generic example profiles remain available for comparison but are intentionally approximate. Verify every value against the actual hardware datasheet, screw standard, printer/material process, and required tolerances.

Restart the add-in after editing the library so its dropdowns reload the data.

### Lightweight profile editor

Open `hardware_library_editor.html` in a Chromium-based browser. When browser permissions allow it, the editor automatically loads an adjacent `hardware_library.json` or reopens the previously authorized file. On the first `file://` launch, browser security can require choosing **Open Library** once. The self-contained editor supports:

- creating, editing, duplicating, and deleting Insert and Screw profiles;
- filtering profiles by thread size;
- validating required fields, unique IDs, positive dimensions, and clearance relationships; and
- saving through the browser's File System Access API or downloading a replacement `hardware_library.json` when direct file access is unavailable.

Browser security requires an explicit file selection and save confirmation. Restart the Fusion add-in after saving profile changes.

For the simplest Windows workflow, double-click `Open Hardware Library Editor.cmd`. It starts the bundled PowerShell loopback server and launches the editor with the adjacent library already loaded. **Save** writes the validated JSON directly back to the same folder. Close the PowerShell window to stop it. No Python installation, administrator rights, or other runtime setup is required for the normal Windows workflow.

## MVP constraints

- Capture Design History must be enabled.
- Both targets must be different solid bodies in the same component.
- In manual mode, Insert Entry Face, Screw Entry Face, and the location sketch must be parallel.
- All locations must be sketch points from the same sketch.
- Assembly occurrence proxies, curved faces, arbitrary cutter bodies, and automatic reference repair are not supported yet.
- Automatic Insert Face detection supports planar opposing faces only; it does not infer curved, angled, or multi-body stackups.
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
