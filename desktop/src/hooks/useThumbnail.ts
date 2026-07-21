import { useCallback, useRef, useState } from "react";

import { useAppStore } from "@/stores/appStore";

/** Cache across component remounts so scrolling does not re-request. */
const cache = new Map<string, string | null>();

/**
 * `convertFileSrc` turns a local path into an asset: URL the webview may
 * load. It only exists inside Tauri, so it is resolved lazily and tests
 * fall back to the raw path.
 */
async function toAssetUrl(path: string): Promise<string> {
  try {
    const core = await import("@tauri-apps/api/core");
    return core.convertFileSrc(path);
  } catch {
    return path;
  }
}

export function useThumbnail(path: string, size: number) {
  const key = `${path}|${size}`;
  const [url, setUrl] = useState<string | null>(cache.get(key) ?? null);
  const [failed, setFailed] = useState(false);
  const inFlight = useRef(false);

  const request = useCallback(async () => {
    if (inFlight.current) return;
    if (cache.has(key)) {
      const cached = cache.get(key) ?? null;
      setUrl(cached);
      setFailed(cached === null);
      return;
    }
    const client = useAppStore.getState().client;
    if (!client) return;
    inFlight.current = true;
    try {
      const data = (await client.request("make_thumbnail", {
        path,
        size,
      })) as { thumbnail: string | null };
      const resolved = data.thumbnail ? await toAssetUrl(data.thumbnail) : null;
      cache.set(key, resolved);
      setUrl(resolved);
      setFailed(resolved === null);
    } catch {
      cache.set(key, null);
      setFailed(true);
    } finally {
      inFlight.current = false;
    }
  }, [key, path, size]);

  return { url, failed, request };
}

export function clearThumbnailCache(): void {
  cache.clear();
}
