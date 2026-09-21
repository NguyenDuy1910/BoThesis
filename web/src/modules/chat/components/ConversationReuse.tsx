"use client";

import { LibraryBig } from "lucide-react";

import type { ConversationResource } from "../conversation-resources";
import { FileTypeIcon } from "./ResourceIcon";

/** A quiet reminder of durable resources the next turn can already use. */
export function ConversationReuse({ resources }: { resources: ConversationResource[] }) {
  if (!resources.length) return null;
  const visible = resources.slice(0, 3);
  const remaining = resources.length - visible.length;

  return (
    <aside aria-label="Resources reused from this conversation" className="conversation-reuse">
      <div className="conversation-reuse__heading">
        <LibraryBig aria-hidden="true" size={14} />
        <span>Reusing from this conversation</span>
      </div>
      <div className="conversation-reuse__list">
        {visible.map((resource) => (
          <span className="conversation-reuse__item" key={resource.id} title={`${resource.title} · ${resource.kind} · Turn ${resource.turn}`}>
            {resource.kind === "source"
              ? <LibraryBig aria-hidden="true" size={14} />
              : <FileTypeIcon name={resource.title} />}
            <span>{resource.title}</span>
            <small>{resource.kind === "artifact" ? "Artifact" : resource.kind === "source" ? "Source" : "Attachment"} · Turn {resource.turn}</small>
          </span>
        ))}
        {remaining > 0 && <span className="conversation-reuse__more">+{remaining} more</span>}
      </div>
    </aside>
  );
}
