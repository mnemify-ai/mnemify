import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";

import { router } from "./app/routes";
import { queryClient } from "./app/lib/queryClient";
import { MapDataProvider } from "./app/data/MapDataProvider";
import { TooltipProvider } from "./app/components/ui/Tooltip";
import { ThemedToaster } from "./app/components/ThemedToaster";

import "./app/theme/index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <MapDataProvider>
        <TooltipProvider delayDuration={200}>
          <RouterProvider router={router} />
          <ThemedToaster />
        </TooltipProvider>
      </MapDataProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
