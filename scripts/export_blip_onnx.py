"""Export BLIP image captioning to ONNX, in two parts.

optimum has no built-in ONNX config for BLIP, so this exports the pieces
directly:

  vision_encoder.onnx  pixel_values                      -> image_embeds
  text_decoder.onnx    input_ids, attention_mask,
                       encoder_hidden_states             -> logits

The decoder is exported *without* a KV cache: greedy captions are ~15
tokens, so the quadratic re-computation is cheap next to the win of
running on the GPU at all, and a cacheless graph is far easier to keep
numerically identical to PyTorch. filesight.inference drives the greedy
loop itself.

Run this in an ISOLATED environment (see docs/onnx-export.md) — the
exporter pins transformers 4.x, which the FileSight runtime does not use.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from transformers import BlipForConditionalGeneration, BlipProcessor

MODEL_ID = "Salesforce/blip-image-captioning-base"
OPSET = 14


class VisionEncoder(torch.nn.Module):
    def __init__(self, model: BlipForConditionalGeneration) -> None:
        super().__init__()
        self.vision_model = model.vision_model

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        return self.vision_model(pixel_values=pixel_values)[0]


class TextDecoder(torch.nn.Module):
    def __init__(self, model: BlipForConditionalGeneration) -> None:
        super().__init__()
        self.text_decoder = model.text_decoder

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        encoder_hidden_states: torch.Tensor,
    ) -> torch.Tensor:
        encoder_attention_mask = torch.ones(
            encoder_hidden_states.shape[:2], dtype=torch.long
        )
        out = self.text_decoder(
            input_ids=input_ids,
            attention_mask=attention_mask,
            encoder_hidden_states=encoder_hidden_states,
            encoder_attention_mask=encoder_attention_mask,
            return_dict=True,
        )
        return out.logits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="output directory")
    parser.add_argument("--model", default=MODEL_ID)
    args = parser.parse_args()

    out: Path = args.output
    out.mkdir(parents=True, exist_ok=True)

    print(f"loading {args.model} ...", flush=True)
    model = BlipForConditionalGeneration.from_pretrained(args.model).eval()
    processor = BlipProcessor.from_pretrained(args.model)

    image_size = model.config.vision_config.image_size
    pixel_values = torch.zeros(1, 3, image_size, image_size)

    print("exporting vision encoder ...", flush=True)
    with torch.no_grad():
        torch.onnx.export(
            VisionEncoder(model),
            (pixel_values,),
            str(out / "vision_encoder.onnx"),
            input_names=["pixel_values"],
            output_names=["image_embeds"],
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "image_embeds": {0: "batch"},
            },
            opset_version=OPSET,
            do_constant_folding=True,
        )
        image_embeds = VisionEncoder(model)(pixel_values)

    print("exporting text decoder ...", flush=True)
    input_ids = torch.tensor([[model.config.text_config.bos_token_id, 100]])
    attention_mask = torch.ones_like(input_ids)
    with torch.no_grad():
        torch.onnx.export(
            TextDecoder(model),
            (input_ids, attention_mask, image_embeds),
            str(out / "text_decoder.onnx"),
            input_names=["input_ids", "attention_mask", "encoder_hidden_states"],
            output_names=["logits"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "sequence"},
                "attention_mask": {0: "batch", 1: "sequence"},
                "encoder_hidden_states": {0: "batch", 1: "vision_sequence"},
                "logits": {0: "batch", 1: "sequence"},
            },
            opset_version=OPSET,
            do_constant_folding=True,
        )

    processor.save_pretrained(out)
    text_config = model.config.text_config
    (out / "filesight-model.json").write_text(
        json.dumps(
            {
                "model_id": args.model,
                "opset": OPSET,
                "image_size": image_size,
                "bos_token_id": text_config.bos_token_id,
                "eos_token_id": text_config.sep_token_id,
                "pad_token_id": text_config.pad_token_id,
                "decoder_start_token_id": model.config.text_config.bos_token_id,
                "kv_cache": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"done -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
