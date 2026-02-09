# Forza Car Folder Importer for Blender

A user-friendly Blender addon for importing Forza Horizon and Forza Motorsport car models with automatic material resolution.

![Blender Version](https://img.shields.io/badge/Blender-2.80+-orange.svg)
![Version](https://img.shields.io/badge/version-1.3.2-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

<img width="274" height="542" alt="image" src="https://github.com/user-attachments/assets/475fa4d4-2734-4155-ae14-1d53dc2c8aed" />


## Features

- **Automatic Discovery**: Recursively finds all `.modelbin` files in the selected car folder
- **Smart Path Resolution**: Automatically locates materials and textures without needing full game path
- **Material Support**: Imports PBR materials with diffuse, normal, and other texture maps
- **LOD Control**: Select which Level of Detail to import (LOD0-LOD7)
- **Bulk Import**: Imports entire car folders with all parts in one click
- **Sidebar Panel**: Clean, integrated UI in Blender's 3D viewport sidebar
- **Texture Caching**: Efficiently reuses textures across multiple meshes

## Compatibility

| Game | Status |
|------|--------|
| **Forza Horizon 5** | ✅ Confirmed Working |
| **Forza Horizon 4** | ✅ Confirmed Working |
| Lower versions |  May or may not work |

## 📥 Installation

### Method 1: Download Release
1. Download the latest `forza_car_folder_importer.py`.
2. Open Blender
3. Go to `Edit > Preferences > Add-ons`
4. Click `Install...`
5. Select the downloaded `.py` file
6. Enable the addon by checking the checkbox

### Method 2: Manual Installation
1. Download `forza_car_folder_importer.py`
2. Copy to Blender addons folder:
   - **Windows**: `%APPDATA%\Blender Foundation\Blender\[version]\scripts\addons\`
   - **Mac**: `~/Library/Application Support/Blender/[version]/scripts/addons/`
   - **Linux**: `~/.config/blender/[version]/scripts/addons/`
3. Restart Blender
4. Enable in `Edit > Preferences > Add-ons`

##  Usage

### Quick Start

1. **Open the Panel**
   - Press `N` in the 3D Viewport to open the sidebar
   - Click on the **"Forza"** tab

2. **Select Car Folder**
   - Click the folder icon 📁 next to "Car Folder"
   - **Important**: Select the car folder directly, NOT the full game path
   - Example: `D:\Vehicles\CARS\koe_one_15\`

3. **Configure Options**
   - Toggle LOD levels (LOD0 = highest detail)
   - Enable/disable materials import

4. **Import**
   - Click "Import Car Folder"
   - Wait for import to complete

### Folder Structure Example

```
koe_one_15/                    ← Select this folder
├── scene/
│   ├── Exterior/
│   │   ├── BumperF/
│   │   │   └── bumperF_a.modelbin
│   │   ├── Hood/
│   │   │   └── hood_a.modelbin
│   │   └── Doors/
│   │       └── doorLF_a.modelbin
│   └── Interior/
│       └── dash/
│           └── dash_a.modelbin
└── materials/
    └── carpaint.materialbin
```

##  Options

### Level of Detail (LOD)

| LOD | Description |
|-----|-------------|
| LOD0 | Highest detail (default) |
| LOD1-3 | Medium detail levels |
| LOD4-7 | Lower detail levels |

**Tip**: Import only LOD0 for best quality, or import multiple LODs to compare detail levels.

### Materials

- **Enabled**: Imports materials and textures (slower, complete)
- **Disabled**: Geometry only (faster)

##  Troubleshooting

### No files found

**Problem**: "Found 0 modelbin files"

**Solution**: 
- Make sure you selected the car folder containing `.modelbin` files
- Check that files are actually `.modelbin` extension
- Try selecting a parent folder if files are in subfolders

### Import failed

**Problem**: "Import failed" error

**Solution**:
1. Open System Console: `Window > Toggle System Console`
2. Look for error messages in red
3. Check file compatibility (FH4/FH5 work best)
4. Report issue with error log

### Materials not loading

**Problem**: Models import but materials are gray

**Solution**:
- Ensure material files (`.materialbin`) exist in the folder
- Check that texture files (`.swatchbin`) are present
- Try disabling materials temporarily to test geometry import

### "Cannot activate file selector" error

**Problem**: Error when clicking folder browse

**Solution**:
- Press `ESC` to close any open file browsers
- Make sure no other import/export dialog is open
- Restart Blender if issue persists

##  FAQ

**Q: Do I need to extract game files first?**  
A: Yes, use game extraction tools to get `.modelbin` files from the game archives.

**Q: Can I import from FH5?**  
A: Yes! FH5 is confirmed working.

**Q: Why are some meshes named "LODS0" when I import LOD1?**  
A: The mesh name is just a label. Meshes can belong to multiple LOD levels. The import is working correctly.

**Q: Can I import multiple cars at once?**  
A: Not directly. Select one car folder at a time. However, the addon imports ALL parts in that folder automatically.

**Q: Where's the game path setting?**  
A: You don't need it! Just select the car folder. The script automatically finds materials and textures.

## 🙏 Credits

**Original Script**: [Doliman100](https://github.com/Doliman100)  
This addon is based on Doliman100's excellent Forza ModelBin importer script. All credit for the core import functionality goes to the original author.

**Addon Development**: Community contributors

## License

MIT License - Feel free to modify and distribute

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Areas for Improvement
- FH5 advanced features support
- More material shader types
- Export functionality
- Performance optimizations

## Changelog

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
