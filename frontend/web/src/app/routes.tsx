import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import { DashboardLayout } from "./layouts/DashboardLayout";
import { HomePage } from "./pages/HomePage";
import { HarvestStatusPage } from "./pages/harvest/HarvestStatusPage";
import { HarvestHistoryPage } from "./pages/harvest/HarvestHistoryPage";
import { ConnectionsSection } from "./pages/harvest/ConnectionsSection";
import { CompileReportPage } from "./pages/CompileReportPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { ActionItemsPage } from "./pages/ActionItemsPage";
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
          { index: true, element: <Navigate to="/build/harvest" replace /> },
          { path: "sources", element: <ConnectionsSection /> },
          { path: "harvest", element: <HarvestStatusPage /> },
          { path: "history", element: <HarvestHistoryPage /> },
          { path: "compile", element: <CompileReportPage /> },
        ],
      },
      { path: "documents", element: <DocumentsPage /> },
      { path: "action-items", element: <ActionItemsPage /> },
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
          { index: true, element: <Navigate to="/build/harvest" replace /> },
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
