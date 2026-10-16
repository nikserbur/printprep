# Bundled pretrained model

FSRCNN ×2, 38,973 bytes, from the author's OpenCV GSoC repository:
https://github.com/Saafke/FSRCNN_Tensorflow/blob/master/models/FSRCNN_x2.pb

SHA-256: `366b33f0084c7b3f2bf6724f0a2c77bca94fcec9d7b6d72389d330073b380d5c`

Repository license: Apache-2.0; unmodified text in
`licenses/FSRCNN-Apache-2.0.txt`. Attribution: Saafke's FSRCNN TensorFlow
implementation, with a subpixel output layer, trained on T91 and fine-tuned
on General100 as described by the author. Original FSRCNN paper:
Dong, Loy, Tang, ECCV 2016.

Inference uses OpenCV DNN, not TensorFlow or PyTorch. No model is downloaded
at runtime. FSRCNN is compact and established, but is not state-of-the-art
photo restoration. Default: OFF. Output must be reviewed for artifacts.
