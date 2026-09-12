"use client";

import { BookOpen, CornerDownLeft, FileText, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { appBrand } from "@/lib/brand";
import { getAuthSession, hasSessionPermission } from "@/lib/auth/session";
import { adminRequest, queryString } from "@/modules/admin/api";
import {
  adminRoutes,
  canAccessAdminRoute,
  type AdminRoute,
} from "@/modules/admin/navigation";

interface PaletteEntry {
  id: string;
  group: string;
  label: string;
  hint?: string;
  href: string;
  icon: React.ReactNode;
}

interface SearchableItem {
  id: string;
  title: string;
  item_type: "collection" | "document";
  parent_item_id: string | null;
}

const SEARCH_DEBOUNCE_MS = 220;

function matches(route: AdminRoute, query: string) {
  const haystack = [route.label, route.description, ...(route.keywords ?? [])]
    .join(" ")
    .toLowerCase();
  return query.split(/\s+/).every((term) => haystack.includes(term));
}

/**
 * One search box for the whole console: it goes to a section, or straight to a
 * collection or document by name, so nothing is more than a keystroke away.
 */
export function AdminCommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<SearchableItem[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setItems([]);
      setActiveIndex(0);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  // Content search only starts once the query is specific enough to be worth a
  // round trip; section matching stays instant and local.
  useEffect(() => {
    const term = query.trim();
    if (!open || term.length < 2 || !hasSessionPermission(getAuthSession(), "item.manage")) {
      setItems([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      adminRequest<{ items: SearchableItem[] }>(
        `/items${queryString({ search: term, page_size: 6 })}`,
        { signal: controller.signal },
      )
        .then((result) => setItems(result.items ?? []))
        .catch(() => {
          if (!controller.signal.aborted) setItems([]);
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [open, query]);

  const entries = useMemo<PaletteEntry[]>(() => {
    const term = query.trim().toLowerCase();
    const sections = adminRoutes
      .filter((route) => canAccessAdminRoute(route, getAuthSession()))
      .filter((route) => !term || matches(route, term))
      .map((route) => {
        const Icon = route.icon;
        return {
          id: `route:${route.id}`,
          group: "Go to",
          label: route.label,
          href: route.path,
          icon: <Icon aria-hidden="true" className="h-4 w-4" />,
        };
      });

    const content = items.map((item) => ({
      id: `item:${item.id}`,
      group: "Knowledge",
      label: item.title || "Untitled",
      href:
        item.item_type === "collection"
          ? `/knowledge/collections/${item.id}`
          : `/knowledge/collections/${item.parent_item_id ?? ""}`,
      icon:
        item.item_type === "collection" ? (
          <BookOpen aria-hidden="true" className="h-4 w-4" />
        ) : (
          <FileText aria-hidden="true" className="h-4 w-4" />
        ),
    }));

    return [...sections, ...content.filter((entry) => entry.href !== "/knowledge/collections/")];
  }, [items, query]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  if (!open || typeof document === "undefined") return null;

  const go = (entry: PaletteEntry | undefined) => {
    if (!entry) return;
    onClose();
    router.push(entry.href);
  };

  let renderedGroup = "";

  return createPortal(
    <div className="adm-palette" role="dialog" aria-label={`Search ${appBrand.productName} Admin`} aria-modal="true">
      <button
        aria-label="Close search"
        className="adm-palette__scrim"
        onClick={onClose}
        tabIndex={-1}
        type="button"
      />
      <div className="adm-palette__panel">
        <div className="adm-palette__field">
          <Search aria-hidden="true" className="h-4 w-4 shrink-0" />
          <input
            aria-label="Search sections, collections and documents"
            autoFocus
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                onClose();
              } else if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveIndex((index) => (index + 1) % Math.max(entries.length, 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveIndex(
                  (index) =>
                    (index - 1 + Math.max(entries.length, 1)) %
                    Math.max(entries.length, 1),
                );
              } else if (event.key === "Enter") {
                event.preventDefault();
                go(entries[activeIndex]);
              }
            }}
            placeholder="Search sections, collections and documents…"
            ref={inputRef}
            value={query}
          />
          <kbd className="adm-kbd">Esc</kbd>
        </div>

        <div className="adm-palette__results">
          {entries.length === 0 ? (
            <p className="adm-palette__empty">
              Nothing matches “{query.trim()}”.
            </p>
          ) : (
            entries.map((entry, index) => {
              const showGroup = entry.group !== renderedGroup;
              renderedGroup = entry.group;
              return (
                <div key={entry.id}>
                  {showGroup && <p className="adm-palette__group">{entry.group}</p>}
                  <button
                    className="adm-palette__item"
                    data-active={index === activeIndex}
                    onClick={() => go(entry)}
                    onMouseEnter={() => setActiveIndex(index)}
                    type="button"
                  >
                    {entry.icon}
                    <span className="min-w-0 flex-1 truncate">{entry.label}</span>
                    {entry.hint && <small>{entry.hint}</small>}
                    {index === activeIndex && (
                      <CornerDownLeft
                        aria-hidden="true"
                        className="h-3.5 w-3.5 shrink-0"
                      />
                    )}
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
