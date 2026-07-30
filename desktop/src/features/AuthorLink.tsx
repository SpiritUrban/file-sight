import { ExternalLink, Sparkles } from "lucide-react";

import { useTranslation } from "@/lib/i18n";
import { openExternal } from "@/lib/platform";
import { PRODUCT_METADATA } from "@/lib/productMetadata";

/**
 * "More by <author>" — a navigation item, not a promo block.
 *
 * It sits next to Settings: always on screen, never in the working area,
 * and it cannot interrupt anything. The measured parameters that keep it
 * unobtrusive: 11px text, muted grey, transparent background, colour only
 * on the icon, and the external-link arrow appearing on hover alone. No
 * badges, no animation, no toast, no modal.
 */
export function AuthorLink() {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={() => void openExternal(PRODUCT_METADATA.authorUrl)}
      title={t("More projects and services by {author}", {
        author: PRODUCT_METADATA.author,
      })}
      className="group flex items-center gap-2 rounded-lg px-2 py-2 text-[11px] font-medium
                 text-slate-500 transition-all hover:bg-slate-100 hover:text-slate-800"
    >
      <Sparkles
        className="h-3.5 w-3.5 shrink-0 text-indigo-400/70 group-hover:text-indigo-500"
        aria-hidden
      />
      <span className="truncate">
        {t("More by {author}", { author: PRODUCT_METADATA.author })}
      </span>
      <ExternalLink
        className="h-3 w-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-60"
        aria-hidden
      />
    </button>
  );
}
