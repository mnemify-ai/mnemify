import { useEffect, useState, type RefObject } from "react";

/**
 * True once the element has scrolled into (or near) the viewport, and stays
 * true afterwards — for lazily mounting something heavy exactly once. Falls
 * back to `true` where IntersectionObserver is unavailable.
 */
export function useInView(ref: RefObject<Element | null>, rootMargin = "200px"): boolean {
  const [inView, setInView] = useState(false);
  useEffect(() => {
    if (inView) return;
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setInView(true);
      return;
    }
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setInView(true);
          obs.disconnect();
        }
      },
      { rootMargin },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [ref, rootMargin, inView]);
  return inView;
}
