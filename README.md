# Forza Car Folder Importer for Blender

A comprehensive Blender addon for importing Forza Horizon and Forza Motorsport car models with automatic material resolution, texture assignment, and intelligent tiling detection.

![Blender Version](https://img.shields.io/badge/Blender-2.80+-orange.svg)
![Version](https://img.shields.io/badge/version-1.5.0-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## ✨ Features

### Core Import
- **Automatic Discovery**: Recursively finds all `.modelbin` files in the selected car folder
- **Smart Path Resolution**: Automatically locates materials and textures without needing full game path
- **Material Support**: Imports PBR materials with diffuse, normal, and other texture maps
- **LOD Control**: Select which Level of Detail to import (LOD0-LOD7)
- **Bulk Import**: Imports entire car folders with all parts in one click
- **Texture Caching**: Efficiently reuses textures across multiple meshes

### Advanced Features
- **Auto-Texture Assignment** (Experimental): Automatically finds and assigns textures from folders matching material names
- **Intelligent Texture Classification**: Recognizes texture types by filename keywords (diff, normal, ao, roughness, etc.)
- **Decal vs Tiled Detection**: Automatically detects if materials are decals or tiled surfaces
- **Automatic Tiling Setup**: Creates Texture Coordinate + Mapping nodes for tiled materials (carbon, patterns, etc.)
- **Game Media Root Support**: Optional path to resolve `Game:\Media\...` references
- **Comprehensive Logging**: Built-in Forza Log tab for import progress and debugging
- **Material Usage Hints**: Tags materials as DECAL or TILED for easy filtering

## 🎮 Compatibility

| Game | Status |
|------|--------|
| **Forza Horizon 5** | ✅ Confirmed Working |
| **Forza Horizon 4** | ✅ Confirmed Working |
| Lower versions | ⚠️ May or may not work |

## 📥 Installation

1. Download `forza_car_folder_importer.py`
2. Copy to Blender addons folder:
   - **Windows**: `%APPDATA%\Blender Foundation\Blender\[version]\scripts\addons\`
   - **Mac**: `~/Library/Application Support/Blender/[version]/scripts/addons/`
   - **Linux**: `~/.config/blender/[version]/scripts/addons/`
3. Restart Blender
4. Enable in `Edit > Preferences > Add-ons`

## 🚀 Usage

### Quick Start

1. **Open the Panel**
   - Press `N` in the 3D Viewport to open the sidebar
   - Click on the **"Forza Main"** tab

2. **Select Car Folder**
   - Click the folder icon next to "Car Folder"
   - **Important**: Select the car folder directly, NOT the full game path
   - Example: `D:\Vehicles\CARS\[2016] Mercedes c63 Coupe\`

3. **Configure Options**
   - Toggle LOD levels (LOD0 = highest detail)
   - Enable/disable materials import
   - (Optional) Set Game Media Root if materials reference `Game:\Media\...`
   - (Optional) Enable "Auto Assign Textures" for automatic texture assignment

4. **Import**
   - Click "Import Car Folder"
   - Check "Forza Log" tab for progress
   - View imported meshes and materials

### UI Tabs

The addon provides three tabs in Blender's sidebar:

- **Forza Main**: Main import interface with all controls
- **Forza Tutorial**: Complete step-by-step guide and documentation
- **Forza Log**: Import logs, debugging info, and import summary

### Auto-Texture Feature (Experimental)

The auto-texture feature automatically finds and assigns textures from folders matching material names.

#### Requirements

1. **Folder Structure**: Create folders named exactly like your material names (case-insensitive)
   ```
   car_folder/
   ├── plastic_textured_001/     ← Must match material name
   │   ├── plastic_diff.png
   │   ├── plastic_nrml.png
   │   └── plastic_ao.png
   └── carbonfiber_001/
       ├── carbon_diff.png
       └── carbon_nrml.png
   ```

2. **Texture Keywords**: Use clear keywords in filenames:
   - **Base Color**: `diff`, `diffuse`, `albedo`, `base`, `color`, `col`
   - **Normal**: `normal`, `nrml`, `nrm`, `nor`, `bump`
   - **Roughness**: `roughness`, `rough`, `rgh`, `glos`, `gloss`
   - **Metallic**: `metallic`, `metal`, `met`
   - **AO**: `ao`, `occlusion`, `icao`, `lcao`, `cao`
   - **Alpha**: `opacity`, `opac`, `alpha`, `transparency`
   - **Emission**: `emissive`, `emission`, `emit`, `emis`, `glow`

3. **Supported Formats**: PNG, JPG, TGA, DDS, BMP, TIF, EXR, HDR, SWATCHBIN

#### How It Works

1. When a material is created (e.g., `plastic_textured_001`)
2. The addon searches for a folder with the same name
3. Scans that folder (and subfolders) for texture files
4. Classifies textures by filename keywords
5. Automatically assigns them to the material's shader nodes

#### Tiled vs Decal Detection

The addon automatically detects if a material should be tiled or treated as a decal:

- **Tiled Materials**: Carbon fiber, patterns (`ptn_`), details (`dtl_`), plastic, rubber, etc.
  - Automatically gets Texture Coordinate + Mapping nodes
  - Default scale: 4x4 (adjustable in Mapping node)
  
- **Decal Materials**: Badges, emblems, logos, gauges, numbers, etc.
  - No automatic tiling
  - Uses default UV mapping

### Game Media Root (Optional)

If your material files reference paths like `Game:\Media\cars\_library\...`, you can optionally set a "Game Media Root" path:

- Point to the folder that **contains** the `Media` directory
- Example: If `Game:\Media\...` should resolve to `D:\ForzaDump\Media\...`, set root to `D:\ForzaDump`
- Leave empty if all files are in the car folder

## 📁 Folder Structure Example

```
[2016] Mercedes c63 Coupe/          ← Select this folder
├── Exported/
│   └── scene/
│       └── _library/
│           └── scene/
│               └── MER_C63AMGCoupe_Alt_001/
│                   └── Scene/
│                       ├── exterior/
│                       │   ├── bumperF/
│                       │   │   └── bumperF_a.modelbin
│                       │   └── hood/
│                       │       └── hood_a.modelbin
│                       └── interior/
│                           └── dash/
│                               └── dash_a.modelbin
├── frc_output/
│   └── ~mer_c63amgcoupe_16/
│       └── mer_c63amgcoupe_16_materials/
│           ├── plastic_textured_001/    ← Auto-texture folder
│           │   ├── org_grain_008_nrml.png
│           │   └── plastic_diff.png
│           └── carbonfiber_001/
│               └── carbon_nrml.png
└── Media/                              ← Optional: if using Game Media Root
    └── _library/
        └── materials/
            └── carpaint.materialbin
```

## ⚙️ Options

### Level of Detail (LOD)

| LOD | Description |
|-----|-------------|
| LOD0 | Highest detail (default) |
| LOD1-3 | Medium detail levels |
| LOD4-7 | Lower detail levels |

**Tip**: Import only LOD0 for best quality, or import multiple LODs to compare detail levels.

### Materials

- **Import Materials & Textures**: Imports materials and textures (slower, complete)
- **Use Material File Names**: Uses `.materialbin` filename for material names (cleaner)
- **Auto Assign Textures** (Experimental): Automatically finds and assigns textures from matching folders

### Material Usage Hints

Materials are automatically tagged with usage hints:
- `material["forza_usage"] = "TILED"` - For tiled/repeatable textures
- `material["forza_usage"] = "DECAL"` - For decals/badges/logos

You can filter materials in Blender using these custom properties.

## 🐛 Troubleshooting

### No files found

**Problem**: "Found 0 modelbin files"

**Solution**: 
- Make sure you selected the car folder containing `.modelbin` files
- Check that files are actually `.modelbin` extension
- Try selecting a parent folder if files are in subfolders

### Import failed

**Problem**: "Import failed" error

**Solution**:
1. Check the **Forza Log** tab for detailed error messages
2. Open System Console: `Window > Toggle System Console`
3. Look for error messages in red
4. Check file compatibility (FH4/FH5 work best)
5. Report issue with error log

### Materials not loading

**Problem**: Models import but materials are gray

**Solution**:
- Ensure material files (`.materialbin`) exist in the folder
- Check that texture files (`.swatchbin`) are present
- Try setting "Game Media Root" if materials reference `Game:\Media\...`
- Check Forza Log tab for material resolution errors

### Auto-texture not working

**Problem**: Textures not being auto-assigned

**Solution**:
1. Check **Forza Log** tab for detailed assignment logs
2. Verify folder name matches material name exactly (case-insensitive)
3. Ensure texture files are inside the matching folder
4. Check that filenames contain recognized keywords (diff, normal, ao, etc.)
5. Verify texture file extensions are supported (PNG, JPG, TGA, DDS, etc.)

### Textures not tiling

**Problem**: Tiled textures appear as single decals

**Solution**:
- Check if material is detected as "TILED" in Forza Log
- Verify material name contains tiled keywords (carbon, ptn, dtl, plastic, etc.)
- Adjust Mapping node scale in shader editor if tiling is too strong/weak
- For materials from materialbin files, ensure they're classified as TILED

### "Cannot activate file selector" error

**Problem**: Error when clicking folder browse

**Solution**:
- Press `ESC` to close any open file browsers
- Make sure no other import/export dialog is open
- Restart Blender if issue persists

## ❓ FAQ

**Q: Do I need to extract game files first?**  
A: Yes, use game extraction tools to get `.modelbin` files from the game archives.

**Q: Can I import from FH5?**  
A: Yes! FH5 is confirmed working.

**Q: Why are some meshes named "LODS0" when I import LOD1?**  
A: The mesh name is just a label. Meshes can belong to multiple LOD levels. The import is working correctly.

**Q: Can I import multiple cars at once?**  
A: Not directly. Select one car folder at a time. However, the addon imports ALL parts in that folder automatically.

**Q: Where's the game path setting?**  
A: You don't need it for most cases! Just select the car folder. Optionally set "Game Media Root" if materials reference `Game:\Media\...`.

**Q: How do I know if auto-texture worked?**  
A: Check the **Forza Log** tab. It shows detailed logs of folder searches, texture classification, and assignment.

**Q: Can I adjust the tiling scale?**  
A: Yes! For tiled materials, find the Mapping node in the shader editor and adjust the Scale X/Y values.

**Q: What's the difference between DECAL and TILED?**  
A: DECAL materials (badges, logos) don't tile. TILED materials (carbon, patterns) automatically get Mapping nodes for tiling.

## 🙏 Credits

**Original Script**: [Doliman100](https://github.com/Doliman100)  
This addon is based on Doliman100's excellent Forza ModelBin importer script. All credit for the core import functionality goes to the original author.

**Addon Development**: Community contributors

## 📄 License

MIT License - Feel free to modify and distribute

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Areas for Improvement
- FH5 advanced features support
- More material shader types
- Export functionality
- Performance optimizations
- Additional texture keyword recognition

## 📝 Changelog

### Version 1.5.0
- ✨ Added Auto-Texture Assignment feature (experimental)
- ✨ Added intelligent Decal vs Tiled texture detection
- ✨ Automatic Mapping node setup for tiled materials
- ✨ Added Forza Tutorial tab with comprehensive guide
- ✨ Added Forza Log tab for import progress and debugging
- ✨ Added Game Media Root option for resolving `Game:\Media\...` paths
- ✨ Expanded texture keyword recognition (nrml, opac, glos, icao, etc.)
- ✨ Material usage hints (DECAL/TILED) stored as custom properties


### Version 1.3.2
- Simplified folder selection instructions
- Clarified compatibility (FH4/FH5 confirmed)
- Added highlighted note about not needing full game path

### Version 1.3.0
- Added sidebar panel interface
- Improved LOD selection with toggle buttons
- Added instructions and compatibility info in UI
- Smart path resolution for materials

### Version 1.0.0
- Initial release based on Doliman100's script
- Automatic folder scanning
- Material support

---

**Note**: This tool is for educational and modding purposes. Respect game copyrights and terms of service.
