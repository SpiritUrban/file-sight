import { Film, ImageOff } from "lucide-react";
import { useEffect, useState } from "react";

import { useThumbnail } from "@/hooks/useThumbnail";
import type { ScanFileEntry } from "@/types";

interface ThumbnailProps {
  entry: ScanFileEntry;
  size?: number;
  className?: string;
}

/**
 * Lazily requests a cached thumbnail from the worker; falls back to an
 * icon so a missing preview never blocks the row.
 */
export function Thumbnail({ entry, size = 40, className = "" }: ThumbnailProps) {
  const { url, failed, request } = useThumbnail(entry.original_path, size);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (visible) request();
  }, [visible, request]);

  const box = { width: size, height: size };

  return (
    <div
      ref={(node) => {
        if (!node || visible) return;
        // Only ask for pixels once the row is actually on screen.
        const observer = new IntersectionObserver((entries) => {
          if (entries.some((e) => e.isIntersecting)) {
            setVisible(true);
            observer.disconnect();
          }
        });
        observer.observe(node);
      }}
      style={box}
      className={`flex shrink-0 items-center justify-center overflow-hidden rounded bg-slate-100 ${className}`}
    >
      {url && !failed ? (
        <img
          src={url}
          alt=""
          className="h-full w-full object-cover"
          onError={() => setVisible(true)}
        />
      ) : entry.media_type === "video" ? (
        <Film className="h-1/2 w-1/2 text-slate-400" aria-hidden />
      ) : (
        <ImageOff className="h-1/2 w-1/2 text-slate-300" aria-hidden />
      )}
    </div>
  );
}
