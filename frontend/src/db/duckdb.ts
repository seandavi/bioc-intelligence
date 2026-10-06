// DuckDB-WASM bootstrap: boot the engine once, register the bundled Parquet marts
// as named files, and hand out a shared connection. Everything runs in the browser;
// there is no backend (spec §8).
import * as duckdb from "@duckdb/duckdb-wasm";

// Marts bundled into the site under <base>/data/. Registered under their bare
// filenames so queries read `FROM 'mart_*.parquet'`.
export const MARTS = [
  "mart_package_directory.parquet",
  "mart_package_impact.parquet",
  "mart_grant_attribution.parquet",
  "mart_release_growth.parquet",
  "mart_work.parquet",
  "mart_package_work.parquet",
  "mart_ecosystem_downloads_yearly.parquet",
  "mart_person.parquet",
  "mart_package_person.parquet",
  "mart_package_funder.parquet",
] as const;

// Marts too large to fetch at boot (~4 MiB). Fetched whole and registered the first time a
// query names them. Not registerFileURL range reads: GitHub Pages gzips .parquet and applies
// Range to the gzipped stream (HEAD reports the compressed length, tail ranges 416), so
// DuckDB-WASM would read the footer at the wrong offset. Revisit if the marts move to a host
// that serves identity-encoded ranges.
export const LAZY_MARTS = ["mart_package_downloads_monthly.parquet"] as const;

export interface Manifest {
  snapshot: string;
  marts: string[];
}

let dbPromise: Promise<duckdb.AsyncDuckDB> | null = null;
const lazyLoads = new Map<string, Promise<void>>();

async function registerMart(db: duckdb.AsyncDuckDB, name: string) {
  const res = await fetch(`${import.meta.env.BASE_URL}data/${name}`);
  if (!res.ok) throw new Error(`failed to load mart ${name}: ${res.status}`);
  await db.registerFileBuffer(name, new Uint8Array(await res.arrayBuffer()));
}

async function boot(): Promise<duckdb.AsyncDuckDB> {
  const bundles = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(bundles);
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker!}");`], { type: "text/javascript" }),
  );
  const worker = new Worker(workerUrl);
  const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);

  await Promise.all(MARTS.map((name) => registerMart(db, name)));
  return db;
}

export function getDb(): Promise<duckdb.AsyncDuckDB> {
  if (!dbPromise) dbPromise = boot();
  return dbPromise;
}

export async function fetchManifest(): Promise<Manifest> {
  const res = await fetch(`${import.meta.env.BASE_URL}data/manifest.json`);
  if (!res.ok) return { snapshot: "unknown", marts: [...MARTS, ...LAZY_MARTS] };
  return res.json();
}

// Run a SQL query and return plain JS row objects. A fresh connection per call
// keeps callers simple; DuckDB-WASM connections are cheap.
export async function query<T = Record<string, unknown>>(sql: string): Promise<T[]> {
  const db = await getDb();
  for (const name of LAZY_MARTS) {
    if (!sql.includes(name)) continue;
    if (!lazyLoads.has(name)) {
      const p = registerMart(db, name);
      p.catch(() => lazyLoads.delete(name)); // let a later query retry
      lazyLoads.set(name, p);
    }
    await lazyLoads.get(name);
  }
  const conn = await db.connect();
  try {
    const result = await conn.query(sql);
    return result.toArray().map((row: any) => {
      const obj = row.toJSON();
      // Arrow returns BigInt for 64-bit ints; coerce to Number for display/serialization.
      for (const k of Object.keys(obj)) {
        if (typeof obj[k] === "bigint") obj[k] = Number(obj[k]);
      }
      return obj as T;
    });
  } finally {
    await conn.close();
  }
}
