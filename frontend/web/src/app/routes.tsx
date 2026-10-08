import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import { DashboardLayout } from "./layouts/DashboardLayout";
import { HomePage } from "./pages/HomePage";
import { HarvestStatusPage } from "./pages/harvest/HarvestStatusPage";
import { HarvestHistoryPage } from "./pages/harvest/HarvestHistoryPage";
import { ConnectionsSection } from "./pages/harvest/ConnectionsSection";
import { CompileReportPage } from "./pages/CompileReportPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { ActionItemsPage } from "./pages/ActionItemsPage";
import { RegionsIndexPage } from "./pages/regions/RegionsIndexPage";
import { RegionWorkspaceLayout, UnassignedRegionRoute } from "./pages/regions/RegionWorkspaceLayout";
import { RegionOverviewTab } from "./pages/regions/RegionOverviewTab";
import { RegionMemoryTab } from "./pages/regions/RegionMemoryTab";
import { RegionActivityTab } from "./pages/regions/RegionActivityTab";
import { SettingsLayout } from "./pages/SettingsLayout";
import { GeneralSection } from "./pages/settings/GeneralSection";
import { DataSection } from "./pages/settings/DataSection";
import { AiModelsSection } from "./pages/settings/AiModelsSection";
import { AuditSection } from "./pages/settings/AuditSection";
import { SchedulesSection } from "./pages/settings/SchedulesSection";
import { ConnectionsRedirect } from "./components/ConnectionsRedirect";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <DashboardLayout />,
    children: [
      { index: true, element: <HomePage /> },
      {
        // Build — the pipeline in one place: Sources → Harvest → Compile.
        path: "build",
        element: <Outlet />,
        children: [
          // Land on Sources: it is step one, and "where are my sources?" is
          // the question that brings people to this tab in the first place.
          { index: true, element: <Navigate to="/build/sources" replace /> },
          { path: "sources", element: <ConnectionsSection /> },
          { path: "harvest", element: <HarvestStatusPage /> },
          { path: "history", element: <HarvestHistoryPage /> },
          { path: "compile", element: <CompileReportPage /> },
        ],
      },
      { path: "documents", element: <DocumentsPage /> },
      { path: "action-items", element: <ActionItemsPage /> },
      {
        // Region workspaces — one per region at any level of the tree.
        path: "regions",
        children: [
          { index: true, element: <RegionsIndexPage /> },
          { path: "unassigned/:regionKey", element: <UnassignedRegionRoute /> },
          {
            path: ":regionId",
            element: <RegionWorkspaceLayout />,
            children: [
              { index: true, element: <RegionOverviewTab /> },
              { path: "memory", element: <RegionMemoryTab /> },
              { path: "activity", element: <RegionActivityTab /> },
            ],
          },
        ],
      },
      {
        path: "settings",
        element: <SettingsLayout />,
        children: [
          { index: true, element: <GeneralSection /> },
          { path: "ai", element: <AiModelsSection /> },
          // Legacy /settings/compile → the AI & Models section it merged into.
          { path: "compile", element: <Navigate to="/settings/ai" replace /> },
          // Legacy /settings/connections → /build/sources.
          { path: "connections", element: <ConnectionsRedirect /> },
          { path: "data", element: <DataSection /> },
          { path: "audit", element: <AuditSection /> },
          { path: "schedules", element: <SchedulesSection /> },
        ],
      },
      // Legacy routes from the pre-Build IA — permanent redirects.
      {
        path: "harvest",
        children: [
          // Land on Sources: it is step one, and "where are my sources?" is
          // the question that brings people to this tab in the first place.
          { index: true, element: <Navigate to="/build/sources" replace /> },
          { path: "connections", element: <Navigate to="/build/sources" replace /> },
          { path: "history", element: <Navigate to="/build/history" replace /> },
          { path: "documents", element: <Navigate to="/documents" replace /> },
        ],
      },
      { path: "compile", element: <Navigate to="/build/compile" replace /> },
      { path: "connections", element: <ConnectionsRedirect /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
