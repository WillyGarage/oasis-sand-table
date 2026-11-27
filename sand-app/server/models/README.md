# Models used by face_art.py

Both are Google's official MediaPipe models, unchanged. SHA-256 checked on 2026-11-24 against fresh downloads from
the URLs below (identical to the copies `tools/photo2sand.py` uses in `~/.cache/photo2sand`).

| File | Size | Source |
|---|---|---|
| `face_landmarker.task` (478 face landmarks) | 3,758,596 B, sha256 `64184e22...0bc9ff` | https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task |
| `selfie_multiclass_256x256.tflite` (background, hair, body skin, face skin, clothes, accessories) | 16,371,837 B, sha256 `c6748b12...e0e0` | https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite |

Licence: Apache License 2.0, per Google's MediaPipe model cards for the Face Landmarker and the Selfie Multiclass
segmentation model (https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker,
https://ai.google.dev/edge/mediapipe/solutions/vision/image_segmenter). Keep the model cards' attribution if these
files are redistributed.
