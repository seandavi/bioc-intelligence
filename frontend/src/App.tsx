import { useEffect, useState } from "react";
import { Link, useRoute } from "./lib/router";
import { ByTheNumbers } from "./pages/ByTheNumbers";
import { Explorer, PackagePage } from "./pages/Explorer";
import { ImpactLeaderboard } from "./pages/ImpactLeaderboard";
import { BiocViews } from "./pages/BiocViews";
import { Grants } from "./pages/Grants";
import { Growth } from "./pages/Growth";
import { fetchManifest, type Manifest } from "./db/duckdb";

const NAV = [
  { id: "numbers", label: "By the Numbers" },
  { id: "explorer", label: "Explorer" },
  { id: "biocviews", label: "biocViews" },
  { id: "impact", label: "Impact" },
  { id: "grants", label: "Grants" },
  { id: "growth", label: "Growth" },
];

export default function App() {
  const route = useRoute();
  const [manifest, setManifest] = useState<Manifest | null>(null);

  useEffect(() => {
    fetchManifest().then(setManifest).catch(() => setManifest(null));
  }, []);

  // Unknown or empty routes render By the Numbers; #/package/<name> highlights no tab.
  const active =
    route.view === "package" ? "" : NAV.some((n) => n.id === route.view) ? route.view : "numbers";

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
              <Link
                key={n.id}
                view={n.id}
                className={`rounded-md px-3 py-1.5 font-medium transition ${
                  active === n.id
                    ? "bg-bioc-50 text-bioc-700"
                    : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                }`}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto text-xs text-slate-400">
            {manifest ? `snapshot ${manifest.snapshot}` : ""}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        {route.view === "explorer" ? (
          <Explorer />
        ) : route.view === "package" && route.arg ? (
          <PackagePage name={route.arg} />
        ) : route.view === "impact" ? (
          <ImpactLeaderboard />
        ) : route.view === "biocviews" ? (
          <BiocViews />
        ) : route.view === "grants" ? (
          <Grants />
        ) : route.view === "growth" ? (
          <Growth />
        ) : (
          <ByTheNumbers />
        )}
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
