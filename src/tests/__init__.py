from src.psk.reader import PskReader

reader = PskReader()
psk = reader.read(r'C:\program files\umodel\UmodelExport\Axis_Kar98_1st\SkeletalMesh\kar98k_mesh.psk')

faces = set()
for f, face in enumerate(psk.faces):
    wedge_indices = [face.wedge_index_1, face.wedge_index_2, face.wedge_index_3]
    point_indices = [psk.wedges[i].point_index for i in wedge_indices]
    if len(set(point_indices)) < 3:
        print(f'degen {f}')
        continue
r = len(faces) == len(psk.faces)
print(r)
