import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { ChevronLeft, ChevronRight, Download, ExternalLink, FileX, ZoomIn, ZoomOut, Maximize2 } from "lucide-react";
import { Button } from "../ui/button";
// @ts-ignore — vite ?url suffix
import pdfWorkerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerSrc;

interface Props {
  url: string;
  filename: string;
}

const MIN_ZOOM = 1;
const MAX_ZOOM = 6;

export function PdfPreview({ url, filename }: Props) {
  const [numPages, setNumPages] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [baseWidth, setBaseWidth] = useState<number>(600);
  const [zoom, setZoom] = useState<number>(1);          // 1 = fit-to-width
  const [origin, setOrigin] = useState<{ x: number; y: number }>({ x: 50, y: 50 }); // percent
  const [err, setErr] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handler = () => {
      const el = containerRef.current;
      if (el) setBaseWidth(Math.max(280, el.clientWidth - 16));
    };
    handler();
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, []);

  // Reset zoom when page changes
  useEffect(() => { setZoom(1); }, [page, url]);

  function onWheel(e: React.WheelEvent) {
    if (!e.ctrlKey && !e.metaKey && Math.abs(e.deltaY) < 8) return; // don't hijack normal scroll unless decisively
    e.preventDefault();
    const stage = stageRef.current;
    if (!stage) return;
    const rect = stage.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;
    setOrigin({ x, y });
    setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z * (e.deltaY < 0 ? 1.15 : 0.87))));
  }

  return (
    <div ref={containerRef} className="h-full w-full flex flex-col bg-muted/30">
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border text-xs">
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
          <ChevronLeft className="h-3.5 w-3.5" />
        </Button>
        <span className="font-mono text-muted-foreground">
          {page} / {numPages || "?"}
        </span>
        <Button size="sm" variant="ghost" disabled={page >= numPages} onClick={() => setPage((p) => p + 1)}>
          <ChevronRight className="h-3.5 w-3.5" />
        </Button>
        <div className="mx-2 h-4 w-px bg-border" />
        <Button size="sm" variant="ghost" onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z * 0.8))} title="Zoom out">
          <ZoomOut className="h-3.5 w-3.5" />
        </Button>
        <span className="font-mono text-muted-foreground w-12 text-center">{Math.round(zoom * 100)}%</span>
        <Button size="sm" variant="ghost" onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z * 1.25))} title="Zoom in">
          <ZoomIn className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="ghost" onClick={() => { setZoom(1); setOrigin({ x: 50, y: 50 }); }} title="Fit width">
          <Maximize2 className="h-3.5 w-3.5" />
        </Button>
        <div className="flex-1" />
        <a href={url} download={filename}>
          <Button size="sm" variant="ghost" title="Download"><Download className="h-3.5 w-3.5" /></Button>
        </a>
        <a href={url} target="_blank" rel="noreferrer">
          <Button size="sm" variant="ghost" title="Open in new tab"><ExternalLink className="h-3.5 w-3.5" /></Button>
        </a>
      </div>
      <div
        ref={stageRef}
        className="flex-1 overflow-auto flex items-start justify-center py-3 select-none"
        onWheel={onWheel}
      >
        {err ? (
          <div className="text-sm text-muted-foreground p-6 text-center space-y-2">
            <FileX className="h-6 w-6 mx-auto opacity-50" />
            <p>Couldn't render PDF: {err}</p>
            <a className="text-primary underline" href={url} target="_blank" rel="noreferrer">Open in a new tab</a>
          </div>
        ) : (
          <div
            style={{
              transform: `scale(${zoom})`,
              transformOrigin: `${origin.x}% ${origin.y}%`,
              transition: "transform 60ms ease-out",
              willChange: "transform",
            }}
          >
            <Document
              file={url}
              onLoadSuccess={({ numPages: n }) => { setNumPages(n); setErr(null); }}
              onLoadError={(e) => setErr(e?.message || "load failed")}
              loading={<div className="text-sm text-muted-foreground p-6">Loading PDF…</div>}
              error={<div className="text-sm text-destructive p-6">Failed to load.</div>}
            >
              <Page pageNumber={page} width={baseWidth} renderAnnotationLayer={false} renderTextLayer={false} />
            </Document>
          </div>
        )}
      </div>
      <div className="px-2 py-1 border-t border-border text-[10px] text-muted-foreground text-center">
        Scroll-wheel to zoom on the cursor · click <kbd className="px-1 rounded bg-muted">fit</kbd> to reset
      </div>
    </div>
  );
}
