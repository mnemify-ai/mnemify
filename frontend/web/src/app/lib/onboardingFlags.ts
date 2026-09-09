// Small shared localStorage flags for first-run state on Home. Centralized so
// the interaction hint, the briefing card, and anything else agree on "has the
// user driven the map yet?" without each re-deriving the key.

const TAG_FLAG_KEY = "mnemify.onboarding.firstTagSelected";

/** True once the user has selected any tag on the map at least once. */
export function hasClickedTag(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(TAG_FLAG_KEY) === "1";
  } catch {
    return true;
  }
}

/** Record that the user has now selected a tag (idempotent). */
export function markTagClicked(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TAG_FLAG_KEY, "1");
  } catch {
    /* quota exceeded or storage disabled — silently noop */
  }
}
