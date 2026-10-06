// Minimal hash router: "#/<view>[/<arg>][?<query>]". No dependency; GitHub Pages needs no 404 handling.
import { useMemo, useSyncExternalStore, type ReactNode } from "react";

export type Params = Record<string, string>;

export interface Route {
  view: string;
  arg: string; // path segment after the view, e.g. the package name in #/package/<name>
  params: Params;
}

const decode = (s: string) => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

export function parseHash(hash: string): Route {
  const i = hash.indexOf("?");
  const path = (i < 0 ? hash : hash.slice(0, i)).replace(/^#\/?/, "");
  const [view = "", ...rest] = path.split("/");
  return {
    view,
    arg: decode(rest.join("/")),
    params: Object.fromEntries(new URLSearchParams(i < 0 ? "" : hash.slice(i + 1))),
  };
}

export function hrefFor(view: string, params: Params = {}, arg?: string): string {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "")).toString();
  return `#/${view}${arg ? `/${encodeURIComponent(arg)}` : ""}${q ? `?${q}` : ""}`;
}

const subscribe = (cb: () => void) => {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
};

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash);
  return useMemo(() => parseHash(hash), [hash]);
}

// Replace the current history entry (so Back is not spammed). replaceState does not fire
// hashchange, so dispatch it for useRoute subscribers. View changes go through <Link>, which
// pushes a normal history entry.
export function navigate(view: string, params: Params = {}, arg?: string) {
  history.replaceState(null, "", hrefFor(view, params, arg));
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

// Merge `patch` into the current query params of `view`; empty values drop the param.
export const setParams = (view: string, patch: Params) =>
  navigate(view, { ...parseHash(window.location.hash).params, ...patch });

// Multi-valued params (repo, agency) are '|'-joined.
export const parseList = (s: string | undefined) => (s ? s.split("|").filter(Boolean) : []);

export function toggleInList(s: string | undefined, v: string): string {
  const l = parseList(s);
  return (l.includes(v) ? l.filter((x) => x !== v) : [...l, v]).join("|");
}

export function Link({
  view,
  params,
  arg,
  className,
  children,
}: {
  view: string;
  params?: Params;
  arg?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <a href={hrefFor(view, params, arg)} className={className}>
      {children}
    </a>
  );
}
