"""Recreate the browser verifier's embedded float16 filters from MediaPipe 0.10.21.

    build/p2s-venv/bin/python tools/pack_face_verifier.py --check

Supply --model if the original wheel's face_detection_short_range.tflite is
elsewhere. Without --check, replace only the weight string in the browser JS.
"""
import argparse
import base64
import hashlib
from importlib.util import find_spec
from pathlib import Path
import re

import numpy as np
from mediapipe.tasks.metadata import schema_py_generated as schema


SOURCE_SHA256 = 'bbff11cebd1eb27a1e004cae0b0e63ec8c551cbf34a4451148b4908b8db3eca8'
MODULE = Path(__file__).resolve().parents[1] / 'web' / 'guest-face-verify.js'


def packed_filters(source):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('Expected the original MediaPipe 0.10.21 short-range model')
    model = schema.Model.GetRootAsModel(source, 0)
    graph = model.Subgraphs(0)
    originals, layers = {}, {}
    for index in range(graph.OperatorsLength()):
        op = graph.Operators(index)
        opcode = model.OperatorCodes(op.OpcodeIndex())
        kind = max(opcode.BuiltinCode(), opcode.DeprecatedBuiltinCode())
        if kind == schema.BuiltinOperator.DEQUANTIZE:
            originals[op.Outputs(0)] = op.Inputs(0)
        if kind not in (schema.BuiltinOperator.CONV_2D, schema.BuiltinOperator.DEPTHWISE_CONV_2D):
            continue
        name = graph.Tensors(op.Outputs(0)).Name().decode()
        parameters = []
        for source_id in op.InputsAsNumpy()[1:]:
            tensor = graph.Tensors(originals[source_id])
            if tensor.Type() != schema.TensorType.FLOAT16:
                raise ValueError(f'Unexpected parameter type in {name}')
            raw = model.Buffers(tensor.Buffer()).DataAsNumpy()
            parameters.append(raw.view('<f2').reshape(tensor.ShapeAsNumpy()))
        kernel, bias = parameters
        if name.startswith('regressor_'):
            bounds = np.arange(len(bias)) % 16 < 4  # x, y, w, h; omit the six keypoints
            kernel, bias = kernel[bounds], bias[bounds]
        layers[name] = kernel.transpose(1, 2, 3, 0).tobytes() + bias.tobytes()

    order = ['conv2d']
    for index in range(16):
        depth = f'depthwise_conv2d_{index}' if index else 'depthwise_conv2d'
        order.extend([depth, f'conv2d_{index+1}'])
    for stride in (8, 16):
        order.extend([f'classificator_{stride}', f'regressor_{stride}'])
    if set(order) != set(layers):
        raise ValueError('Unexpected layers in the verifier model')
    return base64.b64encode(b''.join(layers[name] for name in order)).decode('ascii')


if __name__ == '__main__':
    package = Path(find_spec('mediapipe').origin).parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=package / 'modules/face_detection/face_detection_short_range.tflite')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    encoded = packed_filters(args.model.read_bytes())
    current = MODULE.read_text()
    updated, count = re.subn(r"(?<=const PACKED_WEIGHTS = ')[A-Za-z0-9+/=]+(?=';)", lambda _: encoded, current)
    if count != 1:
        parser.exit(1, 'Expected exactly one embedded verifier weight string\n')
    if args.check and updated != current:
        parser.exit(1, 'Embedded verifier weights differ from the original model\n')
    if updated != current:
        MODULE.write_text(updated)
    print('Browser weights match the MediaPipe short-range detector.')
