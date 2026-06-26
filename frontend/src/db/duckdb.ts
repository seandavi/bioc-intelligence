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
] as const;

export interface Manifest {
  snapshot: string;
  marts: string[];
}

let dbPromise: Promise<duckdb.AsyncDuckDB> | null = null;

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

  const base = import.meta.env.BASE_URL;
  await Promise.all(
    MARTS.map(async (name) => {
      const res = await fetch(`${base}data/${name}`);
      if (!res.ok) throw new Error(`failed to load mart ${name}: ${res.status}`);
      const buf = new Uint8Array(await res.arrayBuffer());
      await db.registerFileBuffer(name, buf);
    }),
  );
  return db;
}

export function getDb(): Promise<duckdb.AsyncDuckDB> {
  if (!dbPromise) dbPromise = boot();
  return dbPromise;
}

export async function fetchManifest(): Promise<Manifest> {
  const res = await fetch(`${import.meta.env.BASE_URL}data/manifest.json`);
  if (!res.ok) return { snapshot: "unknown", marts: [...MARTS] };
  return res.json();
}

// Run a SQL query and return plain JS row objects. A fresh connection per call
// keeps callers simple; DuckDB-WASM connections are cheap.
export async function query<T = Record<string, unknown>>(sql: string): Promise<T[]> {
  const db = await getDb();
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
