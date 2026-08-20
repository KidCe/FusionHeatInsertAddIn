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

## MVP constraints

- Capture Design History must be enabled.
- Both targets must be different solid bodies in the same component.
- Insert Entry Face, Screw-to-Insert Face, and the location sketch must be parallel.
- All locations must be sketch points from the same sketch.
- Assembly occurrence proxies, curved faces, arbitrary cutter bodies, and automatic reference repair are not supported yet.
- Connection Sets use native Hole features, linked projection sketches, a construction plane, User Parameters, Design Attributes, and a named timeline group.
- Helper sketches share a numbered `HIC <id>` name prefix so they remain adjacent in the Sketches folder. Fusion's public modeling API does not currently expose custom Sketches subfolders.

## Installation

Copy the add-in folder to:

```text
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\FusionHeatInsertAddIn
```

The manifest enables startup loading. If Fusion is already running, restart Fusion or reload **FusionHeatInsertAddIn** from **Utilities > Scripts and Add-Ins** after replacing its files.

## Validation boundary

Local tests cover the library, metadata, syntax, and configured Hole directions. These checks do not prove geometry inside Fusion. Before production use, create and edit a Connection Set and visually verify direction, dimensions, save/reopen behavior, and feature health.
