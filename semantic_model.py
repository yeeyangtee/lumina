"""Shared local OpenCLIP model loading and embedding helpers."""

from __future__ import annotations

import os

import numpy as np
import open_clip
import torch


MODEL_NAME = os.environ.get('NFS_VIEWER_CLIP_MODEL', 'MobileCLIP-S1')
PRETRAINED = os.environ.get('NFS_VIEWER_CLIP_PRETRAINED', 'datacompdr')
MODEL_ID = f'openclip:{MODEL_NAME}:{PRETRAINED}'
_model = _preprocess = _tokenizer = None


def load_model():
    global _model, _preprocess, _tokenizer
    if _model is None:
        torch.set_num_threads(int(os.environ.get('NFS_VIEWER_ML_THREADS', '6')))
        _model, _, _preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME, pretrained=PRETRAINED, device='cpu'
        )
        _model.eval()
        _tokenizer = open_clip.get_tokenizer(MODEL_NAME)
    return _model, _preprocess, _tokenizer


def embed_text(text: str) -> np.ndarray:
    model, _, tokenizer = load_model()
    with torch.inference_mode():
        features = model.encode_text(tokenizer([text]))
        features /= features.norm(dim=-1, keepdim=True)
    return features[0].cpu().numpy().astype(np.float32)


def embed_images(images) -> np.ndarray:
    model, preprocess, _ = load_model()
    batch = torch.stack([preprocess(image.convert('RGB')) for image in images])
    with torch.inference_mode():
        features = model.encode_image(batch)
        features /= features.norm(dim=-1, keepdim=True)
    return features.cpu().numpy().astype(np.float32)
