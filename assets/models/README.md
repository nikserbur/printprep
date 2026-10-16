# Bundled pretrained models

All inference runs offline through OpenCV DNN on the CPU. Nothing is downloaded at
runtime; every file is verified by SHA-256 before first use (`printprep/neural.py`).

| File | Size | Purpose | Source | License |
| --- | --- | --- | --- | --- |
| `FSRCNN_x2.pb` | 38,973 B | Fast ×2 enlargement | Saafke/FSRCNN_Tensorflow (OpenCV GSoC), Dong/Loy/Tang ECCV 2016 | Apache-2.0, `licenses/FSRCNN-Apache-2.0.txt` |
| `realesr-general-x4v3.onnx` | 4,866,396 B | ×4 enlargement with detail restoration and JPEG/noise cleanup (SRVGGNetCompact, 1.2 M params) | Official Real-ESRGAN weights `realesr-general-x4v3.pth` (xinntao/Real-ESRGAN), ONNX export (fp32, opset 17) from huggingface.co/jonathanst29/tinier-upscale-models | BSD-3-Clause, `licenses/Real-ESRGAN-BSD-3-Clause.txt` |
| `face_detection_yunet_2023mar.onnx` | 232,589 B | Face detection for smart framing and face-aware exposure | huggingface.co/opencv/face_detection_yunet (OpenCV Zoo) | MIT, `licenses/YuNet-MIT.txt` |

SHA-256:

- `FSRCNN_x2.pb` — `366b33f0084c7b3f2bf6724f0a2c77bca94fcec9d7b6d72389d330073b380d5c`
- `realesr-general-x4v3.onnx` — `924ebad6532777303582d4ce7811849b88869231a3ae7093e0f21200249df8d5` (matches the Hugging Face LFS object id)
- `face_detection_yunet_2023mar.onnx` — `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` (matches the Hugging Face LFS object id)

Measured on the development PC (24 logical cores): Real-ESRGAN ≈ 9 s per input megapixel,
FSRCNN well under 1 s. Input limits: 6 MP (Real-ESRGAN), 12 MP (FSRCNN); larger frames fall
back to classic resampling with a note in the report. Without YuNet the Haar cascade shipped
with OpenCV is used. Super-resolution invents plausible detail; review at 100%.
