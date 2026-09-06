"use client";

import { FileWarning, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { getArtifactContent, type ArtifactContent } from "../api";
import { IncrementalMarkdown } from "./IncrementalMarkdown";

/**
 * One revision of a produced document, rendered beside the conversation.
 *
 * The text comes from the authorized artifact API on demand, so a card that
 * was restored from an old conversation never shows stale or leaked content.
 */
export function ArtifactPreview({
  artifactId,
  revision,
}: {
  artifactId: string;
  revision: number;
}) {
  const [content, setContent] = useState<ArtifactContent>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    const controller = new AbortController();
    setError(undefined);
    void getArtifactContent(artifactId, revision, controller.signal)
      .then(setContent)
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : "Could not open this document.");
      });
    return () => controller.abort();
  }, [artifactId, revision]);

  if (error) {
    return (
      <div className="artifact-preview__notice" role="alert">
        <FileWarning aria-hidden="true" size={16} />
        <span>{error}</span>
      </div>
    );
  }
  if (!content) {
    return (
      <div className="artifact-preview__notice" role="status">
        <LoaderCircle aria-hidden="true" className="artifact-preview__spinner" size={16} />
        <span>Opening document…</span>
      </div>
    );
  }
  return (
    <div className="artifact-preview">
      <div className="artifact-preview__meta">
        <span>Revision {content.revision}</span>
        {content.truncated && <span>Preview shortened</span>}
      </div>
      <div className="artifact-preview__body assistant-content">
        <IncrementalMarkdown isStreaming={false} text={content.content} />
      </div>
    </div>
  );
}
