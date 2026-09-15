"use client";

import clsx from "clsx";
import {
  BookUp,
  Download,
  Eye,
  FilePenLine,
  LoaderCircle,
} from "lucide-react";
import { memo, useCallback, useState } from "react";

import {
  getArtifact,
  listCollections,
  publishArtifact,
  type Collection,
} from "../api";
import { artifactFormatLabel, artifactSizeLabel, type TurnArtifact } from "../artifacts";
import { ChatButton, type ChatButtonTone } from "./ChatButton";
import { FileTypeIcon } from "./ResourceIcon";

/**
 * The files a turn produced, shown under the answer that presents them.
 *
 * A card carries only what the stream annotated; every action re-resolves the
 * file through the authorized artifact API, so download links stay fresh and a
 * restored conversation never trusts a stale URL.
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

type Busy = "download" | "publish" | null;

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
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [collections, setCollections] = useState<Collection[]>();
  const [collectionId, setCollectionId] = useState("");

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
    openUrl(resolved.download_url, "The download link is not available.");
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
      <FileTypeIcon className="artifact-card__icon" name={artifact.fileName} />
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
          <span className="artifact-card__state">Ready</span>
        </div>
        <div className="artifact-card__actions">
          {onPreview && (
            <ActionButton
              icon={Eye}
              label="Preview"
              onClick={() => onPreview(artifact)}
              pressed={active}
              tone="secondary"
            />
          )}
          <ActionButton busy={busy === "download"} icon={Download} label="Download" onClick={download} tone="contextual" />
          {onEdit && (
            <ActionButton icon={FilePenLine} label="Continue editing" onClick={() => onEdit(artifact)} tone="soft" />
          )}
          <ActionButton
            busy={busy === "publish" && !collections}
            icon={BookUp}
            label="Save to knowledge"
            onClick={startPublish}
            tone="success"
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
            <ChatButton
              loading={busy === "publish"}
              tone="success"
              type="submit"
            >
              Publish
            </ChatButton>
            <ChatButton
              disabled={busy !== null}
              onClick={() => setCollections(undefined)}
              tone="ghost"
              type="button"
            >
              Cancel
            </ChatButton>
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
  tone,
}: {
  busy?: boolean;
  icon: typeof Download;
  label: string;
  onClick: () => void;
  pressed?: boolean;
  tone: ChatButtonTone;
}) {
  return (
    <ChatButton
      aria-pressed={pressed}
      className={clsx("artifact-card__action", `artifact-card__action--${tone}`, pressed && "artifact-card__action--active")}
      icon={busy ? <LoaderCircle aria-hidden="true" className="artifact-card__spinner" size={14} /> : <Icon aria-hidden="true" size={14} />}
      loading={busy}
      onClick={onClick}
      title={label}
      tone={tone}
      type="button"
    >
      {label}
    </ChatButton>
  );
}

function openUrl(url: string | null | undefined, missing: string) {
  if (!url) throw new Error(missing);
  window.open(url, "_blank", "noopener,noreferrer");
}
