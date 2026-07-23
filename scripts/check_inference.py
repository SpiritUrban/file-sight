#!/usr/bin/env python3
"""Print inference providers, backends, and auto choice. Exit 1 if broken.

Safe to run on AMD, NVIDIA, or CPU-only machines. Does not require a GPU.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    print("FileSight inference probe")
    print("-" * 40)

    try:
        import onnxruntime as ort
    except Exception as exc:
        print(f"onnxruntime: NOT INSTALLED ({exc})")
        print("Install one of: pip install -e '.[cuda]' | '.[directml]' | '.[onnx]'")
        return 1

    print(f"onnxruntime: {ort.__version__}")
    providers = list(ort.get_available_providers())
    print(f"providers:   {providers}")

    has_cuda = "CUDAExecutionProvider" in providers
    has_dml = "DmlExecutionProvider" in providers
    print(f"CUDA EP:     {has_cuda}")
    print(f"DirectML EP: {has_dml}")

    if has_cuda and has_dml:
        print(
            "WARNING: both CUDA and DirectML listed — unusual; "
            "normally only one onnxruntime wheel is installed."
        )

    from filesight.inference import available_backends, resolve_backend
    from filesight.inference.onnx_caption import (
        describe_model_search,
        find_model_dir,
        model_is_available,
    )

    print()
    print("backends:")
    for row in available_backends():
        flag = "yes" if row["available"] else "no"
        cap = "caption" if row["can_caption"] else "no-caption"
        print(f"  {row['backend_id']:16} available={flag:3}  {cap}")

    pack = find_model_dir()
    print()
    print(f"model pack:  {pack or 'NOT FOUND'}")
    if not model_is_available():
        print("  (copy models/blip-onnx or set FILESIGHT_ONNX_MODEL_DIR)")
        # Keep going — auto may still land on pytorch-cpu.
        for part in describe_model_search().split("; ")[:8]:
            print(f"  search: {part}")

    selection = resolve_backend("auto")
    print()
    print("auto selection:")
    print(json.dumps(selection.report_dict(), indent=2, ensure_ascii=False))

    # Exit non-zero only when nothing can caption.
    if not any(b["can_caption"] for b in available_backends()):
        print("\nERROR: no backend can caption on this machine.", file=sys.stderr)
        return 1

    if has_cuda and selection.actual_backend != "onnx-cuda" and model_is_available():
        print(
            "\nNOTE: CUDA is present and the model pack exists, but auto did "
            f"not pick onnx-cuda (got {selection.actual_backend!r}). "
            "Check can_caption / errors above.",
            file=sys.stderr,
        )
        return 2

    if has_cuda:
        print("\nOK for NVIDIA: CUDA EP visible; use --backend onnx-cuda or auto.")
    elif has_dml:
        print("\nOK for DirectML: use --backend onnx-directml or auto.")
    else:
        print("\nOK CPU path: onnx/pytorch only (no GPU EP).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
