import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { queryClient } from "./lib/query";
import { Toaster } from "./components/ui/toaster";
import "./index.css";

// Theme is applied by the inline script in index.html (flicker-free).
// Subscribe to system theme changes so users who haven't picked explicitly
// follow their OS automatically.
{
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const apply = () => {
    const stored = localStorage.getItem("belege_theme");
    const explicit = stored && stored !== "system" ? stored : null;
    const want = explicit ?? (mq.matches ? "dark" : "light");
    document.documentElement.classList.toggle("dark", want === "dark");
  };
  mq.addEventListener?.("change", apply);
  apply();
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
        <Toaster />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
