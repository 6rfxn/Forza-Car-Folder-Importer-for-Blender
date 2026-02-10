"""
Forza Car Folder Importer for Blender
Based on the original Forza ModelBin importer script by Doliman100
https://github.com/Doliman100

This addon adapts the original script into a user-friendly Blender panel
with automatic folder scanning and material resolution.

Confirmed working: FH4 and FH5
Lower versions of FH4 may or may not work.
"""

bl_info = {
    "name": "Forza Car Folder Importer",
    "author": "Doliman100 (original script), Community (addon)",
    "version": (1, 5, 0),
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
# DEBUG / LOGGING
# ============================================================================

FORZA_DEBUG = True
FORZA_LOG_MESSAGES = []
FORZA_LOG_LIMIT = 400
FORZA_LAST_MESH_COUNT = 0
FORZA_LAST_MATERIAL_COUNT = 0


def forza_log(message):
    """Small helper so all debug can be toggled in one place."""
    global FORZA_LOG_MESSAGES
    if FORZA_DEBUG:
        text = f"[ForzaImporter] {message}"
        print(text)

        FORZA_LOG_MESSAGES.append(text)
        if len(FORZA_LOG_MESSAGES) > FORZA_LOG_LIMIT:
            FORZA_LOG_MESSAGES = FORZA_LOG_MESSAGES[-FORZA_LOG_LIMIT:]

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
    """Resolves Game: paths relative to the selected car folder and optional game root.
    Prioritizes local filename search since users typically move all files
    into the car folder already."""
    def __init__(self, base_folder, game_root=None):
        self.base_folder = base_folder
        self.game_root = game_root if game_root else None
        self.cache = {}
        self._file_index = {}  # filename -> full path (built once)
        self._build_file_index()
    
    def _build_file_index(self):
        """Pre-scan the car folder and index all files by filename for fast lookup."""
        forza_log(f"Building file index for base folder: {self.base_folder}")
        for root, dirs, files in os.walk(self.base_folder):
            for f in files:
                f_lower = f.lower()
                full_path = os.path.join(root, f)
                if f_lower not in self._file_index:
                    self._file_index[f_lower] = full_path
        if self.game_root and os.path.isdir(self.game_root):
            forza_log(f"Also indexing optional game root: {self.game_root}")
            for root, dirs, files in os.walk(self.game_root):
                for f in files:
                    f_lower = f.lower()
                    full_path = os.path.join(root, f)
                    if f_lower not in self._file_index:
                        self._file_index[f_lower] = full_path
        forza_log(f"Indexed {len(self._file_index)} files for path resolution")
    
    def resolve(self, game_path):
        """Resolve Game:\\... path to actual file"""
        if not game_path:
            return None
        
        if game_path in self.cache:
            forza_log(f"Cache hit for path '{game_path}' -> '{self.cache[game_path]}'")
            return self.cache[game_path]
        
        normalized = game_path.replace('\\', os.sep).replace('/', os.sep)
        filename = os.path.basename(normalized)

        forza_log(
            f"Resolving game path '{game_path}' "
            f"(filename '{filename}') from base '{self.base_folder}'"
        )
        
        result = self._file_index.get(filename.lower())
        if result:
            forza_log(f"  -> Found by filename index: '{result}'")
        
        if not result:
            if game_path[:5].lower() == 'game:':
                relative_path = game_path[5:].replace('\\', os.sep).replace('/', os.sep)
            else:
                relative_path = normalized
            
            forza_log(f"  -> Trying relative path '{relative_path}'")
            
            candidate = os.path.join(self.base_folder, relative_path.lstrip(os.sep))
            forza_log(f"  -> Checking direct candidate '{candidate}'")
            if os.path.exists(candidate):
                forza_log("  -> Direct candidate exists")
                result = candidate
            else:
                forza_log("  -> Direct candidate missing, searching upwards from car folder")
                result = self._search_upwards(self.base_folder, relative_path)
                if not result and self.game_root and os.path.isdir(self.game_root):
                    game_candidate = os.path.join(self.game_root, relative_path.lstrip(os.sep))
                    forza_log(f"  -> Checking game root candidate '{game_candidate}'")
                    if os.path.exists(game_candidate):
                        forza_log("  -> Game root candidate exists")
                        result = game_candidate
        
        if result:
            forza_log(f"  -> RESOLVED '{game_path}' -> '{result}'")
            self.cache[game_path] = result
            return result
        
        forza_log(
            f"WARNING: Could not resolve material path.\n"
            f"  game_path : '{game_path}'\n"
            f"  filename  : '{filename}'\n"
            f"  base      : '{self.base_folder}'\n"
            f"  HINT      : Ensure a file named '{filename}' exists somewhere "
            f"under the selected car folder (or its parents)."
        )
        return None
    
    def _search_upwards(self, start_folder, relative_path):
        """Search upwards to find Media folder"""
        current = start_folder
        for _ in range(5):
            test_path = os.path.join(current, relative_path.lstrip(os.sep))
            forza_log(f"    -> Trying parent search candidate '{test_path}'")
            if os.path.exists(test_path):
                forza_log("    -> Parent search hit")
                return test_path
            
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
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
        
        if self.type == 0 or self.type == 5 or self.type == 9:
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
        self.source_file = None  # Store the source file path
        self.resolver = resolver
        self.diffuse_color = (0.8, 0.8, 0.8, 1.0)
        self.diffuse_texture = None
        self.normal_texture = None
        self.parameters = {}
    
    def deserialize(self, blob):
        self.name = blob.metadata[Tag.Name].read_string() if Tag.Name in blob.metadata else "Material"
        
        try:
            bundle = Bundle()
            bundle.deserialize(blob.stream)
            
            parent_blobs = bundle.blobs[Tag.MATI]
            if not parent_blobs:
                parent_blobs = bundle.blobs[Tag.MATL]
            
            if parent_blobs:
                parent_path = parent_blobs[0].stream.read_7bit_string()
                if parent_path:
                    self.source_file = os.path.basename(parent_path.replace('\\', os.sep))
                self._load_parent_material(parent_path)
            
            param_blobs = bundle.blobs[Tag.MTPR]
            if not param_blobs:
                param_blobs = bundle.blobs[Tag.DFPR]
            
            if param_blobs:
                self._load_parameters(param_blobs[0])
            
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
            
            parent_blobs = bundle.blobs[Tag.MATI]
            if not parent_blobs:
                parent_blobs = bundle.blobs[Tag.MATL]
            
            if parent_blobs:
                parent_parent_path = parent_blobs[0].stream.read_7bit_string()
                self._load_parent_material(parent_parent_path)
            
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
        DIFFUSE_TEXTURE = 0x6DD98CD9
        DIFFUSE_COLOR = 0xEF5CCE09
        NORMAL_TEXTURE = 0x8C658791
        
        if DIFFUSE_TEXTURE in self.parameters:
            param = self.parameters[DIFFUSE_TEXTURE]
            if param.path:
                self.diffuse_texture = Texture(param.path, self.resolver)
        
        if DIFFUSE_COLOR in self.parameters:
            param = self.parameters[DIFFUSE_COLOR]
            if param.value:
                self.diffuse_color = param.value
        
        if NORMAL_TEXTURE in self.parameters:
            param = self.parameters[NORMAL_TEXTURE]
            if param.path:
                self.normal_texture = Texture(param.path, self.resolver)

# ============================================================================
# IMPORTER
# ============================================================================

class ForzaCarFolderImporter:
    # Texture type keywords mapped to Principled BSDF inputs or special handling
    TEXTURE_TYPE_MAP = {
        'diffuse':    'Base Color',
        'diff':       'Base Color',
        'albedo':     'Base Color',
        'basecolor':  'Base Color',
        'base_color': 'Base Color',
        'base':       'Base Color',  # Forza naming: _base suffix
        'color':      'Base Color',
        'col':        'Base Color',
        'normal':     'Normal',
        'nrm':        'Normal',
        'nrml':       'Normal',  # common abbreviation
        'nor':        'Normal',
        'norm':       'Normal',
        'bump':       'Normal',
        'ao':         'AO',
        'occlusion':  'AO',
        'ambient':    'AO',
        'icao':       'AO',  # Forza naming: _Icao suffix
        'lcao':       'AO',  # Forza naming: _lcao suffix
        'cao':        'AO',  # Ambient occlusion variant
        'roughness':  'Roughness',
        'rough':      'Roughness',
        'rgh':        'Roughness',
        'glos':       'Roughness',  # Forza naming: glossiness (inverse of roughness)
        'gloss':      'Roughness',  # Full form
        'glossiness': 'Roughness',
        'metallic':   'Metallic',
        'metal':      'Metallic',
        'met':        'Metallic',
        'metalness':  'Metallic',
        'emissive':   'Emission Color',
        'emission':   'Emission Color',
        'emit':       'Emission Color',
        'emis':       'Emission Color',  # Common abbreviation
        'emm':        'Emission Color',
        'glow':       'Emission Color',
        'specular':   'Specular IOR Level',
        'spec':       'Specular IOR Level',
        'reflectiontint': 'Specular IOR Level',  # Forza naming: reflection tint maps
        'reflection': 'Specular IOR Level',  # Reflection maps
        'mask':       'Mask',
        'opacity':    'Alpha',
        'opac':       'Alpha',  # Forza naming: _opac suffix
        'alpha':      'Alpha',
        'transparency': 'Alpha',
    }

    # Heuristic keyword hints to guess if a material/texture is a decal vs tiled surface.
    # This is BEST-EFFORT only and not 100% accurate.
    # Note: We check DECAL keywords first, but TILED keywords take precedence if both match.
    DECAL_HINT_KEYWORDS = {
        'decal', 'badge', 'emblem', 'logo', 'symbol', 'icon',
        'gauge', 'gauges', 'speedo', 'tach', 'tachometer', 'needle',
        'number', 'numbers', 'num_', 'plate', 'license', 'licence',
        'sticker', 'label', 'text', 'font', 'letter', 'digit',
        'hud', 'ui', 'screen', 'display',
        # Brand-specific (be careful - these might match surface materials too)
        'amg_badge', 'amg_emblem', 'mer_badge', 'mer_emblem', 'v8biturbo', 'v8_biturbo',
    }

    TILED_HINT_KEYWORDS = {
        # Carbon fiber variants
        'carbon', 'carbonfiber', 'cf_', 'cfibre', 'fibercarbon',
        # Pattern keywords
        'ptn', 'pattern', 'grid', 'checker', 'check', 'chequer',
        'stripe', 'stripes', 'striped', 'zigzag', 'zig_zag', 'wave', 'noise', 'grain',
        # Fabric/textile materials
        'cloth', 'fabric', 'leather', 'alcantara', 'suede', 'carpet',
        # Metal/surface materials
        'metal', 'brushed', 'machined', 'ridges', 'scratches', 'scratched',
        # Generic surface materials (common in Forza)
        'plastic', 'rubber', 'paint', 'painted', 'smooth', 'rough', 'textured',
        # Detail/texture modifiers
        'dtl', 'detail', 'tiling', 'tile', 'tiled',
        # Common Forza material suffixes/prefixes
        'exterior', 'interior', 'trim', 'surface', 'material',
    }

    TEXTURE_EXTENSIONS = {'.swatchbin', '.png', '.jpg', '.jpeg', '.tga', '.dds', '.bmp', '.tif', '.tiff', '.exr', '.hdr'}
    
    def __init__(self, context, folder_path, options):
        self.context = context
        self.folder_path = folder_path
        self.options = options
        self.resolver = SmartPathResolver(folder_path, options.get('game_root'))
        self.modelbin_files = []
        self.texture_cache = {}
        self._folder_scan_cache = {}
    
    def _find_texture_folder(self, material_name):
        """Search for a folder matching the material name within the car directory."""
        if material_name in self._folder_scan_cache:
            return self._folder_scan_cache[material_name]
        
        mat_lower = material_name.lower()
        result = None
        
        forza_log(f"Auto-texture: Searching for folder matching material name '{material_name}' (lowercase: '{mat_lower}')")
        forza_log(f"  Searching under car folder: {self.folder_path}")
        
        for root, dirs, files in os.walk(self.folder_path):
            for d in dirs:
                if d.lower() == mat_lower:
                    result = os.path.join(root, d)
                    forza_log(f"  -> Found matching folder: '{result}'")
                    break
            if result:
                break
        
        if not result:
            forza_log(f"  -> No folder found matching '{material_name}'")
        
        self._folder_scan_cache[material_name] = result
        return result
    
    def _classify_texture_file(self, filename):
        """Classify a texture file by checking its name against known keywords."""
        forza_log(f"    Classifying: '{filename}'")
        name_lower = os.path.splitext(filename)[0].lower()
        
        import re
        tokens = re.split(r'[_\-\.\s]+', name_lower)
        forza_log(f"      Tokens: {tokens}")
        
        for token in tokens:
            if token in self.TEXTURE_TYPE_MAP:
                forza_log(f"      Matched token '{token}' to type '{self.TEXTURE_TYPE_MAP[token]}'")
                return self.TEXTURE_TYPE_MAP[token]
        
        for keyword, tex_type in sorted(self.TEXTURE_TYPE_MAP.items(), key=lambda x: -len(x[0])):
            if keyword in name_lower:
                forza_log(f"      Matched keyword '{keyword}' in filename to type '{tex_type}'")
                return tex_type
        
        forza_log(f"      No classification found for '{filename}'")
        return None
    
    def _scan_folder_for_textures(self, folder_path):
        """Scan a folder and subfolders for texture files and classify them."""
        found = {}
        forza_log(f"Auto-texture: Scanning folder '{folder_path}' (including subfolders) for textures")
        
        total_files = 0
        classified_count = 0
        
        for root, dirs, files in os.walk(folder_path):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in self.TEXTURE_EXTENSIONS:
                    continue
                
                total_files += 1
                full_path = os.path.join(root, f)
                tex_type = self._classify_texture_file(f)
                
                if tex_type:
                    if tex_type not in found:
                        found[tex_type] = full_path
                        classified_count += 1
                        forza_log(f"  -> Classified '{f}' as '{tex_type}'")
                    else:
                        forza_log(f"  -> Skipped '{f}' (already have '{tex_type}' from '{os.path.basename(found[tex_type])}')")
                else:
                    forza_log(f"  -> Could not classify '{f}' (no recognized keywords found)")
        
        forza_log(f"Auto-texture: Scanned {total_files} texture file(s), classified {classified_count} unique type(s)")
        return found
    
    def _load_texture_from_file(self, filepath, suggested_name=None):
        """Load a texture file and return a Blender image.
        
        Args:
            filepath: Full path to the texture file
            suggested_name: Optional cleaner name to use for the image
        """
        ext = os.path.splitext(filepath)[1].lower()
        if ext == '.swatchbin':
            return self._load_swatchbin_as_image(filepath)
        else:
            return self._load_standard_image(filepath, suggested_name)
    
    def _load_swatchbin_as_image(self, filepath):
        """Load a .swatchbin file and return a Blender image."""
        try:
            with open(filepath, "rb") as f:
                stream = BinaryStream(f.read())
            
            bundle = Bundle()
            bundle.deserialize(stream)
            
            if not bundle.blobs[Tag.TXCB]:
                return None
            
            blob = bundle.blobs[Tag.TXCB][0]
            header_stream = blob.metadata[Tag.TXCH].stream
            header_stream.seek(8, os.SEEK_CUR)
            guid = "{" + str(UUID(bytes_le=header_stream.read(16))).upper() + "}"
            
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
            
            format_encoded = encoding if transcoding <= 1 else transcoding - 2
            format_map = {
                0: 72 if color_profile else 71, 1: 75 if color_profile else 74,
                2: 78 if color_profile else 77, 3: 80, 4: 81, 5: 83, 6: 84,
                7: 95, 8: 96, 9: 99 if color_profile else 98, 13: 29 if color_profile else 28,
            }
            dxgi_format = format_map.get(format_encoded, 0)
            
            buffer = b''.join([
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
            
            if guid in self.texture_cache:
                return self.texture_cache[guid]
            
            img = bpy.data.images.get(guid)
            if not img:
                img = bpy.data.images.new(guid, 1, 1)
                img.pack(data=buffer, data_len=len(buffer))
                img.source = 'FILE'
            
            self.texture_cache[guid] = img
            return img
            
        except Exception as e:
            print(f"  Failed to load swatchbin: {filepath} - {e}")
            return None
    
    def _load_standard_image(self, filepath, suggested_name=None):
        """Load a standard image file (png, jpg, tga, dds, etc.).
        
        Args:
            filepath: Full path to the image file
            suggested_name: Optional cleaner name to use instead of the filename
        """
        try:
            if filepath in self.texture_cache:
                return self.texture_cache[filepath]
            
            # Load the image
            img = bpy.data.images.load(filepath, check_existing=True)
            
            # If a suggested name is provided and the image doesn't already have a custom name, rename it
            if suggested_name and img.name == os.path.basename(filepath):
                # Check if a different image with this name already exists
                existing = bpy.data.images.get(suggested_name)
                if existing and existing != img:
                    # Keep original name if conflict
                    pass
                else:
                    img.name = suggested_name
            
            self.texture_cache[filepath] = img
            return img
        except Exception as e:
            print(f"  Failed to load image: {filepath} - {e}")
            return None
    
    def _auto_assign_textures_to_material(self, material, mat_name):
        """Search for a folder matching mat_name and auto-assign found textures."""
        forza_log(f"Auto-texture: Starting auto-assign for material '{mat_name}'")
        
        folder = self._find_texture_folder(mat_name)
        if not folder:
            forza_log(f"Auto-texture: No folder found matching '{mat_name}' - skipping")
            return
        
        forza_log(f"Auto-texture: Found folder '{folder}'")
        tex_map = self._scan_folder_for_textures(folder)
        
        if not tex_map:
            forza_log(f"Auto-texture: No classifiable textures found in folder - skipping")
            return
        
        forza_log(f"Auto-texture: Found {len(tex_map)} texture type(s) to assign: {list(tex_map.keys())}")
        
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        
        principled = None
        for node in nodes:
            if node.type == 'BSDF_PRINCIPLED':
                principled = node
                break
        if not principled:
            return
        
        y_offset = 400
        x_base = -600
        NON_COLOR_TYPES = {'Normal', 'Roughness', 'Metallic', 'AO', 'Alpha', 'Mask', 'Specular IOR Level'}

        # If this material was heuristically tagged as TILED, create a shared
        # Texture Coordinate + Mapping node so all textures can tile together.
        mapping_node = None
        texcoord_node = None
        usage_hint = None
        try:
            usage_hint = material.get("forza_usage", None)
        except Exception:
            usage_hint = None

        if usage_hint == "TILED":
            forza_log(
                f"Auto-texture: Material '{mat_name}' marked as TILED – "
                f"adding Mapping node for UV tiling"
            )
            texcoord_node = nodes.new('ShaderNodeTexCoord')
            texcoord_node.location = (x_base - 600, y_offset + 200)

            mapping_node = nodes.new('ShaderNodeMapping')
            mapping_node.vector_type = 'POINT'
            mapping_node.location = (x_base - 400, y_offset + 200)

            # Default tiling factor (can be adjusted per-material later by the user)
            mapping_node.inputs['Scale'].default_value[0] = 4.0
            mapping_node.inputs['Scale'].default_value[1] = 4.0

            links.new(texcoord_node.outputs['UV'], mapping_node.inputs['Vector'])
        
        for tex_type, tex_path in tex_map.items():
            forza_log(f"Auto-texture: Loading texture '{os.path.basename(tex_path)}' for type '{tex_type}'")
            
            # Create a cleaner name: {material_name}_{texture_type}
            # e.g., "plastic_textured_001_Normal" or "plastic_textured_001_BaseColor"
            clean_name = f"{mat_name}_{tex_type.replace(' ', '')}"
            img = self._load_texture_from_file(tex_path, suggested_name=clean_name)
            
            if not img:
                forza_log(f"Auto-texture: Failed to load texture '{tex_path}' - skipping")
                continue
            
            if tex_type in NON_COLOR_TYPES:
                try:
                    img.colorspace_settings.name = 'Non-Color'
                except:
                    pass
            
            tex_node = nodes.new('ShaderNodeTexImage')
            tex_node.image = img
            tex_node.label = tex_type
            tex_node.location = (x_base, y_offset)
            y_offset -= 300

            # If we created a Mapping node for tiling, hook it up to each texture.
            if mapping_node is not None:
                try:
                    links.new(mapping_node.outputs['Vector'], tex_node.inputs['Vector'])
                except Exception:
                    pass
            
            if tex_type == 'Base Color':
                links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
            elif tex_type == 'Normal':
                normal_map = nodes.new('ShaderNodeNormalMap')
                normal_map.location = (x_base + 300, tex_node.location[1])
                links.new(tex_node.outputs['Color'], normal_map.inputs['Color'])
                links.new(normal_map.outputs['Normal'], principled.inputs['Normal'])
            elif tex_type == 'Roughness':
                links.new(tex_node.outputs['Color'], principled.inputs['Roughness'])
            elif tex_type == 'Metallic':
                links.new(tex_node.outputs['Color'], principled.inputs['Metallic'])
            elif tex_type == 'Emission Color':
                links.new(tex_node.outputs['Color'], principled.inputs['Emission Color'])
                principled.inputs['Emission Strength'].default_value = 1.0
            elif tex_type == 'Specular IOR Level':
                links.new(tex_node.outputs['Color'], principled.inputs['Specular IOR Level'])
            elif tex_type == 'Alpha':
                links.new(tex_node.outputs['Color'], principled.inputs['Alpha'])
                if hasattr(material, 'blend_method'):
                    material.blend_method = 'CLIP'
            elif tex_type == 'AO':
                base_link = None
                for link in links:
                    if link.to_socket == principled.inputs['Base Color']:
                        base_link = link
                        break
                if base_link:
                    mix_node = nodes.new('ShaderNodeMix')
                    mix_node.data_type = 'RGBA'
                    mix_node.blend_type = 'MULTIPLY'
                    mix_node.location = (x_base + 300, tex_node.location[1])
                    mix_node.inputs['Factor'].default_value = 1.0
                    old_source = base_link.from_socket
                    links.remove(base_link)
                    links.new(old_source, mix_node.inputs[6])
                    links.new(tex_node.outputs['Color'], mix_node.inputs[7])
                    links.new(mix_node.outputs[2], principled.inputs['Base Color'])
                else:
                    links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
            elif tex_type == 'Mask':
                links.new(tex_node.outputs['Color'], principled.inputs['Alpha'])
            
            forza_log(f"Auto-texture: Assigned '{os.path.basename(tex_path)}' -> {tex_type} (connected to Principled BSDF)")
    
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
        global FORZA_LAST_MESH_COUNT, FORZA_LAST_MATERIAL_COUNT
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

            # Update counters
            FORZA_LAST_MESH_COUNT += 1
            if self.options['import_materials']:
                # Count unique materials by name for this session
                FORZA_LAST_MATERIAL_COUNT = len(bpy.data.materials)
    
    def create_blender_material(self, obj, mat_instance):
        """Create Blender material with textures"""
        try:
            # Determine material name
            use_filename = self.options.get('use_material_filename', True)
            
            if use_filename and mat_instance.source_file:
                # Use the source filename without extension
                mat_name = os.path.splitext(mat_instance.source_file)[0]
            else:
                # Use internal name
                mat_name = mat_instance.name

            # Best-effort usage hint based on material name (DECAL vs TILED)
            usage_hint = self._guess_material_usage(mat_name)
            
            # Debug output
            print(f"Creating material: '{mat_name}'")
            if mat_instance.source_file:
                print(f"  Source file: {mat_instance.source_file}")
            print(f"  Internal name: {mat_instance.name}")
            
            # Create or reuse material
            material = bpy.data.materials.get(mat_name)
            is_new_material = False
            
            if not material:
                is_new_material = True
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
                
                # If this material looks like a tiled surface, create a shared
                # Texture Coordinate + Mapping setup for its primary textures.
                texcoord_node = None
                mapping_node = None
                if usage_hint == "TILED":
                    texcoord_node = nodes.new('ShaderNodeTexCoord')
                    texcoord_node.location = (-800, 200)

                    mapping_node = nodes.new('ShaderNodeMapping')
                    mapping_node.vector_type = 'POINT'
                    mapping_node.location = (-600, 200)
                    mapping_node.inputs['Scale'].default_value[0] = 4.0
                    mapping_node.inputs['Scale'].default_value[1] = 4.0

                    links.new(texcoord_node.outputs['UV'], mapping_node.inputs['Vector'])
                
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
                            # Hook up mapping for tiled materials if present
                            if mapping_node is not None:
                                try:
                                    links.new(mapping_node.outputs['Vector'], tex_node.inputs['Vector'])
                                except Exception:
                                    pass
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
                            # Hook up mapping for tiled materials if present
                            if mapping_node is not None:
                                try:
                                    links.new(mapping_node.outputs['Vector'], tex_node.inputs['Vector'])
                                except Exception:
                                    pass
                            
                            normal_map = nodes.new('ShaderNodeNormalMap')
                            normal_map.location = (-100, -200)
                            
                            links.new(tex_node.outputs['Color'], normal_map.inputs['Color'])
                            links.new(normal_map.outputs['Normal'], principled.inputs['Normal'])
            
            if usage_hint:
                try:
                    material["forza_usage"] = usage_hint
                except Exception:
                    pass
                forza_log(f"Usage hint for material '{mat_name}': {usage_hint}")
            else:
                forza_log(f"Usage hint for material '{mat_name}': UNKNOWN")

            if self.options.get('auto_assign_textures', False) and mat_name:
                nodes = material.node_tree.nodes
                has_textures = any(node.type == 'TEX_IMAGE' for node in nodes)
                
                if not has_textures or is_new_material:
                    forza_log(
                        f"Auto-texture: Attempting auto-assignment for material "
                        f"'{mat_name}' (new={is_new_material}, has_textures={has_textures})"
                    )
                    self._auto_assign_textures_to_material(material, mat_name)
                else:
                    forza_log(
                        f"Auto-texture: Skipping '{mat_name}' for auto-assignment "
                        f"(material already has textures assigned)"
                    )
            
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

    def _guess_material_usage(self, mat_name):
        """Best-effort heuristic: guess if a material is a DECAL or TILED surface.

        We only look at the material name here because the Forza data does not expose any
        explicit 'is decal' flag. This is meant as a helper hint for the artist.
        
        Strategy: Check for TILED keywords first (they're more common), then DECAL.
        If both match, TILED takes precedence since surface materials are more common.
        """
        if not mat_name:
            return None

        name_lower = mat_name.lower()
        
        # Check for tiled surface hints first (more common, should take precedence)
        for kw in self.TILED_HINT_KEYWORDS:
            if kw in name_lower:
                forza_log(f"  -> Matched TILED keyword '{kw}' in material name '{mat_name}'")
                return "TILED"

        # Then check for decal hints (less common, but specific)
        for kw in self.DECAL_HINT_KEYWORDS:
            if kw in name_lower:
                forza_log(f"  -> Matched DECAL keyword '{kw}' in material name '{mat_name}'")
                return "DECAL"

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

class FORZA_OT_log_reset_scroll(bpy.types.Operator):
    """Reset the Forza log scroll offset to show the newest messages."""
    bl_idname = "forza_log.reset_scroll"
    bl_label = "Reset Forza Log Scroll"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        global FORZA_LAST_MESH_COUNT, FORZA_LAST_MATERIAL_COUNT, FORZA_LOG_MESSAGES

        settings = context.scene.forza_import_settings
        settings.log_scroll = 0
        return {'FINISHED'}

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
    
    game_root: StringProperty(
        name="Game Media Root (Optional)",
        description=(
            "Root folder that corresponds to 'Game:\\' in material paths, usually the "
            "Forza Media directory. Leave empty to only use the car folder."
        ),
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
    
    use_material_filename: BoolProperty(
        name="Use Material File Names",
        description="Use .materialbin filename for material names instead of internal names",
        default=True
    )
    
    auto_assign_textures: BoolProperty(
        name="Auto Assign Textures (Experimental)",
        description=(
            "EXPERIMENTAL: After materials are created, search for a folder whose name "
            "matches the material name and auto-assign textures by keyword "
            "(diff, normal, ao, mask, emissive, etc.). Results may be unstable."
        ),
        default=False
    )

    # Log view settings
    log_scroll: IntProperty(
        name="Scroll",
        description="Scroll offset for the Forza Log (0 = newest messages)",
        default=0,
        min=0,
        soft_max=200
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
    bl_category = 'Forza Main'
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.forza_import_settings
        
        box = layout.box()
        box.label(text="Car Folder", icon='FILE_FOLDER')
        box.prop(settings, "directory", text="")
        
        box = layout.box()
        box.label(text="Game Media Root (Optional)", icon='DISK_DRIVE')
        col = box.column(align=True)
        col.prop(settings, "game_root", text="")
        col.scale_y = 0.7
        col.label(text="Point to folder containing 'Media' directory", icon='INFO')
        
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
        
        box = layout.box()
        box.label(text="Materials", icon='MATERIAL')
        box.prop(settings, "import_materials")
        if settings.import_materials:
            box.prop(settings, "use_material_filename")
            if settings.use_material_filename:
                sub = box.box()
                sub.prop(settings, "auto_assign_textures")
        
        layout.separator()
        layout.operator("import_scene.forza_car_folder", text="Import Car Folder", icon='IMPORT')


class VIEW3D_PT_forza_tutorial(bpy.types.Panel):
    """Forza Tutorial Panel"""
    bl_label = "Forza Tutorial"
    bl_idname = "VIEW3D_PT_forza_tutorial"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Forza Tutorial'
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.forza_import_settings
        
        header = layout.box()
        header.label(text="Forza Car Importer Tutorial", icon='BOOKMARKS')
        col = header.column(align=True)
        col.scale_y = 0.9
        col.label(text="Complete guide to importing Forza cars into Blender")
        
        layout.separator()
        
        step1 = layout.box()
        step1.label(text="Step 1: Select Car Folder", icon='FILE_FOLDER')
        col = step1.column(align=True)
        col.scale_y = 0.85
        col.label(text="• Browse to the main car folder containing .modelbin files")
        col.label(text="• No full game path needed - just the car folder")
        col.label(text="• Example: D:\\Vehicles\\CARS\\[2016] Mercedes c63 Coupe\\")
        
        layout.separator()
        
        step2 = layout.box()
        step2.label(text="Step 2: Configure Import Settings", icon='SETTINGS')
        col = step2.column(align=True)
        col.scale_y = 0.85
        col.label(text="• Select LOD levels to import (LOD0 = highest detail)")
        col.label(text="• Enable 'Import Materials & Textures' for complete materials")
        col.label(text="• Enable 'Use Material File Names' for cleaner material names")
        
        layout.separator()
        
        step3 = layout.box()
        step3.label(text="Step 3: Game Media Root (Optional)", icon='DISK_DRIVE')
        col = step3.column(align=True)
        col.scale_y = 0.85
        col.label(text="• Only needed if material paths reference Game:\\Media\\...")
        col.label(text="• Point to the folder that CONTAINS the 'Media' directory")
        col.label(text="• Example: Game:\\Media\\... → D:\\ForzaDump\\Media\\...")
        col.label(text="• Leave empty if all files are in the car folder")
        
        layout.separator()
        
        step4 = layout.box()
        step4.label(text="Step 4: Import", icon='IMPORT')
        col = step4.column(align=True)
        col.scale_y = 0.85
        col.label(text="• Click 'Import Car Folder' button")
        col.label(text="• Check 'Forza Log' tab for import progress")
        col.label(text="• Materials and meshes will appear in your scene")
        
        layout.separator()
        
        auto_box = layout.box()
        auto_box.label(text="Auto-Texture Feature (Experimental)", icon='TEXTURE')
        col = auto_box.column(align=True)
        col.scale_y = 0.85
        
        col.label(text="MUST HAVE:", icon='CHECKMARK')
        col.label(text="  • Folders named exactly like the material/file name")
        col.label(text="  • Folders must be INSIDE the selected car folder")
        col.label(text="  • Texture files (PNG, JPG, TGA, DDS, etc.) inside those folders")
        
        col.separator()
        col.label(text="MUST DO:", icon='INFO')
        col.label(text="  • Use clear keywords in filenames: diff, normal, ao, mask, metal...")
        col.label(text="  • Check 'Forza Log' tab for detailed assignment logs")
        col.label(text="  • Tiled textures (carbon, patterns) get automatic Mapping nodes")
        
        col.separator()
        col.label(text="Texture Keywords:", icon='KEY_HLT')
        col.label(text="  • Base Color: diffuse, diff, albedo, base, color, col")
        col.label(text="  • Normal: normal, nrml, nrm, nor, bump")
        col.label(text="  • Roughness: roughness, rough, rgh, glos, gloss")
        col.label(text="  • Metallic: metallic, metal, met")
        col.label(text="  • AO: ao, occlusion, icao, lcao, cao")
        col.label(text="  • Alpha: opacity, opac, alpha, transparency")
        col.label(text="  • Emission: emissive, emission, emit, emis, glow")
        
        layout.separator()
        
        compat_box = layout.box()
        compat_box.label(text="Compatibility", icon='CHECKMARK')
        col = compat_box.column(align=True)
        col.scale_y = 0.85
        col.label(text="✓ Forza Horizon 4: Confirmed working")
        col.label(text="✓ Forza Horizon 5: Confirmed working")
        col.label(text="? Lower versions: May or may not work")
        
        layout.separator()
        
        credit_box = layout.box()
        credit_box.label(text="Credits", icon='INFO')
        col = credit_box.column(align=True)
        col.scale_y = 0.8
        col.label(text="Original ModelBin importer: @Doliman100")
        col.label(text="GitHub: https://github.com/Doliman100")


class VIEW3D_PT_forza_log(bpy.types.Panel):
    """Simple in-Blender log view for the Forza importer."""
    bl_label = "Forza Log"
    bl_idname = "VIEW3D_PT_forza_log"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Forza Log'

    def draw(self, context):
        from textwrap import wrap

        layout = self.layout
        settings = context.scene.forza_import_settings

        # Summary box for last import
        summary = layout.box()
        summary.label(text="Last Import Summary", icon='INFO')
        col = summary.column(align=True)
        col.scale_y = 0.9
        col.label(text=f"Meshes created : {FORZA_LAST_MESH_COUNT}")
        col.label(text=f"Materials total: {FORZA_LAST_MATERIAL_COUNT}")

        layout.separator()

        # Scroll controls
        controls = layout.box()
        controls.label(text="Log View", icon='CONSOLE')
        row = controls.row(align=True)
        row.prop(settings, "log_scroll", text="Scroll Offset")
        row.operator("forza_log.reset_scroll", text="", icon='FILE_REFRESH')

        box = layout.box()
        box.label(text="Recent Log Messages", icon='TEXT')

        col = box.column(align=True)
        col.scale_y = 0.9

        if not FORZA_LOG_MESSAGES:
            col.label(text="No messages yet. Run an import to see activity.")
            return

        # Simple manual scrolling: log_scroll = 0 shows newest, higher shows older
        max_visible = 40
        offset = max(0, min(settings.log_scroll, len(FORZA_LOG_MESSAGES) - 1))
        start = max(0, len(FORZA_LOG_MESSAGES) - max_visible - offset)
        end = len(FORZA_LOG_MESSAGES) - offset

        for msg in FORZA_LOG_MESSAGES[start:end]:
            # Wrap long lines so they fit better in the panel
            for line in wrap(msg, 80):
                col.label(text=line)

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
            'import_materials': settings.import_materials,
            'use_material_filename': settings.use_material_filename,
            'auto_assign_textures': settings.auto_assign_textures,
            'game_root': settings.game_root if settings.game_root else None
        }
        
        # Reset per-import counters and (optionally) trim log
        FORZA_LAST_MESH_COUNT = 0
        FORZA_LAST_MATERIAL_COUNT = len(bpy.data.materials)
        # Keep recent history but make it clear this is a new run
        FORZA_LOG_MESSAGES.append("-" * 40)
        FORZA_LOG_MESSAGES.append(f"[ForzaImporter] New import run for folder: {folder_path}")
        
        # Import
        forza_log(f"{'='*60}")
        forza_log(f"Importing Forza car folder: {folder_path}")
        forza_log(f"Materials enabled: {settings.import_materials}")
        forza_log(f"{'='*60}")
        
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
    bpy.utils.register_class(VIEW3D_PT_forza_tutorial)
    bpy.utils.register_class(VIEW3D_PT_forza_log)
    bpy.utils.register_class(FORZA_OT_log_reset_scroll)
    bpy.utils.register_class(IMPORT_OT_forza_car_folder)
    bpy.types.Scene.forza_import_settings = bpy.props.PointerProperty(type=ForzaImportSettings)

def unregister():
    bpy.utils.unregister_class(IMPORT_OT_forza_car_folder)
    bpy.utils.unregister_class(FORZA_OT_log_reset_scroll)
    bpy.utils.unregister_class(VIEW3D_PT_forza_log)
    bpy.utils.unregister_class(VIEW3D_PT_forza_tutorial)
    bpy.utils.unregister_class(VIEW3D_PT_forza_importer)
    bpy.utils.unregister_class(ForzaImportSettings)
    del bpy.types.Scene.forza_import_settings

if __name__ == "__main__":
    register()
