import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
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
const ZOOM_STEP = 1.25;

export function PdfPreview({ url, filename }: Props) {
  const [numPages, setNumPages] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [baseWidth, setBaseWidth] = useState<number>(600);
  const [zoom, setZoom] = useState<number>(1);
  const [pageRatio, setPageRatio] = useState<number>(1.414); // height / width, A4 default
  const [err, setErr] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const zoomRef = useRef(zoom);
  const pendingScrollRef = useRef<{ left: number; top: number } | null>(null);
  const dragRef = useRef<{ x: number; y: number; sl: number; st: number; pointerId: number } | null>(null);

  useEffect(() => { zoomRef.current = zoom; }, [zoom]);

  useEffect(() => {
    const handler = () => {
      const el = containerRef.current;
      if (el) setBaseWidth(Math.max(280, el.clientWidth - 16));
    };
    handler();
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, []);

  // Reset zoom + scroll when page or document changes
  useEffect(() => {
    pendingScrollRef.current = { left: 0, top: 0 };
    setZoom(1);
  }, [page, url]);

  // After zoom changes the wrapper size, restore the anchor point so the
  // pixel under the cursor (or the viewport center for button-driven zoom)
  // stays put. Runs before paint to avoid visible jumps.
  useLayoutEffect(() => {
    const pending = pendingScrollRef.current;
    if (pending && stageRef.current) {
      stageRef.current.scrollLeft = pending.left;
      stageRef.current.scrollTop = pending.top;
      pendingScrollRef.current = null;
    }
  }, [zoom, baseWidth, pageRatio]);

  // Native non-passive wheel listener — React's synthetic wheel events are
  // passive, so preventDefault() on trackpad pinch wouldn't fire otherwise.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const handler = (e: WheelEvent) => {
      // macOS trackpad pinch reports ctrlKey=true. We only intercept when a
      // modifier is held, so plain scroll wheel still pans the document.
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();

      const rect = stage.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const current = zoomRef.current;
      const factor = Math.exp(-e.deltaY * 0.01);
      const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current * factor));
      if (next === current) return;
      const ratio = next / current;
      const contentX = stage.scrollLeft + px;
      const contentY = stage.scrollTop + py;
      pendingScrollRef.current = {
        left: contentX * ratio - px,
        top: contentY * ratio - py,
      };
      setZoom(next);
    };
    stage.addEventListener("wheel", handler, { passive: false });
    return () => stage.removeEventListener("wheel", handler);
  }, []);

  const zoomByFactor = useCallback((factor: number) => {
    const stage = stageRef.current;
    if (!stage) return;
    const current = zoomRef.current;
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current * factor));
    if (next === current) return;
    const px = stage.clientWidth / 2;
    const py = stage.clientHeight / 2;
    const ratio = next / current;
    const contentX = stage.scrollLeft + px;
    const contentY = stage.scrollTop + py;
    pendingScrollRef.current = {
      left: contentX * ratio - px,
      top: contentY * ratio - py,
    };
    setZoom(next);
  }, []);

  const resetZoom = useCallback(() => {
    pendingScrollRef.current = { left: 0, top: 0 };
    setZoom(1);
  }, []);

  // Click-and-drag panning (mouse only; touch users get native scroll).
  function onPointerDown(e: React.PointerEvent) {
    if (e.pointerType !== "mouse" || e.button !== 0) return;
    const stage = stageRef.current;
    if (!stage) return;
    if (stage.scrollWidth <= stage.clientWidth && stage.scrollHeight <= stage.clientHeight) return;
    dragRef.current = {
      x: e.clientX,
      y: e.clientY,
      sl: stage.scrollLeft,
      st: stage.scrollTop,
      pointerId: e.pointerId,
    };
    stage.setPointerCapture(e.pointerId);
    setDragging(true);
  }

  function onPointerMove(e: React.PointerEvent) {
    const stage = stageRef.current;
    const drag = dragRef.current;
    if (!stage || !drag) return;
    stage.scrollLeft = drag.sl - (e.clientX - drag.x);
    stage.scrollTop = drag.st - (e.clientY - drag.y);
  }

  function onPointerUp(e: React.PointerEvent) {
    const stage = stageRef.current;
    if (stage && stage.hasPointerCapture(e.pointerId)) stage.releasePointerCapture(e.pointerId);
    dragRef.current = null;
    setDragging(false);
  }

  const isZoomed = zoom > 1.001;
  const displayWidth = baseWidth * zoom;
  const displayHeight = baseWidth * pageRatio * zoom;

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
        <Button size="sm" variant="ghost" onClick={() => zoomByFactor(1 / ZOOM_STEP)} title="Verkleinern" disabled={zoom <= MIN_ZOOM + 0.001}>
          <ZoomOut className="h-3.5 w-3.5" />
        </Button>
        <span className="font-mono text-muted-foreground w-12 text-center">{Math.round(zoom * 100)}%</span>
        <Button size="sm" variant="ghost" onClick={() => zoomByFactor(ZOOM_STEP)} title="Vergrößern" disabled={zoom >= MAX_ZOOM - 0.001}>
          <ZoomIn className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="ghost" onClick={resetZoom} title="An Breite anpassen" disabled={!isZoomed}>
          <Maximize2 className="h-3.5 w-3.5" />
        </Button>
        <div className="flex-1" />
        <a href={url} download={filename}>
          <Button size="sm" variant="ghost" title="Herunterladen"><Download className="h-3.5 w-3.5" /></Button>
        </a>
        <a href={url} target="_blank" rel="noreferrer">
          <Button size="sm" variant="ghost" title="In neuem Tab öffnen"><ExternalLink className="h-3.5 w-3.5" /></Button>
        </a>
      </div>
      <div
        ref={stageRef}
        className="flex-1 overflow-auto select-none"
        style={{
          cursor: isZoomed ? (dragging ? "grabbing" : "grab") : "default",
          overscrollBehavior: "contain",
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {err ? (
          <div className="text-sm text-muted-foreground p-6 text-center space-y-2">
            <FileX className="h-6 w-6 mx-auto opacity-50" />
            <p>PDF konnte nicht angezeigt werden: {err}</p>
            <a className="text-primary underline" href={url} target="_blank" rel="noreferrer">In neuem Tab öffnen</a>
          </div>
        ) : (
          <div
            className="mx-auto my-3"
            style={{ width: displayWidth, height: displayHeight, position: "relative" }}
          >
            <div
              style={{
                transform: `scale(${zoom})`,
                transformOrigin: "0 0",
                position: "absolute",
                top: 0,
                left: 0,
                width: baseWidth,
                willChange: "transform",
              }}
            >
              <Document
                file={url}
                onLoadSuccess={({ numPages: n }) => { setNumPages(n); setErr(null); }}
                onLoadError={(e) => setErr(e?.message || "Laden fehlgeschlagen")}
                loading={<div className="text-sm text-muted-foreground p-6">PDF wird geladen…</div>}
                error={<div className="text-sm text-destructive p-6">Fehler beim Laden.</div>}
              >
                <Page
                  pageNumber={page}
                  width={baseWidth}
                  renderAnnotationLayer={false}
                  renderTextLayer={false}
                  onLoadSuccess={(p) => {
                    if (p.width > 0) setPageRatio(p.height / p.width);
                  }}
                />
              </Document>
            </div>
          </div>
        )}
      </div>
      <div className="px-2 py-1 border-t border-border text-[10px] text-muted-foreground text-center">
        Strg/Cmd + Scrollen oder Pinch zum Zoomen · Beim Zoom ziehen zum Verschieben
      </div>
    </div>
  );
}
