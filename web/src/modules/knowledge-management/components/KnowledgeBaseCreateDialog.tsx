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

const FORM_ID = "knowledge-base-create-form";

export function KnowledgeBaseCreateDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (knowledgeBase: KnowledgeItem) => void;
}) {
  const { toast } = useToast();
  const nameRef = useRef<HTMLInputElement | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const normalizedName = name.trim();
  const nameError = nameTouched && !normalizedName
    ? "Enter a name for this knowledge base."
    : undefined;

  function requestClose() {
    if (!submitting) onClose();
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setNameTouched(true);
    if (!normalizedName) {
      nameRef.current?.focus();
      return;
    }

    setSubmitting(true);
    setSubmitError(null);
    try {
      const knowledgeBase = await adminRequest<KnowledgeItem>("/collections", {
        method: "POST",
        body: JSON.stringify({
          title: normalizedName,
          inherit_access: true,
          metadata: description.trim()
            ? { description: description.trim() }
            : {},
        }),
      });
      toast({
        title: "Knowledge base created",
        description: `${knowledgeBase.title} is ready for content.`,
        variant: "success",
      });
      onCreated(knowledgeBase);
    } catch (error) {
      setSubmitError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      className="max-w-xl"
      footer={(
        <>
          <Button disabled={submitting} onClick={requestClose} variant="secondary">
            Cancel
          </Button>
          <Button
            disabled={!normalizedName}
            form={FORM_ID}
            loading={submitting}
            type="submit"
          >
            Create knowledge base
          </Button>
        </>
      )}
      initialFocusRef={nameRef}
      onClose={requestClose}
      open
      title="Create knowledge base"
    >
      <form className="space-y-4" id={FORM_ID} onSubmit={submit}>
        <p className="text-sm leading-6 text-[var(--text-muted)]">
          Your empty knowledge base will be created immediately. You can upload
          files, add items manually, or connect a source afterward.
        </p>
        {submitError && (
          <div
            className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-soft)] px-3 py-2.5 text-sm leading-5 text-[var(--danger-text)]"
            role="alert"
          >
            <strong className="block font-semibold">Knowledge base could not be created</strong>
            <span className="mt-0.5 block">{submitError}</span>
          </div>
        )}
        <FormField
          error={nameError}
          htmlFor="knowledge-base-name"
          label="Knowledge base name"
          required
        >
          <Input
            aria-describedby={nameError ? "knowledge-base-name-error" : undefined}
            autoComplete="off"
            error={Boolean(nameError)}
            id="knowledge-base-name"
            maxLength={255}
            onBlur={() => setNameTouched(true)}
            onChange={(event) => {
              setName(event.target.value);
              if (submitError) setSubmitError(null);
            }}
            placeholder="For example, Product handbook"
            ref={nameRef}
            value={name}
          />
        </FormField>
        <FormField
          helperText={`${description.length.toLocaleString()} of 2,000 characters`}
          htmlFor="knowledge-base-description"
          label="Description"
        >
          <Textarea
            aria-describedby="knowledge-base-description-helper"
            id="knowledge-base-description"
            maxLength={2_000}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What knowledge belongs here?"
            rows={4}
            value={description}
          />
        </FormField>
      </form>
    </Dialog>
  );
}
