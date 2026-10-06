import { useEffect, useState } from "react";
import { Link, useRoute } from "./lib/router";
import { ByTheNumbers } from "./pages/ByTheNumbers";
import { Explorer, PackagePage } from "./pages/Explorer";
import { ImpactLeaderboard } from "./pages/ImpactLeaderboard";
import { BiocViews } from "./pages/BiocViews";
import { Grants } from "./pages/Grants";
import { People } from "./pages/People";
import { Growth } from "./pages/Growth";
import { Trends } from "./pages/Trends";
import { About } from "./pages/About";
import { fetchManifest, type Manifest } from "./db/duckdb";

const NAV = [
  { id: "numbers", label: "By the Numbers" },
  { id: "explorer", label: "Explorer" },
  { id: "biocviews", label: "biocViews" },
  { id: "impact", label: "Impact" },
  { id: "trends", label: "Trends" },
  { id: "grants", label: "Grants" },
  { id: "people", label: "People" },
  { id: "growth", label: "Growth" },
  { id: "about", label: "About" },
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
      <a
        href="#main"
        onClick={(e) => {
          // The hash router owns location.hash, so focus <main> instead of navigating.
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-bioc-700 focus:shadow-lg focus:outline-none focus:ring-2 focus:ring-bioc-500"
      >
        Skip to content
      </a>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-6 py-3">
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold text-slate-900">Bioconductor</span>
            <span className="text-lg font-light text-bioc-600">Intelligence</span>
          </div>
          <nav
            aria-label="Main"
            className="order-last -mx-6 flex w-[calc(100%+3rem)] gap-1 overflow-x-auto whitespace-nowrap px-6 text-sm lg:order-none lg:mx-0 lg:w-auto lg:flex-wrap lg:overflow-visible lg:px-0"
          >
            {NAV.map((n) => (
              <Link
                key={n.id}
                view={n.id}
                className={`shrink-0 rounded-md px-3 py-1.5 font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bioc-500 ${
                  active === n.id
                    ? "bg-bioc-50 text-bioc-700"
                    : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                }`}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto text-xs text-slate-500">
            {manifest ? `snapshot ${manifest.snapshot}` : ""}
          </div>
        </div>
      </header>

      <main id="main" tabIndex={-1} className="focus:outline-none mx-auto max-w-6xl px-6 py-8">
        {route.view === "explorer" ? (
          <Explorer />
        ) : route.view === "package" && route.arg ? (
          <PackagePage name={route.arg} />
        ) : route.view === "impact" ? (
          <ImpactLeaderboard />
        ) : route.view === "trends" ? (
          <Trends />
        ) : route.view === "biocviews" ? (
          <BiocViews />
        ) : route.view === "grants" ? (
          <Grants />
        ) : route.view === "people" ? (
          <People />
        ) : route.view === "growth" ? (
          <Growth />
        ) : route.view === "about" ? (
          <About manifest={manifest} />
        ) : (
          <ByTheNumbers />
        )}
      </main>

      <footer className="mx-auto max-w-6xl px-6 py-8 text-xs text-slate-500">
        Zero-backend SPA — DuckDB-WASM over prebuilt Parquet marts. Enrichment sourced read-only
        from cdsci-lake.{" "}
        <Link view="about" className="text-bioc-600 underline">
          About, methods and how to cite
        </Link>
        . Source:{" "}
        <a
          className="text-bioc-600 underline"
          href="https://github.com/seandavi/bioc-intelligence"
        >
          seandavi/bioc-intelligence
        </a>
        .
      </footer>
    </div>
  );
}
