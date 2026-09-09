import { Navigate, useLocation } from "react-router-dom";

/** Legacy /connections and /settings/connections deep links → /build/sources,
 *  preserving ?connect=… query and #hash. */
export function ConnectionsRedirect() {
  const { search, hash } = useLocation();
  return <Navigate to={{ pathname: "/build/sources", search, hash }} replace />;
}
