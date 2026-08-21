"use client";

import { useCallback, useEffect, useState, type RefObject } from "react";

/** Below this much unseen transcript, the reader is treated as "at the bottom". */
const AT_BOTTOM_THRESHOLD_PX = 160;

/**
 * Track whether the transcript has content below the fold.
 *
 * The turn opens by pinning the new question near the top, which is what we
 * want — the transcript deliberately does NOT chase the stream. The cost is
 * that a long answer can grow past the fold silently, so this reports when
 * that has happened and offers the way back, the same contract ChatGPT uses.
 *
 * Watching the stack as well as the scroller matters: while text streams the
 * content grows without ever firing a scroll event.
 */
export function useJumpToLatest(
  scrollRef: RefObject<HTMLDivElement | null>,
  stackRef: RefObject<HTMLDivElement | null>,
) {
  const [hasMoreBelow, setHasMoreBelow] = useState(false);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;

    const update = () => {
      const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      setHasMoreBelow(distance > AT_BOTTOM_THRESHOLD_PX);
    };

    update();
    scroller.addEventListener("scroll", update, { passive: true });

    const stack = stackRef.current;
    let observer: ResizeObserver | null = null;
    if (stack && typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(update);
      observer.observe(stack);
    }

    return () => {
      scroller.removeEventListener("scroll", update);
      observer?.disconnect();
    };
  }, [scrollRef, stackRef]);

  const jumpToLatest = useCallback(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    scroller.scrollTo({
      top: scroller.scrollHeight,
      behavior: reducedMotion ? "auto" : "smooth",
    });
  }, [scrollRef]);

  return { hasMoreBelow, jumpToLatest };
}
