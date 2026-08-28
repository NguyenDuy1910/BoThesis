"use client";

import { Check, ChevronDown, LoaderCircle, PlugZap, RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/cn";
import { connectorDefinition } from "../catalog";
import type { ChatConnector, ChatConnectorMode } from "../types";
import { ConnectorLogo } from "./ConnectorLogo";

export function PluginPicker({
  connectors,
  disabled,
  error,
  loading,
  mode,
  onModeChange,
  onReload,
  onSelectionChange,
  selectedIds,
}: {
  connectors: ChatConnector[];
  disabled?: boolean;
  error: string | null;
  loading: boolean;
  mode: ChatConnectorMode;
  onModeChange: (mode: ChatConnectorMode) => void;
  onReload: () => void;
  onSelectionChange: (ids: string[]) => void;
  selectedIds: string[];
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const matching = useMemo(() => {
    const term = search.trim().toLocaleLowerCase();
    if (!term) return connectors;
    return connectors.filter((connector) => {
      const definition = connectorDefinition(connector.provider);
      return `${connector.display_name} ${definition?.name ?? connector.provider}`
        .toLocaleLowerCase()
        .includes(term);
    });
  }, [connectors, search]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        requestAnimationFrame(() => triggerRef.current?.focus());
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    const frame = requestAnimationFrame(() => {
      if (window.matchMedia("(min-width: 640px)").matches) searchRef.current?.focus();
    });
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const summary = mode === "auto"
    ? "Auto"
    : mode === "off"
      ? "Off"
      : selectedIds.length === 1
        ? "1 source"
        : `${selectedIds.length} sources`;

  function toggle(connectorId: string) {
    const next = selectedIds.includes(connectorId)
      ? selectedIds.filter((id) => id !== connectorId)
      : [...selectedIds, connectorId];
    onSelectionChange(next);
    onModeChange("selected");
  }

  return (
    <div className="plugin-picker" ref={rootRef}>
      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        className={cn("composer-tool plugin-picker__trigger", open && "plugin-picker__trigger--open")}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        ref={triggerRef}
        title="Choose knowledge sources"
        type="button"
      >
        <PlugZap aria-hidden="true" size={15} />
        <span>Knowledge</span>
        <small>{summary}</small>
        <ChevronDown aria-hidden="true" className={cn("plugin-picker__chevron", open && "plugin-picker__chevron--open")} size={13} />
      </button>
      {open && (
        <div aria-label="Choose connectors for this chat" className="plugin-picker__menu" role="dialog">
          <div className="plugin-picker__header">
            <div>
              <p>Knowledge sources</p>
              <span>Control what this message can search.</span>
            </div>
          </div>
          <div aria-label="Connector mode" className="plugin-picker__modes" role="group">
            {(["auto", "selected", "off"] as const).map((item) => (
              <button
                aria-pressed={mode === item}
                className={cn(mode === item && "is-active")}
                key={item}
                onClick={() => onModeChange(item)}
                type="button"
              >
                {item === "auto" ? "Auto" : item === "selected" ? "Selected" : "Off"}
              </button>
            ))}
          </div>
          <p className="plugin-picker__mode-help">
            {mode === "auto" && "BoThesis chooses among your permitted connections."}
            {mode === "selected" && "Only the checked connections can be searched."}
            {mode === "off" && "Connector tools are disabled for this message."}
          </p>
          {mode !== "off" && (
            <>
              <label className="plugin-picker__search">
                <Search aria-hidden="true" size={14} />
                <span className="sr-only">Search available connections</span>
                <input autoComplete="off" name="connector_search" onChange={(event) => setSearch(event.target.value)} placeholder="Search connections…" ref={searchRef} spellCheck={false} value={search} />
              </label>
              <div className="plugin-picker__list">
                {loading && <div className="plugin-picker__state"><LoaderCircle aria-hidden="true" className="animate-spin" size={16} /> Loading permitted connections…</div>}
                {!loading && error && (
                  <div className="plugin-picker__state plugin-picker__state--error">
                    <span>Connections could not be loaded.</span>
                    <button onClick={onReload} type="button"><RefreshCw aria-hidden="true" size={13} /> Retry</button>
                  </div>
                )}
                {!loading && !error && !matching.length && (
                  <div className="plugin-picker__state">{connectors.length ? "No connections match that search." : "No active connections are available to chat."}</div>
                )}
                {!loading && !error && matching.map((connector) => {
                  const definition = connectorDefinition(connector.provider);
                  const selected = selectedIds.includes(connector.id);
                  return (
                    <button
                      aria-pressed={selected}
                      className={cn("plugin-picker__item", selected && "is-selected")}
                      key={connector.id}
                      onClick={() => toggle(connector.id)}
                      type="button"
                    >
                      <ConnectorLogo provider={connector.provider} size="sm" />
                      <span className="plugin-picker__item-copy">
                        <strong>{connector.display_name}</strong>
                        <small>{definition?.name ?? connector.provider}</small>
                      </span>
                      <span aria-hidden="true" className="plugin-picker__check">{selected && <Check size={12} strokeWidth={2.5} />}</span>
                    </button>
                  );
                })}
              </div>
            </>
          )}
          <div className="plugin-picker__footer"><span>Tenant-enabled</span><span>Permission-aware</span></div>
        </div>
      )}
    </div>
  );
}
