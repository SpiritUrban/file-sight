"""Determine when a media file was captured, and record where that came from.

Priority for images: EXIF DateTimeOriginal -> DateTimeDigitized ->
other EXIF date fields -> filesystem creation -> filesystem modified.
For videos: container creation_time -> filesystem creation -> modified.

Timezones are never invented: naive timestamps stay naive.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from filesight.models import MediaDateResult

# EXIF tag ids (avoids importing ExifTags at module import time)
_EXIF_DATETIME_ORIGINAL = 36867
_EXIF_DATETIME_DIGITIZED = 36868
_EXIF_DATETIME = 306

SOURCE_EXIF_ORIGINAL = "exif_datetime_original"
SOURCE_EXIF_DIGITIZED = "exif_datetime_digitized"
SOURCE_EXIF_DATETIME = "exif_datetime"
SOURCE_VIDEO_CREATION = "video_creation_time"
SOURCE_FS_CREATED = "filesystem_created"
SOURCE_FS_MODIFIED = "filesystem_modified"
SOURCE_NONE = "none"

WARNING_IMPLAUSIBLE = "implausible_metadata_date"

_MIN_PLAUSIBLE_YEAR = 1990
_EXIF_DATE_RE = re.compile(r"^(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})")


def _parse_exif_datetime(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    match = _EXIF_DATE_RE.match(value.strip())
    if not match:
        return None
    try:
        return datetime(*(int(part) for part in match.groups()))  # type: ignore[arg-type]
    except ValueError:
        return None


def is_plausible(moment: datetime, now: Optional[datetime] = None) -> bool:
    """Reject epoch/placeholder dates and dates far in the future."""
    reference = now or datetime.now()
    if moment.year < _MIN_PLAUSIBLE_YEAR:
        return False
    # allow a little clock skew, but not years into the future
    return moment <= reference.replace(year=reference.year + 1)


def read_image_date(path: Path) -> tuple[Optional[datetime], str]:
    """Read a capture date from EXIF. Returns (datetime, source)."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None, SOURCE_NONE
            for tag, source in (
                (_EXIF_DATETIME_ORIGINAL, SOURCE_EXIF_ORIGINAL),
                (_EXIF_DATETIME_DIGITIZED, SOURCE_EXIF_DIGITIZED),
                (_EXIF_DATETIME, SOURCE_EXIF_DATETIME),
            ):
                moment = _parse_exif_datetime(exif.get(tag))
                if moment is not None:
                    return moment, source
            # Some cameras store these in the Exif IFD instead.
            try:
                ifd = exif.get_ifd(0x8769)
            except Exception:
                ifd = {}
            for tag, source in (
                (_EXIF_DATETIME_ORIGINAL, SOURCE_EXIF_ORIGINAL),
                (_EXIF_DATETIME_DIGITIZED, SOURCE_EXIF_DIGITIZED),
            ):
                moment = _parse_exif_datetime(ifd.get(tag))
                if moment is not None:
                    return moment, source
    except Exception:
        return None, SOURCE_NONE
    return None, SOURCE_NONE


def parse_video_creation_time(value: object) -> Optional[datetime]:
    """Parse a container creation_time such as 2026-07-21T18:42:10.000000Z."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(normalized)
    except ValueError:
        match = _EXIF_DATE_RE.match(text)
        if not match:
            return None
        try:
            return datetime(*(int(p) for p in match.groups()))  # type: ignore[arg-type]
        except ValueError:
            return None
    if moment.tzinfo is not None:
        # Convert a real UTC offset to local wall time, then drop tzinfo:
        # file names carry no timezone, and we do not invent one.
        moment = moment.astimezone().replace(tzinfo=None)
    return moment


def _filesystem_date(path: Path) -> tuple[Optional[datetime], str]:
    try:
        stat = path.stat()
    except OSError:
        return None, SOURCE_NONE
    created = getattr(stat, "st_birthtime", None)
    if created is None and os.name == "nt":
        created = stat.st_ctime  # on Windows this is the creation time
    if created:
        moment = datetime.fromtimestamp(created)
        if is_plausible(moment):
            return moment, SOURCE_FS_CREATED
    try:
        return datetime.fromtimestamp(stat.st_mtime), SOURCE_FS_MODIFIED
    except (OSError, OverflowError, ValueError):
        return None, SOURCE_NONE


def resolve_media_date(
    path: Path,
    media_type: str = "image",
    video_tags: Optional[dict] = None,
) -> MediaDateResult:
    """Resolve the capture date through the documented fallback chain."""
    warnings: list[str] = []
    candidate: Optional[datetime] = None
    source = SOURCE_NONE

    if media_type == "video":
        raw = (video_tags or {}).get("creation_time")
        parsed = parse_video_creation_time(raw)
        if parsed is not None:
            if is_plausible(parsed):
                candidate, source = parsed, SOURCE_VIDEO_CREATION
            else:
                warnings.append(WARNING_IMPLAUSIBLE)
    else:
        parsed, exif_source = read_image_date(path)
        if parsed is not None:
            if is_plausible(parsed):
                candidate, source = parsed, exif_source
            else:
                warnings.append(WARNING_IMPLAUSIBLE)

    if candidate is None:
        candidate, source = _filesystem_date(path)
        if candidate is not None and not is_plausible(candidate):
            warnings.append(WARNING_IMPLAUSIBLE)
            candidate, source = None, SOURCE_NONE

    return MediaDateResult(
        captured_at=candidate.isoformat(timespec="seconds") if candidate else None,
        date_source=source,
        warnings=warnings,
    )


def date_parts(
    captured_at: Optional[str], date_format: str, time_format: str
) -> dict[str, str]:
    """Render {date} {time} {year} {month} {day} from an ISO timestamp."""
    if not captured_at:
        return {}
    try:
        moment = datetime.fromisoformat(captured_at)
    except ValueError:
        return {}
    return {
        "date": moment.strftime(date_format),
        "time": moment.strftime(time_format),
        "year": moment.strftime("%Y"),
        "month": moment.strftime("%m"),
        "day": moment.strftime("%d"),
    }
