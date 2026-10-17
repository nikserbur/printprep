# Bundled pretrained models

All inference runs offline through OpenCV DNN on the CPU. Nothing is downloaded at
runtime; every file is verified by SHA-256 before first use (`printprep/neural.py`).

| File | Size | Purpose | Source | License |
| --- | --- | --- | --- | --- |
| `realesr-general-x4v3.onnx` | 4,866,396 B | The single enhancement network: ×4 enlargement with detail restoration and JPEG/noise cleanup (SRVGGNetCompact, 1.2 M params) | Official Real-ESRGAN weights `realesr-general-x4v3.pth` (xinntao/Real-ESRGAN), ONNX export (fp32, opset 17) from huggingface.co/jonathanst29/tinier-upscale-models | BSD-3-Clause, `licenses/Real-ESRGAN-BSD-3-Clause.txt` |
| `face_detection_yunet_2023mar.onnx` | 232,589 B | Face detection for smart framing and face-aware exposure | huggingface.co/opencv/face_detection_yunet (OpenCV Zoo) | MIT, `licenses/YuNet-MIT.txt` |

SHA-256 (both match the Hugging Face LFS object ids):

- `realesr-general-x4v3.onnx` — `924ebad6532777303582d4ce7811849b88869231a3ae7093e0f21200249df8d5`
- `face_detection_yunet_2023mar.onnx` — `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`

How the enhancement is used:

- It runs only where it visibly helps a print: when the photo is enlarged at least 1.3× and the
  source is at most 4 MP. Larger photos already have enough detail; smaller enlargements look the
  same with classic resampling plus output sharpening.
- It is computed once per photo and orientation in a background thread with progress, then cached
  (memory budget ~450 MB, shared by preview and export). Colour edits and the strength slider never
  re-run the network; strength is blended at render time.
- Sources up to 1.2 MP keep the full ×4 result, larger ones are stored at ×2 (tiles are averaged
  2×2 as they are produced, so memory stays at a quarter).
- Measured speed: ≈ 9 s per input megapixel on a 24-thread desktop, ≈ 13 s on 4 threads.

The earlier FSRCNN ×2 model was removed in 2.1: it added little visible improvement next to
Real-ESRGAN. Without YuNet the Haar cascade shipped with OpenCV is used. Super-resolution invents
plausible detail; review at 1:1.
