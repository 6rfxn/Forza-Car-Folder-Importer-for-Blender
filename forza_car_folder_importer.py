"""
Forza Car Folder Importer for Blender
Based on the original Forza ModelBin importer script by Doliman100
https://github.com/Doliman100/Forza-Motorsport-file-formats

This addon adapts the original script into a user-friendly Blender panel
with automatic folder scanning and material resolution.

Confirmed working: FH4 and FH5
Lower versions of FH4 may or may not work.
"""

bl_info = {
    "name": "Forza Car Folder Importer",
    "author": "Doliman100 (original script), Community (addon)",
    "version": (1, 3, 2),
    "blender": (2, 80, 0),
    "location": "View3D > Sidebar > Forza Tab",
    "description": "Import Forza car folders with materials. Based on Doliman100's modelbin importer.",
    "category": "Import-Export",
    "warning": "FH4 and FH5 confirmed working. Lower versions may or may not work.",
}

import bpy
import bmesh
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty, PointerProperty
from bpy.types import PropertyGroup
from collections import defaultdict
import io
import math
import os
import struct
from uuid import UUID

# ============================================================================
# BINARY STREAM
# ============================================================================

class BinaryStream:
    def __init__(self, buffer):
        self._stream = io.BytesIO(buffer)
    
    def __getitem__(self, key):
        return self._stream.getbuffer()[key]
    
    def tell(self):
        return self._stream.tell()
    
    def seek(self, offset, whence=0):
        return self._stream.seek(offset, whence)
    
    def read(self, size=None):
        return self._stream.read(size)
    
    def read_string(self):
        length = self.read_u32()
        return self._stream.read(length).decode("utf-8")
    
    def read_7bit_string(self):
        length = self.read_7bit()
        return self._stream.read(length).decode("utf-8")
    
    def read_s16(self):
        v = self._stream.read(2)
        return struct.unpack('h', v)[0] if v else None
    
    def read_u8(self):
        v = self._stream.read(1)
        return struct.unpack('B', v)[0] if v else None
    
    def read_u16(self):
        v = self._stream.read(2)
        return struct.unpack('H', v)[0] if v else None
    
    def read_s32(self):
        v = self._stream.read(4)
        return struct.unpack('i', v)[0] if v else None
    
    def read_u32(self):
        v = self._stream.read(4)
        return struct.unpack('I', v)[0] if v else None
    
    def read_f16(self):
        v = self._stream.read(2)
        return struct.unpack('e', v)[0] if v else None
    
    def read_f32(self):
        v = self._stream.read(4)
        return struct.unpack('f', v)[0] if v else None
    
    def read_sn16(self):
        return self.read_s16() / 32767
    
    def read_un8(self):
        return self.read_u8() / 255
    
    def read_un16(self):
        return self.read_u16() / 65535
    
    def read_7bit(self):
        value = 0
        shift = 0
        while True:
            value_byte = self.read_u8()
            value |= (value_byte & 0x7F) << shift
            shift += 7
            if value_byte & 0x80 == 0:
                break
        return value

# ============================================================================
# PATH RESOLVER
# ============================================================================

class SmartPathResolver:
    """Resolves Game: paths relative to the selected car folder"""
    def __init__(self, base_folder):
        self.base_folder = base_folder
        self.cache = {}
    
    def resolve(self, game_path):
        """Resolve Game:\... path to actual file"""
        if not game_path:
            return None
        
        # Check cache first
        if game_path in self.cache:
            return self.cache[game_path]
        
        # Remove "Game:" prefix
        if game_path[:5].lower() == "game:":
            relative_path = game_path[5:].replace('\\', os.sep).replace('/', os.sep)
        else:
            relative_path = game_path.replace('\\', os.sep).replace('/', os.sep)
        
        # Try multiple search strategies
        candidates = [
            # 1. Direct path from base folder
            os.path.join(self.base_folder, relative_path.lstrip(os.sep)),
            
            # 2. Search from parent directories (go up to find Media folder)
            self._search_upwards(self.base_folder, relative_path),
            
            # 3. Search within the car folder itself
            self._search_in_folder(self.base_folder, os.path.basename(relative_path)),
        ]
        
        # Return first existing file
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                self.cache[game_path] = candidate
                return candidate
        
        print(f"Warning: Could not resolve path: {game_path}")
        return None
    
    def _search_upwards(self, start_folder, relative_path):
        """Search upwards to find Media folder"""
        current = start_folder
        for _ in range(5):  # Search up to 5 levels
            test_path = os.path.join(current, relative_path.lstrip(os.sep))
            if os.path.exists(test_path):
                return test_path
            
            parent = os.path.dirname(current)
            if parent == current:  # Reached root
                break
            current = parent
        return None
    
    def _search_in_folder(self, folder, filename):
        """Search for filename recursively in folder"""
        for root, dirs, files in os.walk(folder):
            if filename in files:
                return os.path.join(root, filename)
        return None

# ============================================================================
# BUNDLE FORMAT
# ============================================================================

class Tag:
    Grub = 0x47727562
    Id = 0x49642020
    Name = 0x4E616D65
    TXCH = 0x54584348
    Modl = 0x4D6F646C
    Skel = 0x536B656C
    MatI = 0x4D617449
    Mesh = 0x4D657368
    VLay = 0x564C6179
    IndB = 0x496E6442
    VerB = 0x56657242
    MATI = 0x4D415449
    MATL = 0x4D41544C
    MTPR = 0x4D545052
    DFPR = 0x44465052
    TXCB = 0x54584342

class Version:
    def __init__(self):
        self.major = 0
        self.minor = 0
    
    def deserialize(self, stream):
        self.major = stream.read_u8()
        self.minor = stream.read_u8()
    
    def is_at_least(self, major, minor):
        return self.major > major or (self.major == major and self.minor >= minor)

class Metadata:
    def __init__(self):
        self.tag = 0
    
    def deserialize(self, stream):
        self.tag = stream.read_u32()
        version_and_size = stream.read_u16()
        size = version_and_size >> 4
        offset = stream.read_u16()
        self.stream = BinaryStream(stream[offset : offset + size])
    
    def read_string(self):
        return self.stream.read().decode('utf-8')
    
    def read_s32(self):
        return self.stream.read_s32()

class Blob:
    def __init__(self):
        self.tag = 0
        self.version = Version()
        self.metadata = {}
    
    def deserialize(self, stream):
        self.tag = stream.read_u32()
        self.version.deserialize(stream)
        self.metadata_length = stream.read_u16()
        self.metadata_offset = stream.read_u32()
        self.data_offset = stream.read_u32()
        self.data_size = stream.read_u32()
        stream.seek(4, os.SEEK_CUR)
        
        for i in range(self.metadata_length):
            metadata = Metadata()
            metadata.deserialize(BinaryStream(stream[self.metadata_offset + i * 8:]))
            self.metadata[metadata.tag] = metadata
        
        self.stream = BinaryStream(stream[self.data_offset : self.data_offset + self.data_size])

class Bundle:
    def __init__(self):
        self.blobs = defaultdict(list)
    
    def deserialize(self, stream):
        self.tag = stream.read_u32()
        self.version = Version()
        self.version.deserialize(stream)
        
        blobs_length = stream.read_u16()
        stream.seek(8, os.SEEK_CUR)
        
        if self.version.is_at_least(1, 1):
            blobs_length = stream.read_u32()
        
        for _ in range(blobs_length):
            blob = Blob()
            blob.deserialize(stream)
            self.blobs[blob.tag].append(blob)

# ============================================================================
# MODEL DATA
# ============================================================================

class Model:
    def deserialize(self, blob):
        stream = blob.stream
        self.meshes_length = stream.read_s16()
        self.buffers_length = stream.read_s16()
        self.vertex_layouts_length = stream.read_s16()
        self.materials_length = stream.read_s16()
        stream.seek(4, os.SEEK_CUR)
        self.levels_of_detail = stream.read_u16()
        if blob.version.is_at_least(1, 2):
            self.decompress_flags = stream.read_u8()

class VertexLayout:
    def __init__(self):
        self.elements = {}
    
    def deserialize(self, stream):
        element_names_length = stream.read_u16()
        element_names = [stream.read_string() for _ in range(element_names_length)]
        
        elements_length = stream.read_u16()
        for _ in range(elements_length):
            semantic_name = element_names[stream.read_u16()]
            semantic_index = stream.read_u16()
            key = semantic_name + str(semantic_index)
            self.elements[key] = {
                'input_slot': stream.read_u16(),
                'format': (stream.seek(2, os.SEEK_CUR), stream.read_u32())[1]
            }
            stream.seek(8, os.SEEK_CUR)

class ModelBuffer:
    def deserialize(self, blob):
        self.length = blob.stream.read_u32()
        self.size = blob.stream.read_u32()
        self.stride = blob.stream.read_u16()
        blob.stream.seek(2, os.SEEK_CUR)
        
        if blob.version.is_at_least(1, 0):
            self.format = blob.stream.read_u32()
            self.stream = blob.stream[0x10 : 0x10 + self.size]
        else:
            self.stream = blob.stream[0xC : 0xC + self.size]

class Mesh:
    def deserialize(self, blob):
        self.name = blob.metadata[Tag.Name].read_string() if Tag.Name in blob.metadata else "Unnamed"
        
        self.material_id = blob.stream.read_s16()
        if blob.version.is_at_least(1, 9):
            self.material_id = blob.stream.read_s16()
            blob.stream.seek(4, os.SEEK_CUR)
        
        self.bone_index = blob.stream.read_s16()
        self.levels_of_detail = blob.stream.read_u16()
        blob.stream.seek(2, os.SEEK_CUR)
        self.render_pass = blob.stream.read_u16()
        blob.stream.seek(1, os.SEEK_CUR)
        
        if blob.version.is_at_least(1, 2):
            blob.stream.seek(2, os.SEEK_CUR)
        if blob.version.is_at_least(1, 3):
            blob.stream.seek(1, os.SEEK_CUR)
        
        blob.stream.seek(3, os.SEEK_CUR)
        self.index_buffer_id = blob.stream.read_s32()
        blob.stream.seek(4, os.SEEK_CUR)
        self.start_index_location = blob.stream.read_s32()
        self.base_vertex_location = blob.stream.read_s32()
        self.index_count = blob.stream.read_u32()
        blob.stream.seek(4, os.SEEK_CUR)
        
        if blob.version.is_at_least(1, 6):
            blob.stream.seek(8, os.SEEK_CUR)
        
        self.vertex_layout_id = blob.stream.read_u32()
        vb_count = blob.stream.read_u32()
        self.vertex_buffer_indices = [None] * vb_count
        
        for _ in range(vb_count):
            vb_id = blob.stream.read_s32()
            input_slot = blob.stream.read_s32()
            stride = blob.stream.read_s32()
            offset = blob.stream.read_s32()
            self.vertex_buffer_indices[input_slot] = {'id': vb_id, 'stride': stride, 'offset': offset}
        
        blob.stream.seek(4 if blob.version.is_at_least(1, 4) else 0, os.SEEK_CUR)
        blob.stream.seek(4 if blob.version.is_at_least(1, 4) else 0, os.SEEK_CUR)
        blob.stream.read_u32()
        
        if blob.version.is_at_least(1, 1):
            blob.stream.seek(4, os.SEEK_CUR)
        
        self.uv_transforms = [None] * 5
        if blob.version.is_at_least(1, 5):
            for i in range(5):
                self.uv_transforms[i] = (
                    (blob.stream.read_f32(), blob.stream.read_f32()),
                    (blob.stream.read_f32(), blob.stream.read_f32())
                )
        
        self.scale = [1, 1, 1, 1]
        self.translate = [0, 0, 0, 0]
        if blob.version.is_at_least(1, 8):
            self.scale = [blob.stream.read_f32() for _ in range(4)]
            self.translate = [blob.stream.read_f32() for _ in range(4)]

class Skeleton:
    def __init__(self):
        self.bones = []
    
    def deserialize(self, blob):
        bones_length = blob.stream.read_u16()
        self.bones = []
        
        for _ in range(bones_length):
            bone = {'transform': [[1 if i == j else 0 for i in range(4)] for j in range(4)]}
            name_length = blob.stream.read_u32()
            bone['name'] = blob.stream.read(name_length).decode("utf-8")
            parent_index = blob.stream.read_s16()
            blob.stream.seek(4, os.SEEK_CUR)
            
            for j in range(4):
                for i in range(4):
                    bone['transform'][j][i] = blob.stream.read_f32()
            
            if parent_index != -1 and parent_index < len(self.bones):
                tr = self.bones[parent_index]['transform']
                transform = [[0] * 4 for _ in range(4)]
                for i in range(4):
                    for j in range(4):
                        for k in range(4):
                            transform[i][j] += bone['transform'][i][k] * tr[k][j]
                bone['transform'] = transform
            
            self.bones.append(bone)

# ============================================================================
# MATERIALS
# ============================================================================

class Texture:
    def __init__(self, path, resolver):
        self.path = path
        self.resolver = resolver
        self.buffer = None
        self.guid = ""
        self.width = 0
        self.height = 0
    
    def load(self):
        """Load texture from swatchbin file"""
        try:
            filepath = self.resolver.resolve(self.path)
            if not filepath or not os.path.exists(filepath):
                print(f"Texture not found: {self.path}")
                return False
            
            with open(filepath, "rb") as f:
                stream = BinaryStream(f.read())
            
            bundle = Bundle()
            bundle.deserialize(stream)
            
            if not bundle.blobs[Tag.TXCB]:
                return False
            
            blob = bundle.blobs[Tag.TXCB][0]
            header_stream = blob.metadata[Tag.TXCH].stream
            header_stream.seek(8, os.SEEK_CUR)
            self.guid = "{" + str(UUID(bytes_le=header_stream.read(16))).upper() + "}"
            
            width = header_stream.read(4)
            height = header_stream.read(4)
            header_stream.seek(6, os.SEEK_CUR)
            mip_levels = header_stream.read(1)
            header_stream.seek(1, os.SEEK_CUR)
            transcoding = header_stream.read_u32()
            header_stream.seek(4, os.SEEK_CUR)
            color_profile = header_stream.read_u32()
            header_stream.seek(12, os.SEEK_CUR)
            encoding = header_stream.read_u32()
            header_stream.seek(8, os.SEEK_CUR)
            linear_size = header_stream.read(4)
            
            # Determine DDS format
            format_encoded = encoding if transcoding <= 1 else transcoding - 2
            format_map = {
                0: 72 if color_profile else 71,
                1: 75 if color_profile else 74,
                2: 78 if color_profile else 77,
                3: 80, 4: 81, 5: 83, 6: 84,
                7: 95, 8: 96,
                9: 99 if color_profile else 98,
                13: 29 if color_profile else 28,
            }
            dxgi_format = format_map.get(format_encoded, 0)
            
            # Create DDS buffer
            self.buffer = b''.join([
                b'\x44\x44\x53\x20\x7C\x00\x00\x00\x07\x10\x0A\x00', height,
                width, linear_size, b'\x01\x00\x00\x00', mip_levels, b'\x00\x00\x00'
                b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
                b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
                b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x20\x00\x00\x00',
                b'\x04\x00\x00\x00\x44\x58\x31\x30\x00\x00\x00\x00\x00\x00\x00\x00',
                b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\x10\x40\x00',
                b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
                struct.pack("I", dxgi_format), b'\x03\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00',
                b'\x03\x00\x00\x00', blob.stream.read()
            ])
            
            return True
            
        except Exception as e:
            print(f"Failed to load texture {self.path}: {e}")
            return False

class ShaderParameter:
    def __init__(self):
        self.hash = 0
        self.type = 0
        self.value = None
        self.path = None
    
    def deserialize(self, stream):
        version = Version()
        version.deserialize(stream)
        
        self.hash = stream.read_u32()
        if version.is_at_least(3, 1) and stream.read_u8() != 0:
            stream.seek(4, os.SEEK_CUR)
        
        self.type = stream.read_u8()
        if version.is_at_least(3, 0):
            self.guid = stream.read(16)
        
        # Parse value based on type
        if self.type == 0 or self.type == 5 or self.type == 9:  # Vector
            stream.seek(16, os.SEEK_CUR)
        elif self.type == 1:  # Color
            self.value = (stream.read_f32(), stream.read_f32(), stream.read_f32(), stream.read_f32())
        elif self.type == 2:  # Float
            self.value = stream.read_f32()
        elif self.type == 4:  # Int
            stream.seek(4, os.SEEK_CUR)
        elif self.type == 3:  # Bool
            self.value = stream.read_u32() != 0
        elif self.type == 6:  # Texture2D
            self.path = stream.read_7bit_string()
            stream.seek(4, os.SEEK_CUR)
        elif self.type == 7:  # Sampler
            stream.seek(8, os.SEEK_CUR)
            if version.is_at_least(1, 1):
                stream.seek(4, os.SEEK_CUR)
        elif self.type == 8:  # ColorGradient
            length = stream.read_u32()
            stream.seek(4 * length, os.SEEK_CUR)
        elif self.type == 11:  # Vector2
            self.value = (stream.read_f32(), stream.read_f32())
            if not version.is_at_least(2, 0):
                stream.seek(8, os.SEEK_CUR)

class MaterialInstance:
    def __init__(self, resolver):
        self.name = ""
        self.resolver = resolver
        self.diffuse_color = (0.8, 0.8, 0.8, 1.0)
        self.diffuse_texture = None
        self.normal_texture = None
        self.parameters = {}
    
    def deserialize(self, blob):
        self.name = blob.metadata[Tag.Name].read_string() if Tag.Name in blob.metadata else "Material"
        
        try:
            # Read parent material if exists
            bundle = Bundle()
            bundle.deserialize(blob.stream)
            
            # Load parent material
            parent_blobs = bundle.blobs[Tag.MATI]
            if not parent_blobs:
                parent_blobs = bundle.blobs[Tag.MATL]
            
            if parent_blobs:
                parent_path = parent_blobs[0].stream.read_7bit_string()
                self._load_parent_material(parent_path)
            
            # Load shader parameters
            param_blobs = bundle.blobs[Tag.MTPR]
            if not param_blobs:
                param_blobs = bundle.blobs[Tag.DFPR]
            
            if param_blobs:
                self._load_parameters(param_blobs[0])
            
            # Extract common material properties
            self._extract_material_properties()
            
        except Exception as e:
            print(f"Failed to load material {self.name}: {e}")
    
    def _load_parent_material(self, parent_path):
        """Load parent material file"""
        try:
            filepath = self.resolver.resolve(parent_path)
            if not filepath or not os.path.exists(filepath):
                return
            
            with open(filepath, "rb") as f:
                stream = BinaryStream(f.read())
            
            bundle = Bundle()
            bundle.deserialize(stream)
            
            # Recursively load parent
            parent_blobs = bundle.blobs[Tag.MATI]
            if not parent_blobs:
                parent_blobs = bundle.blobs[Tag.MATL]
            
            if parent_blobs:
                parent_parent_path = parent_blobs[0].stream.read_7bit_string()
                self._load_parent_material(parent_parent_path)
            
            # Load parent parameters
            param_blobs = bundle.blobs[Tag.MTPR]
            if not param_blobs:
                param_blobs = bundle.blobs[Tag.DFPR]
            
            if param_blobs:
                self._load_parameters(param_blobs[0])
                
        except Exception as e:
            print(f"Failed to load parent material: {e}")
    
    def _load_parameters(self, blob):
        """Load shader parameters"""
        try:
            if blob.version.is_at_least(2, 1):
                param_count = blob.stream.read_u16()
            else:
                param_count = blob.stream.read_u8()
            
            for _ in range(param_count):
                param = ShaderParameter()
                param.deserialize(blob.stream)
                self.parameters[param.hash] = param
                
        except Exception as e:
            print(f"Failed to load parameters: {e}")
    
    def _extract_material_properties(self):
        """Extract common properties from parameters"""
        # Common parameter hashes
        DIFFUSE_TEXTURE = 0x6DD98CD9  # DiffuseATexture
        DIFFUSE_COLOR = 0xEF5CCE09    # DiffuseColorAColorParam
        NORMAL_TEXTURE = 0x8C658791   # NormalTexture
        
        # Try to find diffuse texture
        if DIFFUSE_TEXTURE in self.parameters:
            param = self.parameters[DIFFUSE_TEXTURE]
            if param.path:
                self.diffuse_texture = Texture(param.path, self.resolver)
        
        # Try to find diffuse color
        if DIFFUSE_COLOR in self.parameters:
            param = self.parameters[DIFFUSE_COLOR]
            if param.value:
                self.diffuse_color = param.value
        
        # Try to find normal texture
        if NORMAL_TEXTURE in self.parameters:
            param = self.parameters[NORMAL_TEXTURE]
            if param.path:
                self.normal_texture = Texture(param.path, self.resolver)

# ============================================================================
# IMPORTER
# ============================================================================

class ForzaCarFolderImporter:
    def __init__(self, context, folder_path, options):
        self.context = context
        self.folder_path = folder_path
        self.options = options
        self.resolver = SmartPathResolver(folder_path)
        self.modelbin_files = []
        self.texture_cache = {}
    
    def find_modelbin_files(self):
        """Find all .modelbin files in folder"""
        print(f"Searching for .modelbin files in: {self.folder_path}")
        
        for root, dirs, files in os.walk(self.folder_path):
            for file in files:
                if file.lower().endswith('.modelbin'):
                    filepath = os.path.join(root, file)
                    self.modelbin_files.append(filepath)
        
        print(f"Found {len(self.modelbin_files)} modelbin files")
        return len(self.modelbin_files) > 0
    
    def import_all(self):
        """Import all found modelbin files"""
        if not self.find_modelbin_files():
            return {'CANCELLED'}
        
        imported_count = 0
        for filepath in self.modelbin_files:
            print(f"\nImporting: {os.path.relpath(filepath, self.folder_path)}")
            
            if self.import_modelbin(filepath):
                imported_count += 1
        
        print(f"\nImport complete: {imported_count}/{len(self.modelbin_files)} files")
        return {'FINISHED'} if imported_count > 0 else {'CANCELLED'}
    
    def import_modelbin(self, filepath):
        """Import single modelbin file"""
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            
            stream = BinaryStream(memoryview(data))
            bundle = Bundle()
            bundle.deserialize(stream)
            
            # Check bundle version (informational only)
            if bundle.version.major > 1 or (bundle.version.major == 1 and bundle.version.minor > 1):
                print(f"Info: Detected newer format version {bundle.version.major}.{bundle.version.minor} (likely FH5)")
            
            if not bundle.blobs[Tag.Modl]:
                return False
            
            # Parse model data
            model = Model()
            model.deserialize(bundle.blobs[Tag.Modl][0])
            
            skeleton = Skeleton()
            if bundle.blobs[Tag.Skel]:
                skeleton.deserialize(bundle.blobs[Tag.Skel][0])
            
            vertex_layouts = []
            for vl_blob in bundle.blobs[Tag.VLay]:
                vl = VertexLayout()
                vl.deserialize(vl_blob.stream)
                vertex_layouts.append(vl)
            
            index_buffer = ModelBuffer()
            if bundle.blobs[Tag.IndB]:
                index_buffer.deserialize(bundle.blobs[Tag.IndB][0])
            
            vertex_buffers = [ModelBuffer() for _ in range(len(bundle.blobs[Tag.VerB]) + 1)]
            for vb_blob in bundle.blobs[Tag.VerB]:
                vb_id = vb_blob.metadata[Tag.Id].read_s32() if Tag.Id in vb_blob.metadata else -1
                vertex_buffers[vb_id + 1].deserialize(vb_blob)
            
            meshes = []
            for mesh_blob in bundle.blobs[Tag.Mesh]:
                mesh = Mesh()
                mesh.deserialize(mesh_blob)
                meshes.append(mesh)
            
            # Parse materials
            materials = [MaterialInstance(self.resolver) for _ in range(model.materials_length)]
            if self.options['import_materials']:
                for mat_blob in bundle.blobs[Tag.MatI]:
                    mat_id = mat_blob.metadata[Tag.Id].read_s32() if Tag.Id in mat_blob.metadata else 0
                    if mat_id < len(materials):
                        materials[mat_id].deserialize(mat_blob)
            
            # Create Blender objects
            self.create_blender_objects(meshes, vertex_layouts, vertex_buffers, index_buffer, skeleton, materials)
            
            return True
            
        except Exception as e:
            print(f"Import failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def create_blender_objects(self, meshes, vertex_layouts, vertex_buffers, index_buffer, skeleton, materials):
        """Create Blender mesh objects"""
        requested_lod = self.options['lod_filter']
        
        for mesh in meshes:
            if mesh.levels_of_detail & requested_lod == 0:
                continue
            if mesh.render_pass & 0x10 == 0:
                continue
            
            # Read indices
            vertex_id_min = 0xFFFFFFFF
            vertex_id_max = 0
            
            stream = BinaryStream(index_buffer.stream[
                mesh.start_index_location * index_buffer.stride:
                (mesh.start_index_location + mesh.index_count) * index_buffer.stride
            ])
            
            draw_indices = []
            for i in range(mesh.index_count):
                vertex_id = stream.read_u32() if index_buffer.stride == 4 else stream.read_u16()
                vertex_id_max = max(vertex_id_max, vertex_id)
                vertex_id_min = min(vertex_id_min, vertex_id)
                draw_indices.append(vertex_id)
            
            # Create faces
            faces = []
            for i in range(mesh.index_count // 3):
                j = i * 3
                faces.append((draw_indices[j] - vertex_id_min, draw_indices[j + 2] - vertex_id_min, draw_indices[j + 1] - vertex_id_min))
            
            # Prepare vertex data
            vertex_count = vertex_id_max - vertex_id_min + 1
            verts = [(0, 0, 0)] * vertex_count
            norms = [(0, 0, 0)] * vertex_count
            uvs = [[(0, 0)] * vertex_count for _ in range(5)]
            colors = [(1, 1, 1, 1)] * vertex_count
            
            # Setup vertex elements
            vertex_layout = vertex_layouts[mesh.vertex_layout_id]
            elements = self.setup_vertex_elements(mesh, vertex_layout, vertex_buffers, vertex_id_min, vertex_id_max)
            
            # Read vertices
            for vertex_id in range(vertex_id_min, vertex_id_max + 1):
                local_id = vertex_id - vertex_id_min
                
                # Position
                pos_elem = elements.get("POSITION0")
                if pos_elem:
                    if pos_elem['format'] == 13:
                        v = [
                            pos_elem['stream'].read_sn16() * mesh.scale[0] + mesh.translate[0],
                            pos_elem['stream'].read_sn16() * mesh.scale[1] + mesh.translate[1],
                            pos_elem['stream'].read_sn16() * mesh.scale[2] + mesh.translate[2]
                        ]
                        v_w = pos_elem['stream'].read_sn16()
                    else:
                        v = [pos_elem['stream'].read_f32(), pos_elem['stream'].read_f32(), pos_elem['stream'].read_f32()]
                        v_w = 1.0
                    pos_elem['stream'].seek(pos_elem['advance'], os.SEEK_CUR)
                else:
                    v = [0, 0, 0]
                    v_w = 1.0
                
                # Normal
                norm_elem = elements.get("NORMAL0")
                if norm_elem:
                    if norm_elem['format'] == 37:
                        n = [v_w, norm_elem['stream'].read_sn16(), norm_elem['stream'].read_sn16()]
                    else:
                        n = [norm_elem['stream'].read_f16(), norm_elem['stream'].read_f16(), norm_elem['stream'].read_f16()]
                    norm_elem['stream'].seek(norm_elem['advance'], os.SEEK_CUR)
                else:
                    n = [0, 0, 1]
                
                # UVs
                for i in range(5):
                    uv_elem = elements.get(f"TEXCOORD{i}")
                    if uv_elem:
                        u = uv_elem['stream'].read_un16()
                        v_uv = uv_elem['stream'].read_un16()
                        
                        if mesh.uv_transforms[i]:
                            u = u * mesh.uv_transforms[i][0][1] + mesh.uv_transforms[i][0][0]
                            v_uv = v_uv * mesh.uv_transforms[i][1][1] + mesh.uv_transforms[i][1][0]
                        
                        uvs[i][local_id] = (u, 1 - v_uv)
                        uv_elem['stream'].seek(uv_elem['advance'], os.SEEK_CUR)
                
                # Colors
                color_elem = elements.get("COLOR0")
                if color_elem:
                    colors[local_id] = (color_elem['stream'].read_un8(), color_elem['stream'].read_un8(), 
                                       color_elem['stream'].read_un8(), color_elem['stream'].read_un8())
                    color_elem['stream'].seek(color_elem['advance'], os.SEEK_CUR)
                
                # Apply bone transform
                if skeleton.bones:
                    bone_transform = skeleton.bones[mesh.bone_index]['transform']
                    v2 = [0, 0, 0]
                    n2 = [0, 0, 0]
                    for j in range(3):
                        for k in range(4):
                            if k == 3:
                                v2[j] += bone_transform[k][j]
                            else:
                                v2[j] += v[k] * bone_transform[k][j]
                                n2[j] += n[k] * bone_transform[k][j]
                    v, n = v2, n2
                
                # Normalize normal
                n_len = math.sqrt(n[0]**2 + n[1]**2 + n[2]**2)
                if n_len > 0:
                    n = [n[0]/n_len, n[1]/n_len, n[2]/n_len]
                
                # Convert coordinate system
                verts[local_id] = (-v[0], -v[2], v[1])
                norms[local_id] = (-n[0], -n[2], n[1])
            
            # Create Blender mesh
            mesh_name = f"{mesh.name} {materials[mesh.material_id].name}"
            mesh_data = bpy.data.meshes.new(name=mesh_name)
            mesh_data.from_pydata(verts, [], faces)
            mesh_data.validate()
            
            if norm_elem and norm_elem['format'] in [10, 37]:
                mesh_data.normals_split_custom_set_from_vertices(norms)
            
            # Create object
            obj = bpy.data.objects.new(mesh_name, mesh_data)
            self.context.collection.objects.link(obj)
            
            # Add UV maps and vertex colors
            bm = bmesh.new()
            bm.from_mesh(mesh_data)
            
            uv_layers = [bm.loops.layers.uv.new(f"TEXCOORD{i}") for i in range(5)]
            for face in bm.faces:
                for loop in face.loops:
                    for uv_layer, uv in zip(uv_layers, uvs):
                        loop[uv_layer].uv = uv[loop.vert.index]
            
            color_layer = bm.verts.layers.color.new("COLOR0")
            for vert in bm.verts:
                vert[color_layer] = colors[vert.index]
            
            bm.to_mesh(mesh_data)
            bm.free()
            
            # Create material if enabled
            if self.options['import_materials']:
                self.create_blender_material(obj, materials[mesh.material_id])
    
    def create_blender_material(self, obj, mat_instance):
        """Create Blender material with textures"""
        try:
            # Create or reuse material
            mat_name = mat_instance.name
            material = bpy.data.materials.get(mat_name)
            
            if not material:
                material = bpy.data.materials.new(mat_name)
                material.use_nodes = True
                nodes = material.node_tree.nodes
                links = material.node_tree.links
                
                # Clear default nodes
                nodes.clear()
                
                # Create shader nodes
                output = nodes.new('ShaderNodeOutputMaterial')
                output.location = (400, 0)
                
                principled = nodes.new('ShaderNodeBsdfPrincipled')
                principled.location = (0, 0)
                
                links.new(principled.outputs['BSDF'], output.inputs['Surface'])
                
                # Set diffuse color
                principled.inputs['Base Color'].default_value = mat_instance.diffuse_color
                
                # Add diffuse texture if exists
                if mat_instance.diffuse_texture:
                    if mat_instance.diffuse_texture.load():
                        img = self.get_or_create_image(mat_instance.diffuse_texture)
                        if img:
                            tex_node = nodes.new('ShaderNodeTexImage')
                            tex_node.image = img
                            tex_node.location = (-400, 200)
                            links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
                
                # Add normal map if exists
                if mat_instance.normal_texture:
                    if mat_instance.normal_texture.load():
                        img = self.get_or_create_image(mat_instance.normal_texture)
                        if img:
                            img.colorspace_settings.name = 'Non-Color'
                            
                            tex_node = nodes.new('ShaderNodeTexImage')
                            tex_node.image = img
                            tex_node.location = (-400, -200)
                            
                            normal_map = nodes.new('ShaderNodeNormalMap')
                            normal_map.location = (-100, -200)
                            
                            links.new(tex_node.outputs['Color'], normal_map.inputs['Color'])
                            links.new(normal_map.outputs['Normal'], principled.inputs['Normal'])
            
            # Assign material to object
            if obj.data.materials:
                obj.data.materials[0] = material
            else:
                obj.data.materials.append(material)
                
        except Exception as e:
            print(f"Failed to create material: {e}")
    
    def get_or_create_image(self, texture):
        """Get or create Blender image from texture"""
        if texture.guid in self.texture_cache:
            return self.texture_cache[texture.guid]
        
        try:
            img = bpy.data.images.get(texture.guid)
            if not img:
                img = bpy.data.images.new(texture.guid, 1, 1)
                img.pack(data=texture.buffer, data_len=len(texture.buffer))
                img.source = 'FILE'
            
            self.texture_cache[texture.guid] = img
            return img
            
        except Exception as e:
            print(f"Failed to create image: {e}")
            return None
    
    def setup_vertex_elements(self, mesh, vertex_layout, vertex_buffers, vertex_id_min, vertex_id_max):
        """Setup vertex element streams"""
        elements = {}
        vertex_buffer_offsets = [0] * len(mesh.vertex_buffer_indices)
        
        for semantic_name, elem_desc in vertex_layout.elements.items():
            vb_index = mesh.vertex_buffer_indices[elem_desc['input_slot']]
            vb = vertex_buffers[vb_index['id'] + 1]
            
            start = vb_index['offset'] + (vertex_id_min + mesh.base_vertex_location) * vb.stride
            start += vertex_buffer_offsets[elem_desc['input_slot']]
            end = vb_index['offset'] + (vertex_id_max + mesh.base_vertex_location + 1) * vb.stride
            end += vertex_buffer_offsets[elem_desc['input_slot']]
            
            format_sizes = {6: 12, 10: 8, 13: 8, 24: 4, 28: 4, 35: 4, 37: 4}
            size = format_sizes.get(elem_desc['format'], 0)
            
            elements[semantic_name] = {
                'stream': BinaryStream(vb.stream[start:end]),
                'format': elem_desc['format'],
                'advance': vb.stride - size
            }
            
            vertex_buffer_offsets[elem_desc['input_slot']] += size
        
        return elements

# ============================================================================
# OPERATOR
# ============================================================================

# ============================================================================
# PROPERTIES
# ============================================================================

class ForzaImportSettings(PropertyGroup):
    """Settings for Forza car folder import"""
    
    directory: StringProperty(
        name="Car Folder",
        description="Select the car folder containing .modelbin files",
        subtype='DIR_PATH',
        default=""
    )
    
    # LOD selection
    import_lod0: BoolProperty(name="LOD0", description="Import LOD0 (highest detail)", default=True)
    import_lod1: BoolProperty(name="LOD1", description="Import LOD1", default=False)
    import_lod2: BoolProperty(name="LOD2", description="Import LOD2", default=False)
    import_lod3: BoolProperty(name="LOD3", description="Import LOD3", default=False)
    import_lod4: BoolProperty(name="LOD4", description="Import LOD4", default=False)
    import_lod5: BoolProperty(name="LOD5", description="Import LOD5", default=False)
    import_lod6: BoolProperty(name="LOD6", description="Import LOD6", default=False)
    import_lod7: BoolProperty(name="LOD7", description="Import LOD7 (lowest detail)", default=False)
    
    # Material options
    import_materials: BoolProperty(
        name="Import Materials & Textures",
        description="Import materials and textures (slower but complete)",
        default=True
    )

# ============================================================================
# PANEL
# ============================================================================

class VIEW3D_PT_forza_importer(bpy.types.Panel):
    """Forza Car Importer Panel"""
    bl_label = "Forza Car Importer"
    bl_idname = "VIEW3D_PT_forza_importer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Forza'
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.forza_import_settings
        
        # Instructions box
        box = layout.box()
        box.label(text="How to Use:", icon='INFO')
        col = box.column(align=True)
        col.scale_y = 0.8
        col.label(text="1. Browse to car folder")
        col.label(text="2. Select LOD levels to import")
        col.label(text="3. Click 'Import Car Folder'")
        col.separator()
        col.label(text="Compatibility:", icon='CHECKMARK')
        col.label(text="✓ FH4 and FH5: Confirmed")
        col.label(text="? Lower versions: May work")
        col.separator()
        col.scale_y = 0.7
        col.label(text="Original script: @Doliman100")
        
        layout.separator()
        
        # Important note box
        box = layout.box()
        box.alert = True
        col = box.column(align=True)
        col.scale_y = 0.85
        col.label(text="Note: No full game path needed!", icon='INFO')
        col.label(text="Just select the car folder only.")
        
        # Folder selection
        box = layout.box()
        box.label(text="Car Folder", icon='FILE_FOLDER')
        box.prop(settings, "directory", text="")
        
        # LOD Selection
        box = layout.box()
        box.label(text="Level of Detail", icon='OUTLINER_OB_MESH')
        
        row = box.row(align=True)
        row.prop(settings, "import_lod0", toggle=True)
        row.prop(settings, "import_lod1", toggle=True)
        row.prop(settings, "import_lod2", toggle=True)
        row.prop(settings, "import_lod3", toggle=True)
        
        row = box.row(align=True)
        row.prop(settings, "import_lod4", toggle=True)
        row.prop(settings, "import_lod5", toggle=True)
        row.prop(settings, "import_lod6", toggle=True)
        row.prop(settings, "import_lod7", toggle=True)
        
        # Materials
        box = layout.box()
        box.label(text="Materials", icon='MATERIAL')
        box.prop(settings, "import_materials")
        row = box.row()
        row.scale_y = 0.8
        row.label(text="(Slower but includes textures)", icon='INFO')
        
        # Import button
        layout.separator()
        layout.operator("import_scene.forza_car_folder", text="Import Car Folder", icon='IMPORT')

# ============================================================================
# OPERATOR
# ============================================================================

class IMPORT_OT_forza_car_folder(bpy.types.Operator):
    """Import entire Forza car folder"""
    bl_idname = "import_scene.forza_car_folder"
    bl_label = "Import Forza Car Folder"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        settings = context.scene.forza_import_settings
        
        # Validate folder path
        if not settings.directory or not os.path.exists(settings.directory):
            self.report({'ERROR'}, "Please select a valid car folder")
            return {'CANCELLED'}
        
        folder_path = settings.directory
        
        # Convert LOD checkboxes to bitmask
        lod_filter = 0
        if settings.import_lod0: lod_filter |= (1 << 0)
        if settings.import_lod1: lod_filter |= (1 << 1)
        if settings.import_lod2: lod_filter |= (1 << 2)
        if settings.import_lod3: lod_filter |= (1 << 3)
        if settings.import_lod4: lod_filter |= (1 << 4)
        if settings.import_lod5: lod_filter |= (1 << 5)
        if settings.import_lod6: lod_filter |= (1 << 6)
        if settings.import_lod7: lod_filter |= (1 << 7)
        
        if lod_filter == 0:
            self.report({'ERROR'}, "Please select at least one LOD to import")
            return {'CANCELLED'}
        
        options = {
            'lod_filter': lod_filter,
            'render_pass_filter': 0xFFFF,
            'import_materials': settings.import_materials
        }
        
        # Import
        print(f"\n{'='*60}")
        print(f"Importing Forza car folder: {folder_path}")
        print(f"Materials enabled: {settings.import_materials}")
        print(f"{'='*60}\n")
        
        importer = ForzaCarFolderImporter(context, folder_path, options)
        result = importer.import_all()
        
        if result == {'FINISHED'}:
            self.report({'INFO'}, f"Imported {len(importer.modelbin_files)} modelbin files")
        else:
            self.report({'ERROR'}, "Import failed")
        
        return result

def register():
    bpy.utils.register_class(ForzaImportSettings)
    bpy.utils.register_class(VIEW3D_PT_forza_importer)
    bpy.utils.register_class(IMPORT_OT_forza_car_folder)
    bpy.types.Scene.forza_import_settings = bpy.props.PointerProperty(type=ForzaImportSettings)

def unregister():
    bpy.utils.unregister_class(IMPORT_OT_forza_car_folder)
    bpy.utils.unregister_class(VIEW3D_PT_forza_importer)
    bpy.utils.unregister_class(ForzaImportSettings)
    del bpy.types.Scene.forza_import_settings

if __name__ == "__main__":
    register()
