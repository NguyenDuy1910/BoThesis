"use client";

import clsx from "clsx";
import {
  BookUp,
  Download,
  Eye,
  FileDown,
  FilePenLine,
  FileText,
  LoaderCircle,
} from "lucide-react";
import { memo, useCallback, useState } from "react";

import {
  exportArtifact,
  getArtifact,
  listCollections,
  publishArtifact,
  type ArtifactDetail,
  type Collection,
} from "../api";
import { artifactFormatLabel, artifactSizeLabel, type TurnArtifact } from "../artifacts";

/**
 * The documents a turn produced, shown under the answer that presents them.
 *
 * A card carries only what the stream annotated; every action re-resolves the
 * document through the authorized artifact API, so download links stay fresh
 * and a restored conversation never trusts a stale URL.
 */
export const ArtifactCards = memo(function ArtifactCards({
  activeArtifactId,
  artifacts,
  onEdit,
  onPreview,
}: {
  activeArtifactId?: string;
  artifacts: readonly TurnArtifact[];
  onEdit?: (artifact: TurnArtifact) => void;
  onPreview?: (artifact: TurnArtifact) => void;
}) {
  if (!artifacts.length) return null;
  return (
    <div aria-label="Documents from this answer" className="artifact-cards" role="group">
      {artifacts.map((artifact) => (
        <ArtifactCard
          active={activeArtifactId === artifact.id}
          artifact={artifact}
          key={artifact.id}
          onEdit={onEdit}
          onPreview={onPreview}
        />
      ))}
    </div>
  );
});

type Busy = "download" | "export" | "publish" | null;

function ArtifactCard({
  active,
  artifact,
  onEdit,
  onPreview,
}: {
  active: boolean;
  artifact: TurnArtifact;
  onEdit?: (artifact: TurnArtifact) => void;
  onPreview?: (artifact: TurnArtifact) => void;
}) {
  const [detail, setDetail] = useState<ArtifactDetail>();
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [collections, setCollections] = useState<Collection[]>();
  const [collectionId, setCollectionId] = useState("");
  const hasPdf = artifact.exports.includes("pdf") || Boolean(detail?.exports.pdf?.download_url);

  const run = useCallback(async (kind: Busy, action: () => Promise<void>) => {
    if (busy) return;
    setBusy(kind);
    setError(undefined);
    setNotice(undefined);
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The document action failed.");
    } finally {
      setBusy(null);
    }
  }, [busy]);

  const download = useCallback(() => run("download", async () => {
    const resolved = await getArtifact(artifact.id);
    setDetail(resolved);
    openUrl(resolved.download_url, "The download link is not available.");
  }), [artifact.id, run]);

  const exportPdf = useCallback(() => run("export", async () => {
    const resolved = await exportArtifact(artifact.id, "pdf");
    setDetail(resolved);
    openUrl(resolved.exports.pdf?.download_url, "The PDF is not available.");
  }), [artifact.id, run]);

  const startPublish = useCallback(() => run("publish", async () => {
    const available = await listCollections();
    if (!available.length) {
      throw new Error("No collection is available to publish into. Ask an administrator for access.");
    }
    setCollections(available);
    setCollectionId(available[0]?.id ?? "");
  }), [run]);

  const confirmPublish = useCallback(() => run("publish", async () => {
    const collection = collections?.find((candidate) => candidate.id === collectionId);
    if (!collection) throw new Error("Choose a destination collection.");
    const published = await publishArtifact(artifact.id, collection.id);
    setCollections(undefined);
    setNotice(
      published.created
        ? `Published to ${collection.title}.`
        : `Already published to ${collection.title}.`,
    );
  }), [artifact.id, collections, collectionId, run]);

  return (
    <div className={clsx("artifact-card", active && "artifact-card--active")}>
      <span className="artifact-card__icon"><FileText aria-hidden="true" size={18} /></span>
      <div className="artifact-card__body">
        <div className="artifact-card__heading">
          <span className="artifact-card__title" title={artifact.fileName}>{artifact.title}</span>
          <span className="artifact-card__meta">
            {[
              `Revision ${artifact.revision}`,
              artifactFormatLabel(artifact.mimeType),
              artifactSizeLabel(artifact.sizeBytes),
            ].join(" · ")}
          </span>
        </div>
        <div className="artifact-card__actions">
          {onPreview && (
            <ActionButton
              icon={Eye}
              label="Preview"
              onClick={() => onPreview(artifact)}
              pressed={active}
            />
          )}
          <ActionButton busy={busy === "download"} icon={Download} label="Download" onClick={download} />
          {onEdit && (
            <ActionButton icon={FilePenLine} label="Edit" onClick={() => onEdit(artifact)} />
          )}
          <ActionButton
            busy={busy === "export"}
            icon={FileDown}
            label={hasPdf ? "Download PDF" : "Export PDF"}
            onClick={exportPdf}
          />
          <ActionButton
            busy={busy === "publish" && !collections}
            icon={BookUp}
            label="Publish to Knowledge Base"
            onClick={startPublish}
          />
        </div>
        {collections && (
          <form
            className="artifact-card__publish"
            onSubmit={(event) => {
              event.preventDefault();
              void confirmPublish();
            }}
          >
            <label className="artifact-card__publish-label" htmlFor={`publish-${artifact.id}`}>
              Destination collection
            </label>
            <select
              className="artifact-card__publish-select"
              id={`publish-${artifact.id}`}
              onChange={(event) => setCollectionId(event.target.value)}
              value={collectionId}
            >
              {collections.map((collection) => (
                <option key={collection.id} value={collection.id}>{collection.title}</option>
              ))}
            </select>
            <button className="artifact-card__action artifact-card__action--primary" disabled={busy !== null} type="submit">
              {busy === "publish" ? <LoaderCircle aria-hidden="true" className="artifact-card__spinner" size={13} /> : null}
              <span>Publish</span>
            </button>
            <button
              className="artifact-card__action"
              disabled={busy !== null}
              onClick={() => setCollections(undefined)}
              type="button"
            >
              Cancel
            </button>
          </form>
        )}
        {error && <div className="artifact-card__note artifact-card__note--error" role="alert">{error}</div>}
        {notice && <div className="artifact-card__note" role="status">{notice}</div>}
      </div>
    </div>
  );
}

function ActionButton({
  busy = false,
  icon: Icon,
  label,
  onClick,
  pressed,
}: {
  busy?: boolean;
  icon: typeof Download;
  label: string;
  onClick: () => void;
  pressed?: boolean;
}) {
  return (
    <button
      aria-pressed={pressed}
      className={clsx("artifact-card__action", pressed && "artifact-card__action--active")}
      disabled={busy}
      onClick={onClick}
      title={label}
      type="button"
    >
      {busy
        ? <LoaderCircle aria-hidden="true" className="artifact-card__spinner" size={13} />
        : <Icon aria-hidden="true" size={13} />}
      <span>{label}</span>
    </button>
  );
}

function openUrl(url: string | null | undefined, missing: string) {
  if (!url) throw new Error(missing);
  window.open(url, "_blank", "noopener,noreferrer");
}
