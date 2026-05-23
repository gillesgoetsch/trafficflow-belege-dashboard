import { useEffect, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { ChevronLeft, ChevronRight, Download, ExternalLink, FileX } from "lucide-react";
import { Button } from "../ui/button";
// Vite-bundled PDF.js worker; ?url returns a hashed asset path so we don't
// depend on a CDN and the worker can't drift from the main bundle's version.
// @ts-ignore — vite-only suffix
import pdfWorkerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerSrc;

interface Props {
  url: string;
  filename: string;
  containerWidth?: number;
}

export function PdfPreview({ url, filename, containerWidth }: Props) {
  const [numPages, setNumPages] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [width, setWidth] = useState<number>(containerWidth ?? 600);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const handler = () => {
      const el = document.getElementById("pdfpv");
      if (el) setWidth(Math.max(280, el.clientWidth - 16));
    };
    handler();
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, []);

  return (
    <div id="pdfpv" className="h-full w-full flex flex-col bg-muted/30">
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
        <div className="flex-1" />
        <a href={url} download={filename}>
          <Button size="sm" variant="ghost" title="Download"><Download className="h-3.5 w-3.5" /></Button>
        </a>
        <a href={url} target="_blank" rel="noreferrer">
          <Button size="sm" variant="ghost" title="Open in new tab"><ExternalLink className="h-3.5 w-3.5" /></Button>
        </a>
      </div>
      <div className="flex-1 overflow-auto flex items-start justify-center py-3">
        {err ? (
          <div className="text-sm text-muted-foreground p-6 text-center space-y-2">
            <FileX className="h-6 w-6 mx-auto opacity-50" />
            <p>Couldn't render PDF: {err}</p>
            <a className="text-primary underline" href={url} target="_blank" rel="noreferrer">Open in a new tab</a>
          </div>
        ) : (
          <Document
            file={url}
            onLoadSuccess={({ numPages: n }) => { setNumPages(n); setErr(null); }}
            onLoadError={(e) => setErr(e?.message || "load failed")}
            loading={<div className="text-sm text-muted-foreground p-6">Loading PDF…</div>}
            error={<div className="text-sm text-destructive p-6">Failed to load.</div>}
          >
            <Page pageNumber={page} width={width} renderAnnotationLayer={false} renderTextLayer={false} />
          </Document>
        )}
      </div>
    </div>
  );
}
