import { useCallback } from "react";
import { useNavigate, type NavigateOptions, type To } from "react-router-dom";
import { useDemo } from "../demo/DemoContext";
import { toSamplePath } from "../demo/samplePaths";

/**
 * `useNavigate` for components the sample workspace reuses: inside /sample,
 * absolute app paths it can show are kept inside it (see samplePaths.ts).
 * Outside the sample it is exactly `useNavigate`.
 */
export function useAppNavigate(): (to: To | number, options?: NavigateOptions) => void {
  const navigate = useNavigate();
  const demo = useDemo();
  return useCallback(
    (to: To | number, options?: NavigateOptions) => {
      if (typeof to === "number") {
        navigate(to);
        return;
      }
      if (demo && typeof to === "string") {
        navigate(toSamplePath(to) ?? to, options);
        return;
      }
      navigate(to, options);
    },
    [navigate, demo],
  );
}
