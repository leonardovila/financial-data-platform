// ──────────────────────────────────────────────────────────────────────────────
// FRONT-013 (PL_03): InfoTooltip — click-toggle help icon.
//
// Why ad-hoc and not @radix-ui/react-popover or floating-ui?
//   We need ~150 LOC of behavior, no library, no extra bundle weight, brutalist
//   look matching the rest of the design. Positioning is computed once on open
//   via getBoundingClientRect; the popup uses position:fixed so it escapes any
//   parent overflow:hidden / overflow:auto (e.g. the mobile MetricsGrid scroll
//   container, FundamentalsBar overflow-x-auto).
//
// Viewport-aware placement:
//   - HORIZONTAL: centered on the button, clamped to [margin, vp.w - width - margin]
//     so it never overflows left/right edges.
//   - VERTICAL: picks whichever side (above/below) has MORE room. Sets max-height
//     to that available space, then internal `overflow-y: auto` ensures very long
//     texts scroll inside the popup instead of bleeding off the screen. This is
//     what fixes the bug where the Momentum-category text was getting cut off at
//     the bottom of mobile / short desktop windows.
//
// Color choice (yellow vs neon green):
//   - Yellow #ffcc00 is the universal info-affordance color (Stack Overflow,
//     Bootstrap, browser address bar tooltips). Users instantly read "yellow ?"
//     as "click for an explanation".
//   - Green is already overloaded in this design (positive deltas, live pulse,
//     chart up-candles, search highlights). Adding another green meaning would
//     dilute the "important live thing" signal.
//
// Behavior:
//   - Click ? → toggle popup.
//   - Click outside / Escape / scroll / resize → close.
// ──────────────────────────────────────────────────────────────────────────────

import { useState, useRef, useEffect, useCallback } from "react";

interface InfoTooltipProps {
  text: string;
  /** sm = 16px (default, for row labels). md = 18px (for category titles). */
  size?: "sm" | "md";
  /** Optional aria-label override. Defaults to "What is this?". */
  ariaLabel?: string;
}

const POP_WIDTH = 264;
const POP_MARGIN = 8;
const MIN_HEIGHT = 80;

type Placement = "below" | "above";

interface Coords {
  left: number;
  top?: number;
  bottom?: number;
  maxHeight: number;
  placement: Placement;
}

export default function InfoTooltip({
  text,
  size = "sm",
  ariaLabel = "What is this?",
}: InfoTooltipProps) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<Coords | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  const computeCoords = useCallback(() => {
    const btn = btnRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const vpW = window.innerWidth;
    const vpH = window.innerHeight;

    // ── Horizontal: center on button, clamp to viewport ──
    let left = rect.left + rect.width / 2 - POP_WIDTH / 2;
    left = Math.max(POP_MARGIN, Math.min(left, vpW - POP_WIDTH - POP_MARGIN));

    // ── Vertical: pick the side with more room ──
    const spaceBelow = vpH - rect.bottom - POP_MARGIN;
    const spaceAbove = rect.top - POP_MARGIN;

    // Prefer below; flip to above only if below is too small AND above has more room.
    const placement: Placement =
      spaceBelow >= MIN_HEIGHT || spaceBelow >= spaceAbove ? "below" : "above";

    if (placement === "below") {
      setCoords({
        left,
        top: rect.bottom + 6,
        maxHeight: Math.max(MIN_HEIGHT, spaceBelow - 6),
        placement,
      });
    } else {
      // Anchor by bottom edge so we don't need to know the popup's rendered height.
      setCoords({
        left,
        bottom: vpH - rect.top + 6,
        maxHeight: Math.max(MIN_HEIGHT, spaceAbove - 6),
        placement,
      });
    }
  }, []);

  // Recompute on open
  useEffect(() => {
    if (open) computeCoords();
  }, [open, computeCoords]);

  // Outside click / Escape / scroll / resize → close
  useEffect(() => {
    if (!open) return;

    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (
        btnRef.current &&
        !btnRef.current.contains(target) &&
        popRef.current &&
        !popRef.current.contains(target)
      ) {
        setOpen(false);
      }
    }

    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }

    function handleScrollOrResize() {
      // popup is fixed-position, would otherwise drift away from anchor
      setOpen(false);
    }

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    window.addEventListener("scroll", handleScrollOrResize, true);
    window.addEventListener("resize", handleScrollOrResize);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
      window.removeEventListener("scroll", handleScrollOrResize, true);
      window.removeEventListener("resize", handleScrollOrResize);
    };
  }, [open]);

  const sizeCls =
    size === "md"
      ? "w-[18px] h-[18px] text-[11px]"
      : "w-4 h-4 text-[10px]";

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className={[
          sizeCls,
          "inline-flex items-center justify-center rounded-full",
          "border border-[var(--color-yellow)] text-[var(--color-yellow)]",
          "font-bold leading-none shrink-0 cursor-pointer",
          "hover:bg-[var(--color-yellow)] hover:text-black",
          "transition-colors",
          open ? "bg-[var(--color-yellow)] text-black" : "",
        ].join(" ")}
        aria-label={ariaLabel}
        aria-expanded={open}
      >
        ?
      </button>

      {open && coords && (
        <div
          ref={popRef}
          role="tooltip"
          style={{
            left: coords.left,
            top: coords.top,
            bottom: coords.bottom,
            width: POP_WIDTH,
            maxHeight: coords.maxHeight,
          }}
          className={[
            "fixed z-[100] p-3",
            "bg-[#0a0c18] border border-[var(--color-yellow)]",
            "text-[var(--color-text)] text-xs leading-relaxed",
            "shadow-xl shadow-black/80",
            "font-mono",
            "overflow-y-auto",
          ].join(" ")}
        >
          {text}
        </div>
      )}
    </>
  );
}
