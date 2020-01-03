from .data import *
from ctypes import *
from typing import Type
import io


class PskReader(object):
    def __init__(self):
        pass

    @staticmethod
    def read_section_data(f: io.BytesIO, section: Section, data_type: Type[Structure]):
        assert section.data_size == sizeof(data_type)
        for i in range(section.data_count):
            buffer = f.read(section.data_size)
            yield data_type.from_buffer_copy(buffer)

    def read(self, path: str) -> Psk:
        psk = Psk()
        with open(path, 'rb') as f:
            while True:
                buffer = f.read(sizeof(Section))
                if len(buffer) == 0:
                    # EOF
                    break
                assert len(buffer) == sizeof(Section), \
                    f'Section size mismatch (expected: {sizeof(Section)}, found {len(buffer)})'
                section = Section.from_buffer_copy(buffer)
                assert section.type_flags == 1999801
                if section.name == b'PNTS0000':
                    psk.points.extend(self.read_section_data(f, section, Vector3))
                elif section.name == b'VTXW0000':
                    wedge_type = Psk.get_wedge_type(section.data_count)
                    psk.wedges.extend(self.read_section_data(f, section, wedge_type))
                elif section.name == b'FACE0000':
                    psk.faces.extend(self.read_section_data(f, section, Psk.Face))
                elif section.name == b'MATT0000':
                    psk.materials.extend(self.read_section_data(f, section, Psk.Material))
                elif section.name == b'REFSKELT':
                    psk.bones.extend(self.read_section_data(f, section, Psk.Bone))
                elif section.name == b'RAWWEIGHTS':
                    psk.weights.extend(self.read_section_data(f, section, Psk.Weight))
                else:
                    # Unhandled or zero-data section.
                    # Skip the data!
                    f.seek(section.data_size * section.data_count, io.SEEK_CUR)
        return psk
