"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { useToast } from "@/components/ui/Toast";
import { adminRequest } from "@/modules/admin/api";
import { collectionDescription, type KnowledgeItem } from "@/modules/admin/collections";
import { errorMessage } from "@/modules/admin/format";

const FORM_ID = "collection-edit-form";

export function CollectionEditDialog({
  collection,
  onClose,
  onSaved,
}: {
  collection: KnowledgeItem;
  onClose: () => void;
  onSaved: (collection: KnowledgeItem) => void;
}) {
  const { toast } = useToast();
  const nameRef = useRef<HTMLInputElement | null>(null);
  const [name, setName] = useState(collection.title);
  const [description, setDescription] = useState(collectionDescription(collection));
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedName = name.trim();
  const nameError = touched && !trimmedName ? "Give this collection a name." : undefined;
  const unchanged =
    trimmedName === collection.title &&
    description.trim() === collectionDescription(collection);

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    setTouched(true);
    if (!trimmedName) {
      nameRef.current?.focus();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await adminRequest<KnowledgeItem>(
        `/collections/${collection.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            title: trimmedName,
            description: description.trim() || null,
          }),
        },
      );
      toast({ title: "Collection updated", variant: "success" });
      onSaved(updated);
    } catch (cause) {
      setError(errorMessage(cause, "The collection could not be updated."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      className="max-w-lg"
      footer={
        <>
          <Button disabled={saving} onClick={onClose} variant="secondary">
            Cancel
          </Button>
          <Button
            disabled={!trimmedName || unchanged}
            form={FORM_ID}
            loading={saving}
            type="submit"
          >
            Save changes
          </Button>
        </>
      }
      initialFocusRef={nameRef}
      onClose={() => {
        if (!saving) onClose();
      }}
      open
      title="Edit collection"
    >
      <form className="space-y-4" id={FORM_ID} onSubmit={save}>
        {error && <ErrorState description={error} layout="inline" />}
        <FormField
          error={nameError}
          htmlFor="collection-edit-name"
          label="Name"
          required
        >
          <Input
            autoComplete="off"
            error={Boolean(nameError)}
            id="collection-edit-name"
            maxLength={255}
            onBlur={() => setTouched(true)}
            onChange={(event) => setName(event.target.value)}
            ref={nameRef}
            value={name}
          />
        </FormField>
        <FormField
          helperText="Helps teammates pick the right collection when they search."
          htmlFor="collection-edit-description"
          label="Description"
        >
          <Textarea
            id="collection-edit-description"
            maxLength={2000}
            onChange={(event) => setDescription(event.target.value)}
            rows={3}
            value={description}
          />
        </FormField>
      </form>
    </Dialog>
  );
}
