import { useEffect, useState } from "react";
import { ByTheNumbers } from "./pages/ByTheNumbers";
import { fetchManifest, type Manifest } from "./db/duckdb";

type ViewId = "numbers" | "explorer" | "biocviews" | "impact" | "grants" | "growth";

const NAV: { id: ViewId; label: string; ready: boolean }[] = [
  { id: "numbers", label: "By the Numbers", ready: true },
  { id: "explorer", label: "Explorer", ready: false },
  { id: "biocviews", label: "biocViews", ready: false },
  { id: "impact", label: "Impact", ready: false },
  { id: "grants", label: "Grants", ready: false },
  { id: "growth", label: "Growth", ready: false },
];

function ComingSoon({ label }: { label: string }) {
  return (
    <div className="mx-auto max-w-2xl px-6 py-24 text-center text-slate-500">
      <div className="text-lg font-medium text-slate-700">{label}</div>
      <p className="mt-2 text-sm">This view is on the way.</p>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<ViewId>("numbers");
  const [manifest, setManifest] = useState<Manifest | null>(null);

  useEffect(() => {
    fetchManifest().then(setManifest).catch(() => setManifest(null));
  }, []);

  const active = NAV.find((n) => n.id === view)!;

  return (
    <div className="min-h-full bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-6 py-3">
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold text-slate-900">Bioconductor</span>
            <span className="text-lg font-light text-bioc-600">Intelligence</span>
          </div>
          <nav className="flex flex-wrap gap-1 text-sm">
            {NAV.map((n) => (
              <button
                key={n.id}
                onClick={() => setView(n.id)}
                className={`rounded-md px-3 py-1.5 font-medium transition ${
                  view === n.id
                    ? "bg-bioc-50 text-bioc-700"
                    : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                }`}
              >
                {n.label}
                {!n.ready && <span className="ml-1 text-[10px] text-slate-400">soon</span>}
              </button>
            ))}
          </nav>
          <div className="ml-auto text-xs text-slate-400">
            {manifest ? `snapshot ${manifest.snapshot}` : ""}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        {active.id === "numbers" ? <ByTheNumbers /> : <ComingSoon label={active.label} />}
      </main>

      <footer className="mx-auto max-w-6xl px-6 py-8 text-xs text-slate-400">
        Zero-backend SPA — DuckDB-WASM over prebuilt Parquet marts. Enrichment sourced read-only
        from cdsci-lake. Source:{" "}
        <a
          className="text-bioc-600 hover:underline"
          href="https://github.com/seandavi/bioc-intelligence"
        >
          seandavi/bioc-intelligence
        </a>
        .
      </footer>
    </div>
  );
}
