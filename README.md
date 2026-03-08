# Forza Car Folder Importer for Blender

A Blender addon for importing Forza Horizon and Forza Motorsport car models with automatic material, texture, and tiling support.

<img width="366" height="685" alt="image" src="https://github.com/user-attachments/assets/84b8c3c6-0968-4459-9cde-d5a5a3e521dc" />


---

## Features

- Scans car folders and imports all `.modelbin` files automatically
- Imports PBR materials with diffuse, normal, and other texture maps
- Selectable LOD levels (LOD0 = highest detail)
- Auto-detects and assigns textures from folders matching material names
- Distinguishes between decal and tiled materials (e.g. carbon fiber, badges)
- Sets up Mapping nodes automatically for tiled surfaces
- Built-in log tab for tracking import progress and errors

---

## Compatibility

- Forza Horizon 5 - confirmed working
- Forza Horizon 4 - confirmed working
- Older versions - may or may not work

---

## Installation

1. Download `forza_car_folder_importer.py`
2. Place it in your Blender addons folder:
   - Windows: `%APPDATA%\Blender Foundation\Blender\[version]\scripts\addons\`
   - Mac: `~/Library/Application Support/Blender/[version]/scripts/addons/`
   - Linux: `~/.config/blender/[version]/scripts/addons/`
3. Restart Blender and enable the addon in `Edit > Preferences > Add-ons`

---

## Usage

1. Press `N` in the 3D Viewport to open the sidebar, then go to the **Forza Main** tab.
2. Click the folder icon and select your car folder directly (not the full game path).
   - Example: `D:\Vehicles\CARS\[2016] Mercedes c63 Coupe\`
3. Choose your LOD level, enable materials, and optionally set a Game Media Root.
4. Click **Import Car Folder** and check the **Forza Log** tab for results.

---

## Auto-Texture Assignment (Experimental)

To use this feature, create folders inside your car folder named exactly like the material names. Place texture files inside those folders with recognizable keywords in their filenames.

Supported keyword types:
- Base color: `diff`, `diffuse`, `albedo`, `base`, `color`
- Normal: `normal`, `nrml`, `nrm`, `bump`
- Roughness: `roughness`, `rough`, `rgh`, `gloss`
- Metallic: `metallic`, `metal`, `met`
- AO: `ao`, `occlusion`, `icao`, `lcao`
- Alpha: `opacity`, `alpha`, `transparency`
- Emission: `emissive`, `emit`, `glow`

Supported formats: PNG, JPG, TGA, DDS, BMP, TIF, EXR, HDR, SWATCHBIN

---

## Tiled vs Decal Detection

The addon automatically classifies materials:

- **Tiled** (carbon fiber, patterns, plastic, rubber): Gets Texture Coordinate and Mapping nodes. Default scale is 4x4, adjustable in the Mapping node.
- **Decal** (badges, logos, numbers, gauges): Uses default UV mapping, no tiling.

Materials are tagged with a custom property (`forza_usage = "TILED"` or `"DECAL"`) for easy filtering in Blender.

---

## Game Media Root (Optional)

If material files reference paths like `Game:\Media\...`, set the Game Media Root to the folder that contains the `Media` directory.

Example: If `Game:\Media\...` maps to `D:\ForzaDump\Media\...`, set root to `D:\ForzaDump`.

Leave this empty if all files are already in the car folder.

---

## Troubleshooting

**No files found** - Make sure you selected the correct car folder containing `.modelbin` files.

**Materials not loading** - Check that `.materialbin` and `.swatchbin` files are present. Try setting the Game Media Root if paths reference `Game:\Media\...`.

**Auto-texture not working** - Verify the folder name matches the material name exactly (case-insensitive), and that texture filenames contain recognized keywords.

**Textures not tiling** - Check the Forza Log to confirm the material is tagged as TILED. Adjust the Mapping node scale in the shader editor as needed.

**"Cannot activate file selector" error** - Press ESC to close any open dialogs. Restart Blender if the issue persists.

---

## Credits

Original importer script by [Doliman100](https://github.com/Doliman100). All core import functionality is based on their work.

---

## License

MIT - Free to modify and distribute.
