"""Analyze extracted frames and aggregate their captions into one.

No new language model: aggregation is deterministic and reuses the
existing naming tokenizer so word handling stays consistent with images.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

from filesight.captioner import ImageCaptioner
from filesight.frame_quality import assess_frame
from filesight.models import FileError, VideoFrameResult
from filesight.naming import caption_to_words

FrameProgress = Callable[[str, int, int], None]

# Warning codes
PARTIAL_FRAME_ANALYSIS = "partial_frame_analysis"


class VideoCaptionAggregator:
    """Combine per-frame captions into a single representative caption.

    Strategy (deterministic, stable): count how often each significant
    word appears across frames, then pick the frame caption whose words
    best cover those frequent words. Ties go to the earliest frame.
    """

    def aggregate(self, captions: list[str]) -> Optional[str]:
        cleaned = [c.strip() for c in captions if c and c.strip()]
        if not cleaned:
            return None
        if len(cleaned) == 1:
            return cleaned[0]

        frequency: Counter[str] = Counter()
        per_caption_words: list[set[str]] = []
        for caption in cleaned:
            words = set(caption_to_words(caption))
            per_caption_words.append(words)
            frequency.update(words)

        best_index = 0
        best_score = -1
        for index, words in enumerate(per_caption_words):
            score = sum(frequency[word] for word in words)
            if score > best_score:
                best_score = score
                best_index = index
        return cleaned[best_index]


@dataclass
class FrameAnalysis:
    frame_results: list[VideoFrameResult]
    usable_frames: int
    analyzed_frames: int
    aggregated_caption: Optional[str]
    warnings: list[str] = field(default_factory=list)
    captioning_ms: int = 0
    aggregation_ms: int = 0


def analyze_frames(
    extracted: list["ExtractedFrameLike"],
    captioner: ImageCaptioner,
    on_progress: Optional[FrameProgress] = None,
) -> FrameAnalysis:
    """Assess quality, caption usable frames, then aggregate the captions.

    ``extracted`` items must have ``index``, ``timestamp_seconds``,
    ``path`` and ``error`` attributes (see video_frames.ExtractedFrame).
    A failed single frame never fails the whole video.
    """
    from filesight.captioner import load_image_for_captioning

    frame_results: list[VideoFrameResult] = []
    captions: list[str] = []
    previous_hash: Optional[int] = None
    usable = 0
    analyzed = 0
    captioning_ms = 0

    total = len(extracted)
    for position, frame in enumerate(extracted, start=1):
        if frame.path is None:
            frame_results.append(
                VideoFrameResult(
                    index=frame.index,
                    timestamp_seconds=frame.timestamp_seconds,
                    status="failed",
                    error=FileError(type="FrameExtractionError", message=frame.error or ""),
                )
            )
            continue

        quality = assess_frame(frame.path, previous_hash)
        if not quality.usable:
            frame_results.append(
                VideoFrameResult(
                    index=frame.index,
                    timestamp_seconds=frame.timestamp_seconds,
                    status="skipped",
                    skip_reason=quality.skip_reason,
                )
            )
            continue

        previous_hash = quality.dhash
        usable += 1
        if on_progress is not None:
            on_progress("Analyzing frame", position, total)
        start = time.perf_counter()
        try:
            image = load_image_for_captioning(frame.path)
            caption = captioner.caption(image)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            captioning_ms += int((time.perf_counter() - start) * 1000)
            frame_results.append(
                VideoFrameResult(
                    index=frame.index,
                    timestamp_seconds=frame.timestamp_seconds,
                    status="failed",
                    error=FileError(type=type(exc).__name__, message=str(exc) or repr(exc)),
                )
            )
            continue
        captioning_ms += int((time.perf_counter() - start) * 1000)
        analyzed += 1
        captions.append(caption)
        frame_results.append(
            VideoFrameResult(
                index=frame.index,
                timestamp_seconds=frame.timestamp_seconds,
                status="success",
                caption=caption,
            )
        )

    agg_start = time.perf_counter()
    aggregated = VideoCaptionAggregator().aggregate(captions)
    aggregation_ms = int((time.perf_counter() - agg_start) * 1000)

    warnings: list[str] = []
    if analyzed and analyzed < total:
        warnings.append(PARTIAL_FRAME_ANALYSIS)

    return FrameAnalysis(
        frame_results=frame_results,
        usable_frames=usable,
        analyzed_frames=analyzed,
        aggregated_caption=aggregated,
        warnings=warnings,
        captioning_ms=captioning_ms,
        aggregation_ms=aggregation_ms,
    )


class ExtractedFrameLike:  # pragma: no cover - typing helper
    index: int
    timestamp_seconds: float
    path: Optional[str]
    error: Optional[str]
