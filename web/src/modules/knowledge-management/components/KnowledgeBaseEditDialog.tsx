"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { useToast } from "@/components/ui/Toast";
import { adminRequest } from "@/modules/admin/api";
import { errorMessage } from "@/modules/knowledge-management/presentation";
import type { KnowledgeItem } from "@/modules/knowledge-management/types";

const FORM_ID = "knowledge-base-edit-form";

export function KnowledgeBaseEditDialog({
  item,
  onClose,
  onSaved,
}: {
  item: KnowledgeItem;
  onClose: () => void;
  onSaved: (item: KnowledgeItem) => void;
}) {
  const { toast } = useToast();
  const nameRef = useRef<HTMLInputElement | null>(null);
  const [name, setName] = useState(item.title);
  const [description, setDescription] = useState(collectionDescription(item));
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const normalizedName = name.trim();
  const nameError = touched && !normalizedName
    ? "Enter a name for this knowledge base."
    : undefined;

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    setTouched(true);
    if (!normalizedName) {
      nameRef.current?.focus();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await adminRequest<KnowledgeItem>(`/collections/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: normalizedName,
          description: description.trim() || null,
        }),
      });
      toast({ title: "Knowledge base updated", variant: "success" });
      onSaved(updated);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      footer={(
        <>
          <Button disabled={saving} onClick={onClose} variant="secondary">Cancel</Button>
          <Button disabled={!normalizedName} form={FORM_ID} loading={saving} type="submit">
            Save changes
          </Button>
        </>
      )}
      initialFocusRef={nameRef}
      onClose={() => { if (!saving) onClose(); }}
      open
      title="Edit knowledge base"
    >
      <form className="space-y-4" id={FORM_ID} onSubmit={save}>
        {error && <p className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-soft)] px-3 py-2.5 text-sm text-[var(--danger-text)]" role="alert">{error}</p>}
        <FormField error={nameError} htmlFor="knowledge-base-edit-name" label="Knowledge base name" required>
          <Input
            aria-describedby={nameError ? "knowledge-base-edit-name-error" : undefined}
            autoComplete="off"
            error={Boolean(nameError)}
            id="knowledge-base-edit-name"
            maxLength={255}
            onBlur={() => setTouched(true)}
            onChange={(event) => setName(event.target.value)}
            ref={nameRef}
            value={name}
          />
        </FormField>
        <FormField helperText={`${description.length.toLocaleString()} of 2,000 characters`} htmlFor="knowledge-base-edit-description" label="Description">
          <Textarea
            aria-describedby="knowledge-base-edit-description-helper"
            id="knowledge-base-edit-description"
            maxLength={2_000}
            onChange={(event) => setDescription(event.target.value)}
            rows={4}
            value={description}
          />
        </FormField>
      </form>
    </Dialog>
  );
}

export function collectionDescription(item: KnowledgeItem) {
  const description = item.metadata?.description;
  return typeof description === "string" ? description : "";
}
