"use client";

import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";

/** Create a governed Collection before adding files or connected knowledge to it. */
export function CreateCollectionDialog({
  open,
  onClose,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  onCreate: (values: { title: string; description?: string }) => Promise<void>;
}) {
  const formId = useId();
  const titleId = useId();
  const descriptionId = useId();
  const titleRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setTitle("");
    setDescription("");
    setSaving(false);
    setError(null);
  }, [open]);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!title.trim()) {
      setError("Enter a collection name.");
      titleRef.current?.focus();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onCreate({ title: title.trim(), description: description.trim() || undefined });
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The collection could not be created.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      footer={(
        <>
          <Button disabled={saving} onClick={onClose} variant="ghost">Cancel</Button>
          <Button form={formId} loading={saving} type="submit">
            Create collection
          </Button>
        </>
      )}
      initialFocusRef={titleRef}
      onClose={onClose}
      open={open}
      title="Create collection"
    >
      <form className="space-y-4" id={formId} noValidate onSubmit={(event) => void submit(event)}>
        <p className="text-[length:var(--text-size-ui)] leading-5 text-[var(--text-tertiary)]">
          Collections keep connected sources and uploads together under one access boundary.
        </p>
        <FormField error={error ?? undefined} htmlFor={titleId} label="Collection name" required>
          <Input
            autoComplete="off"
            aria-describedby={error ? `${titleId}-error` : undefined}
            error={Boolean(error)}
            id={titleId}
            name="title"
            onChange={(event) => {
              setTitle(event.target.value);
              if (error) setError(null);
            }}
            placeholder="Engineering handbook"
            ref={titleRef}
            required
            value={title}
          />
        </FormField>
        <FormField htmlFor={descriptionId} label="Description">
          <Textarea
            autoComplete="off"
            id={descriptionId}
            name="description"
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What this collection contains…"
            rows={3}
            value={description}
          />
        </FormField>
      </form>
    </Dialog>
  );
}
