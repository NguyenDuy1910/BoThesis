"use client";

import { ChevronRight, Folder, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { connectionsApi, type ProviderResource } from "@/modules/knowledge/integrations-api";

export interface SelectedResource {
  resource_type: string;
  external_id: string;
  name: string;
}

interface Crumb {
  id: string | null;
  name: string;
}

/**
 * What to read from an account that is already connected.
 *
 * Nothing is selected by default. A workspace's whole Drive is rarely what
 * anyone means, and indexing it because a checkbox started ticked is a costly
 * thing to undo — so the picker opens empty and the button stays disabled
 * until someone says what they want.
 *
 * Containers are walked rather than expanded in place: a Shared Drive can hold
 * hundreds of folders, and a tree that unfolds inside a dialog loses the
 * reader long before it runs out of room.
 */
export function ResourcePicker({
  connectionId,
  selected,
  onChange,
}: {
  connectionId: string;
  selected: SelectedResource[];
  onChange: (next: SelectedResource[]) => void;
}) {
  const [trail, setTrail] = useState<Crumb[]>([{ id: null, name: "All" }]);
  const [resources, setResources] = useState<ProviderResource[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  const current = trail[trail.length - 1];

  const load = useCallback(
    async (parentId: string | null, term: string) => {
      setLoading(true);
      setError(null);
      try {
        const page = await connectionsApi.resources(connectionId, {
          parent_id: parentId ?? undefined,
          search: term.trim() || undefined,
        });
        setResources(page.items);
      } catch (cause) {
        setResources(null);
        setError(
          cause instanceof Error
            ? cause.message
            : "This account's contents could not be read.",
        );
      } finally {
        setLoading(false);
      }
    },
    [connectionId],
  );

  useEffect(() => {
    // Searching a large organization is a server-side question, so it is
    // debounced rather than filtered in the browser over one page of results.
    const timer = window.setTimeout(() => void load(current.id, search), 250);
    return () => window.clearTimeout(timer);
  }, [current.id, load, search]);

  const selectedIds = useMemo(
    () => new Set(selected.map((item) => item.external_id)),
    [selected],
  );

  const toggle = (resource: ProviderResource) => {
    onChange(
      selectedIds.has(resource.external_id)
        ? selected.filter((item) => item.external_id !== resource.external_id)
        : [
            ...selected,
            {
              resource_type: resource.resource_type,
              external_id: resource.external_id,
              name: resource.name,
            },
          ],
    );
  };

  const openContainer = (resource: ProviderResource) => {
    setSearch("");
    setTrail((value) => [...value, { id: resource.external_id, name: resource.name }]);
  };

  return (
    <section aria-label="Choose knowledge to add" className="knowledge-picker">
      <div className="knowledge-picker__bar">
        <nav aria-label="Location" className="knowledge-picker__trail">
          {trail.map((crumb, index) => (
            <span key={`${crumb.id ?? "root"}-${index}`}>
              {index > 0 && <ChevronRight aria-hidden="true" size={13} />}
              {index === trail.length - 1 ? (
                <strong>{crumb.name}</strong>
              ) : (
                <button onClick={() => setTrail((value) => value.slice(0, index + 1))} type="button">
                  {crumb.name}
                </button>
              )}
            </span>
          ))}
        </nav>
        <div className="knowledge-picker__search">
          <Search aria-hidden="true" size={14} />
          <Input
            aria-label="Search this account"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search…"
            spellCheck={false}
            value={search}
          />
        </div>
      </div>

      {error ? (
        <ErrorState
          actionLabel="Try again"
          description={error}
          layout="inline"
          onAction={() => void load(current.id, search)}
          title="This account's contents could not be read"
        />
      ) : loading ? (
        <ul aria-busy="true" className="knowledge-picker__list">
          <li className="sr-only">Loading</li>
          {Array.from({ length: 4 }).map((_, index) => (
            <li key={index}>
              <Skeleton className="h-8 w-full" />
            </li>
          ))}
        </ul>
      ) : resources?.length ? (
        <ul className="knowledge-picker__list">
          {resources.map((resource) => (
            <li key={`${resource.resource_type}:${resource.external_id}`}>
              <label>
                <input
                  checked={selectedIds.has(resource.external_id)}
                  onChange={() => toggle(resource)}
                  type="checkbox"
                />
                <Folder aria-hidden="true" size={15} />
                <span className="min-w-0 flex-1 truncate">{resource.name}</span>
              </label>
              {resource.has_children && (
                <Button
                  aria-label={`Open ${resource.name}`}
                  icon={<ChevronRight size={16} />}
                  iconOnly
                  onClick={() => openContainer(resource)}
                  size="sm"
                  variant="ghost"
                />
              )}
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          description={
            search
              ? "Nothing here matches that search."
              : "This account has nothing BoThesis can read at this level."
          }
          size="sm"
          title="Nothing to choose"
        />
      )}

      <p className="knowledge-picker__summary">
        {selected.length
          ? `${selected.length} selected: ${selected.map((item) => item.name).join(", ")}`
          : "Nothing selected yet. Only what you tick here is indexed."}
      </p>
    </section>
  );
}
