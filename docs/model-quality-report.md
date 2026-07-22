# FileSight — model quality report (iteration 6)

## Summary

The production captioning model is unchanged from iterations 1–5:

- **`Salesforce/blip-image-captioning-base`**, run on **PyTorch CPU**.

No ONNX caption model is shipped yet, so there is no PyTorch-vs-ONNX
caption quality comparison to report. This section records **why**, so the
decision is auditable (the iteration spec requires the technical reason
when the ONNX caption path is not completed).

## Why the caption model is not on ONNX/DirectML yet

BLIP captioning is an **autoregressive vision-to-seq** model: a ViT vision
encoder feeds a text decoder that generates tokens one at a time with
past-key-value caching. Exporting that to a working ONNX + DirectML
pipeline is a substantial, multi-step effort, and the current environment
blocks the usual tool:

- The standard exporter, `optimum` (`ORTModelForVision2Seq`), when
  installed here resolves to **downgrading transformers 5.14 → 4.57** and
  pulling plain **`onnxruntime` 1.27**, which **conflicts with
  `onnxruntime-directml` 1.24.4** (only one `onnxruntime` package may be
  installed). Confirmed via `pip install --dry-run "optimum[onnxruntime]"`.
- A correct export therefore needs an **isolated export environment**
  (separate venv, pinned transformers), and then the exported graphs must
  be quality-verified against PyTorch on a 50-image / 10-video reference
  set before replacing the production caption path.

This is exactly the fallback the spec anticipates ("зафіксувати точну
технічну причину"). Rather than ship a fake or half-working export, the
caption model stays on PyTorch CPU and is reported honestly.

## What *is* verified on the GPU

The `onnx-directml` backend runs a real ONNX model on the RX 580 via
`DmlExecutionProvider` (self-test + benchmark). This proves the runtime,
provider, device detection and session lifecycle work end to end — the
foundation the future ONNX caption model will plug into.

## Reference dataset

`tests/reference-media/manifest.json` defines the intended reference set
(concepts + expected category per file) without committing private media.
It is used for the future PyTorch-vs-ONNX comparison; this session did not
run a caption-quality comparison because there is no second caption model
to compare against.

## Decision

- **Default / production caption backend: `pytorch-cpu`.**
- DirectML remains verified-but-not-yet-captioning; it is never presented
  as the caption backend in a scan report.
