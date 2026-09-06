"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { useToast } from "@/components/ui/Toast";
import { adminRequest } from "@/modules/admin/api";
import { errorMessage } from "@/modules/admin/format";

const FORM_ID = "collection-create-form";

interface CreatedCollection {
  id: string;
  title: string;
}

/**
 * Creating a collection asks for the two things that make it findable and
 * nothing else. Access, sources and content all follow on the collection page,
 * where there is something to attach them to.
 */
export function CollectionCreateDialog({
  open,
  onClose,
  onCreated,
  /** Skips the redirect when the caller stays on the page it created from. */
  stayOnPage = false,
}: {
  open: boolean;
  onClose: () => void;
  onCreated?: (collection: CreatedCollection) => void;
  stayOnPage?: boolean;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const nameRef = useRef<HTMLInputElement | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [templateLibrary, setTemplateLibrary] = useState(false);
  const [touched, setTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const trimmedName = name.trim();
  const nameError =
    touched && !trimmedName ? "Give this collection a name." : undefined;

  function reset() {
    setName("");
    setDescription("");
    setTemplateLibrary(false);
    setTouched(false);
    setSubmitError(null);
  }

  function requestClose() {
    if (submitting) return;
    reset();
    onClose();
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setTouched(true);
    if (!trimmedName) {
      nameRef.current?.focus();
      return;
    }

    setSubmitting(true);
    setSubmitError(null);
    try {
      const collection = await adminRequest<CreatedCollection>("/collections", {
        method: "POST",
        body: JSON.stringify({
          title: trimmedName,
          inherit_access: true,
          metadata: {
            ...(description.trim() ? { description: description.trim() } : {}),
            ...(templateLibrary ? { template_library: true } : {}),
          },
        }),
      });
      toast({
        title: `${collection.title} created`,
        description: "Add files or connect a source to fill it.",
        variant: "success",
      });
      onCreated?.(collection);
      reset();
      onClose();
      if (!stayOnPage) router.push(`/admin/collections/${collection.id}`);
    } catch (error) {
      setSubmitError(errorMessage(error, "The collection could not be created."));
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;

  return (
    <Dialog
      className="max-w-lg"
      footer={
        <>
          <Button disabled={submitting} onClick={requestClose} variant="secondary">
            Cancel
          </Button>
          <Button
            disabled={!trimmedName}
            form={FORM_ID}
            loading={submitting}
            type="submit"
          >
            Create collection
          </Button>
        </>
      }
      initialFocusRef={nameRef}
      onClose={requestClose}
      open
      title="Create collection"
    >
      <form className="space-y-4" id={FORM_ID} onSubmit={submit}>
        <p className="text-[0.8125rem] leading-5 text-[var(--text-muted)]">
          A collection groups related knowledge so the assistant answers from the
          right material. You can add content straight after.
        </p>
        {submitError && <ErrorState description={submitError} layout="inline" />}
        <FormField
          error={nameError}
          htmlFor="collection-name"
          label="Name"
          required
        >
          <Input
            aria-describedby={nameError ? "collection-name-error" : undefined}
            autoComplete="off"
            error={Boolean(nameError)}
            id="collection-name"
            maxLength={255}
            onBlur={() => setTouched(true)}
            onChange={(event) => {
              setName(event.target.value);
              if (submitError) setSubmitError(null);
            }}
            placeholder="Product handbook"
            ref={nameRef}
            value={name}
          />
        </FormField>
        <FormField
          helperText="Helps teammates pick the right collection when they search."
          htmlFor="collection-description"
          label="Description"
        >
          <Textarea
            id="collection-description"
            maxLength={2000}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Onboarding guides, policies and how-to articles for the product team."
            rows={3}
            value={description}
          />
        </FormField>
        <label className="flex items-start gap-2 text-[0.8125rem] leading-5 text-[var(--text)]" htmlFor="collection-template-library">
          <input
            checked={templateLibrary}
            className="mt-1"
            id="collection-template-library"
            onChange={(event) => setTemplateLibrary(event.target.checked)}
            type="checkbox"
          />
          <span>
            <span className="block font-medium">Template library</span>
            <span className="block text-[var(--text-muted)]">
              Documents here are offered as templates when the assistant drafts a
              document, and users can publish their drafts into it.
            </span>
          </span>
        </label>
      </form>
    </Dialog>
  );
}
