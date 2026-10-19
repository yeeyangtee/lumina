"""Media formats shared by scanner, workers and authenticated routes."""

from pathlib import Path

IMAGE_EXTS = {
    '.jpg',
    '.jpeg',
    '.png',
    '.gif',
    '.webp',
    '.bmp',
    '.tiff',
    '.tif',
    '.heic',
    '.heif',
    '.cr2',
}
VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.webm', '.avi'}
DERIVED_IMAGES = {'.cr2', '.tif', '.tiff'}
AUDIO_EXTS = {'.wav'}


def is_image(name):
    return Path(name).suffix.lower() in IMAGE_EXTS and not Path(name).name.startswith(
        '.'
    )


def is_video(name):
    return Path(name).suffix.lower() in VIDEO_EXTS and not Path(name).name.startswith(
        '.'
    )


def is_media(name):
    return is_image(name) or is_video(name)
