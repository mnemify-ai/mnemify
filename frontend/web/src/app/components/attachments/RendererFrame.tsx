// Suspense + error boundary wrapper around the dispatched renderer.
//
// A single malformed file (corrupt PDF, exotic XLSX) must not tear down the
// modal or the page. This frame catches render-time crashes and shows a
// themed ErrorState with Retry + Download fallbacks.

import { Component, Suspense, type ReactNode } from "react";
import { Download } from "lucide-react";
import { ErrorState } from "../ui/ErrorState";
import { Skeleton } from "../ui/Skeleton";
import { Button } from "../ui/Button";

interface FrameProps {
  children: ReactNode;
  downloadUrl: string;
  filename: string;
}

interface FrameState {
  error: Error | null;
  retries: number;
}

export class RendererFrame extends Component<FrameProps, FrameState> {
  state: FrameState = { error: null, retries: 0 };

  static getDerivedStateFromError(error: Error): Partial<FrameState> {
    return { error };
  }

  retry = () => {
    // Bumping `retries` re-keys the inner subtree so its Suspense restarts
    // and any failed dynamic import is re-attempted.
    this.setState((s) => ({ error: null, retries: s.retries + 1 }));
  };

  triggerDownload = () => {
    const a = document.createElement("a");
    a.href = this.props.downloadUrl;
    a.download = this.props.filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  render() {
    if (this.state.error) {
      return (
        <div className="flex-1 min-h-0 flex items-center justify-center overflow-y-auto">
          <ErrorState
            title="Can't preview this file"
            description={
              <>
                Something went wrong rendering{" "}
                <span className="font-mono">{this.props.filename}</span>. You
                can still download the original.
              </>
            }
            onRetry={this.retry}
            action={
              <Button
                variant="secondary"
                size="md"
                type="button"
                onClick={this.triggerDownload}
              >
                <Download size={14} strokeWidth={1.75} aria-hidden />
                Download
              </Button>
            }
          />
        </div>
      );
    }
    return (
      <Suspense key={this.state.retries} fallback={<RendererSkeleton />}>
        {this.props.children}
      </Suspense>
    );
  }
}

function RendererSkeleton() {
  return (
    <div className="flex-1 min-h-0 flex items-center justify-center p-8">
      <Skeleton variant="block" aspectRatio="4/5" width="min(560px, 80%)" />
    </div>
  );
}
