import { useEffect } from "react";
import type { RefObject } from "react";

export function useDismissibleDetails(
  detailsRef: RefObject<HTMLDetailsElement | null>,
  onDismiss?: () => void,
) {
  useEffect(() => {
    const closeDetails = () => {
      const details = detailsRef.current;
      if (!details?.open) return;
      details.open = false;
      onDismiss?.();
    };

    const onPointerDown = (event: PointerEvent) => {
      const details = detailsRef.current;
      if (!details?.open) return;
      if (event.target instanceof Node && details.contains(event.target))
        return;
      closeDetails();
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeDetails();
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [detailsRef, onDismiss]);
}
