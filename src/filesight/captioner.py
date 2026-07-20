"""Local image captioning via a Hugging Face vision-language model.

The heavy imports (torch, transformers) happen lazily inside ``load`` so
that the CLI can print helpful errors first and unit tests never touch
the neural network.
"""

from __future__ import annotations

from typing import Protocol

from PIL import Image

DEFAULT_MODEL = "Salesforce/blip-image-captioning-base"


class ImageCaptioner(Protocol):
    """Anything that can caption a PIL image."""

    model_name: str
    device: str

    def caption(self, image: Image.Image) -> str: ...


class BlipCaptioner:
    """CPU captioner built on BLIP (no trust_remote_code required)."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self.device = "cpu"
        self._model = None
        self._processor = None

    def load(self) -> None:
        """Download (on first run) and load the model. May take a while."""
        from transformers import BlipForConditionalGeneration, BlipProcessor

        self._processor = BlipProcessor.from_pretrained(self.model_name)
        self._model = BlipForConditionalGeneration.from_pretrained(self.model_name)
        self._model.to(self.device)
        self._model.eval()

    def caption(self, image: Image.Image) -> str:
        if self._model is None or self._processor is None:
            self.load()
        import torch

        inputs = self._processor(images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            output_ids = self._model.generate(
                **inputs, max_new_tokens=32, num_beams=3
            )
        text: str = self._processor.decode(output_ids[0], skip_special_tokens=True)
        return text.strip()


def load_image_for_captioning(path: str) -> Image.Image:
    """Open an image, fix EXIF orientation and convert to RGB."""
    from PIL import ImageOps

    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")
