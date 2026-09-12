"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowRight,
  BookOpen,
  ChevronRight,
  CircleHelp,
  Database,
  File,
  FileCode2,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileUp,
  FolderKanban,
  LibraryBig,
  LoaderCircle,
  MessageSquare,
  Moon,
  PanelLeftClose,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import {
  type ChangeEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { ProductMark } from "@/components/ui/ProductMark";
import { Dialog } from "@/components/ui/Dialog";
import { appBrand } from "@/lib/brand";
import { isProductNavigationActive, productNavigationItems } from "@/lib/product-navigation";
import {
  getAuthSession,
  hasAnySessionPermission,
  type AuthSession,
} from "@/lib/auth/session";
import { useTheme } from "@/modules/chat/hooks/useTheme";
import {
  createKnowledgeCollection,
  getKnowledgeCollectionWorkspace,
  getKnowledgeHome,
  searchKnowledge,
  uploadKnowledgeCollectionDocument,
} from "../api";
import type {
  KnowledgeCollectionSummary,
  KnowledgeCollectionWorkspace,
  KnowledgeDocumentSummary,
  KnowledgeHome,
  KnowledgeSearchResult,
} from "../types";

interface KnowledgeWorkspaceProps {
  collectionId?: string;
}

export function KnowledgeWorkspace({ collectionId }: KnowledgeWorkspaceProps) {
  const [home, setHome] = useState<KnowledgeHome>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);

  const reloadHome = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(undefined);
    try {
      setHome(await getKnowledgeHome(signal));
    } catch (cause) {
      if (!signal?.aborted) {
        setError(messageFrom(cause, "Could not load your knowledge workspace."));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void reloadHome(controller.signal);
    return () => controller.abort();
  }, [reloadHome]);

  return (
    <div className="knowledge-shell">
      <KnowledgeSidebar
        collections={home?.items ?? []}
        currentCollectionId={collectionId}
        loading={loading}
        personalCollectionId={home?.personal_collection_id}
      />
      <main className="knowledge-main" id="main-content">
        {collectionId ? (
          <CollectionWorkspace
            collectionId={collectionId}
            onCollectionChanged={() => void reloadHome()}
          />
        ) : (
          <KnowledgeHomeView
            error={error}
            home={home}
            loading={loading}
            onRetry={() => void reloadHome()}
          />
        )}
      </main>
    </div>
  );
}

function KnowledgeSidebar({
  collections,
  currentCollectionId,
  loading,
  personalCollectionId,
}: {
  collections: KnowledgeCollectionSummary[];
  currentCollectionId?: string;
  loading: boolean;
  personalCollectionId?: string | null;
}) {
  const { resolvedTheme, theme, toggleTheme } = useTheme();
  const pathname = usePathname();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => setSession(getAuthSession()), []);

  return (
    <aside className={clsx("knowledge-sidebar", collapsed && "knowledge-sidebar--collapsed")}>
      <div className="knowledge-sidebar__brand">
        <Link aria-label={appBrand.productName} className="knowledge-sidebar__brand-link" href="/app">
          <ProductMark decorative size="md" />
          {!collapsed && <span>{appBrand.productName}</span>}
        </Link>
        <button
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Expand knowledge navigation" : "Collapse knowledge navigation"}
          className="knowledge-icon-button knowledge-sidebar__collapse"
          onClick={() => setCollapsed((value) => !value)}
          title={collapsed ? "Expand navigation" : "Collapse navigation"}
          type="button"
        >
          <PanelLeftClose aria-hidden="true" size={16} />
        </button>
      </div>

      <nav aria-label="Workspace" className="knowledge-sidebar__primary-nav">
        {productNavigationItems
          .filter((destination) => !destination.permissionCodes || hasAnySessionPermission(session, destination.permissionCodes))
          .map((destination) => (
            <KnowledgeNavLink
              active={isProductNavigationActive(pathname, destination.href)}
              collapsed={collapsed}
              href={destination.href}
              icon={destination.icon}
              key={destination.label}
              label={destination.label}
            />
          ))}
      </nav>

      {!collapsed && (
        <div className="knowledge-sidebar__collections">
          <p>Knowledge</p>
          <Link className={clsx("knowledge-sidebar__collection-link", !currentCollectionId && "is-active")} href="/knowledge">
            <BookOpen aria-hidden="true" size={15} />
            <span>All collections</span>
          </Link>
          {personalCollectionId ? (
            <Link
              className={clsx("knowledge-sidebar__collection-link", currentCollectionId === personalCollectionId && "is-active")}
              href={`/knowledge/collections/${personalCollectionId}`}
              title="Open your private workspace"
            >
              <FolderKanban aria-hidden="true" size={15} />
              <span>My collection</span>
            </Link>
          ) : (
            <span
              aria-disabled="true"
              className="knowledge-sidebar__collection-link is-unavailable"
              title="Your private workspace appears after you add personal content"
            >
              <FolderKanban aria-hidden="true" size={15} />
              <span>My collection</span>
            </span>
          )}
          <p className="knowledge-sidebar__section-label">Shared with you</p>
          {loading ? (
            <span className="knowledge-sidebar__loading"><LoaderCircle aria-hidden="true" size={14} />Loading collections</span>
          ) : collections.length ? (
            <div className="knowledge-sidebar__collection-list">
              {collections.map((collection) => (
                <Link
                  aria-current={currentCollectionId === collection.id ? "page" : undefined}
                  className={clsx("knowledge-sidebar__collection-link", currentCollectionId === collection.id && "is-active")}
                  href={`/knowledge/collections/${collection.id}`}
                  key={collection.id}
                >
                  <span className="knowledge-sidebar__collection-mark" aria-hidden="true" />
                  <span>{collection.title}</span>
                </Link>
              ))}
            </div>
          ) : (
            <span className="knowledge-sidebar__empty">No collections are available to this account.</span>
          )}
        </div>
      )}

      <div className="knowledge-sidebar__footer">
        {!collapsed && <span>Private to your access</span>}
        <button
          aria-label={`Switch theme (currently ${theme})`}
          className="knowledge-icon-button"
          onClick={toggleTheme}
          title={`Theme: ${theme}`}
          type="button"
        >
          {resolvedTheme === "dark" ? <Moon aria-hidden="true" size={16} /> : <Sun aria-hidden="true" size={16} />}
        </button>
      </div>
    </aside>
  );
}

function KnowledgeNavLink({
  active,
  collapsed,
  href,
  icon: Icon,
  label,
}: {
  active: boolean;
  collapsed: boolean;
  href: string;
  icon: typeof LibraryBig;
  label: string;
}) {
  return (
    <Link aria-current={active ? "page" : undefined} className={clsx("knowledge-nav-link", active && "is-active")} href={href} title={collapsed ? label : undefined}>
      <Icon aria-hidden="true" size={17} />
      {!collapsed && <span>{label}</span>}
    </Link>
  );
}

function KnowledgeHomeView({
  error,
  home,
  loading,
  onRetry,
}: {
  error?: string;
  home?: KnowledgeHome;
  loading: boolean;
  onRetry: () => void;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<KnowledgeSearchResult[]>();
  const [searchError, setSearchError] = useState<string>();
  const [searching, setSearching] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [canManageCollections, setCanManageCollections] = useState(false);

  useEffect(() => {
    setCanManageCollections(
      hasAnySessionPermission(getAuthSession(), ["item.manage"]),
    );
  }, []);

  const submitSearch = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) {
      setResults(undefined);
      setSearchError(undefined);
      return;
    }
    const controller = new AbortController();
    setSearching(true);
    setSearchError(undefined);
    try {
      setResults(await searchKnowledge(query, undefined, controller.signal));
    } catch (cause) {
      if (!controller.signal.aborted) setSearchError(messageFrom(cause, "Could not search knowledge."));
    } finally {
      if (!controller.signal.aborted) setSearching(false);
    }
  };

  if (loading) return <KnowledgeLoading label="Loading your accessible knowledge" />;
  if (error) return <KnowledgeFailure detail={error} onRetry={onRetry} />;

  const collections = home?.items ?? [];
  const resultItems = results ?? [];
  return (
    <div className="knowledge-page knowledge-home">
      <header className="knowledge-header">
        <div>
          <p className="knowledge-eyebrow">Workspace knowledge</p>
          <h1>Knowledge</h1>
          <p>Find trusted content organized around access, source lineage, and ownership.</p>
        </div>
        {canManageCollections && (
          <button className="knowledge-header__action" onClick={() => setCreateOpen(true)} type="button">
            <Plus aria-hidden="true" size={15} />
            New collection
          </button>
        )}
      </header>

      <form className="knowledge-search" onSubmit={(event) => void submitSearch(event)}>
        <Search aria-hidden="true" size={17} />
        <input
          aria-label="Search accessible knowledge"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search knowledge bases, documents, and connected sources…"
          type="search"
          value={query}
        />
        {query && (
          <button aria-label="Clear knowledge search" onClick={() => { setQuery(""); setResults(undefined); }} type="button">
            <X aria-hidden="true" size={15} />
          </button>
        )}
        <button className="knowledge-search__submit" disabled={searching || !query.trim()} type="submit">
          {searching ? <LoaderCircle aria-hidden="true" className="animate-spin" size={15} /> : "Search"}
        </button>
      </form>

      {(results || searchError) && (
        <section aria-label="Knowledge search results" className="knowledge-search-results">
          <div className="knowledge-section-heading">
            <div><p>Search results</p><span>{resultItems.length ? `${resultItems.length} relevant documents` : "No matching documents"}</span></div>
            <button onClick={() => { setResults(undefined); setSearchError(undefined); }} type="button">Clear</button>
          </div>
          {searchError ? <KnowledgeInlineError detail={searchError} /> : resultItems.length ? (
            <div className="knowledge-result-list">
              {resultItems.map((result) => {
                const chunk = result.metadata.chunk_id;
                return (
                  <Link className="knowledge-result-row" href={`/knowledge/items/${result.id}${chunk ? `?chunk=${encodeURIComponent(chunk)}` : ""}`} key={`${result.id}:${chunk ?? ""}`}>
                    <DocumentTypeIcon contentType={undefined} />
                    <span><strong>{result.title}</strong><small>{result.excerpt}</small></span>
                    <ArrowRight aria-hidden="true" size={16} />
                  </Link>
                );
              })}
            </div>
          ) : <KnowledgeEmpty title="No matching documents" detail="Try a more specific phrase or browse a collection below." />}
        </section>
      )}

      <section className="knowledge-overview">
        <div className="knowledge-section-heading">
          <div><p>Your collections</p><span>{collections.length ? `${collections.length} available to your account` : "No collection access yet"}</span></div>
        </div>
        {collections.length ? (
          <div className="knowledge-collection-grid">
            {collections.map((collection) => (
              <button className="knowledge-collection-card" key={collection.id} onClick={() => router.push(`/knowledge/collections/${collection.id}`)} type="button">
                <span className="knowledge-collection-card__icon"><LibraryBig aria-hidden="true" size={19} /></span>
                <span className="knowledge-collection-card__body">
                  <strong>{collection.title}</strong>
                  <small>{collection.description || "Organized knowledge you can search and inspect."}</small>
                </span>
                <span className="knowledge-collection-card__facts">
                  <span>{collection.document_count} {pluralize(collection.document_count, "document")}</span>
                  <span>{collection.source_count} {pluralize(collection.source_count, "source")}</span>
                </span>
                <ChevronRight aria-hidden="true" className="knowledge-collection-card__arrow" size={17} />
              </button>
            ))}
          </div>
        ) : (
          <KnowledgeEmpty title="No knowledge collections are available" detail="Ask a workspace administrator for access to a collection, or add a source through an approved connection." />
        )}
      </section>

      <section className="knowledge-home-bottom">
        <div className="knowledge-recent-card">
          <div className="knowledge-section-heading">
            <div><p>Recently updated</p><span>Changes from sources you can access</span></div>
          </div>
          {home?.recent_documents.length ? (
            <div className="knowledge-recent-list">
              {home.recent_documents.map((document) => <DocumentCompactRow document={document} key={document.id} />)}
            </div>
          ) : <KnowledgeEmpty compact title="Nothing has been indexed yet" detail="New or updated source documents will appear here." />}
        </div>
        <aside className="knowledge-trust-card">
          <ShieldCheck aria-hidden="true" size={19} />
          <strong>Permission-aware knowledge</strong>
          <p>Collections, document rows, search results, and source views are filtered before they reach this workspace.</p>
          <Link href="/app"><MessageSquare aria-hidden="true" size={14} />Ask across your knowledge</Link>
        </aside>
      </section>
      <KnowledgeCollectionCreateDialog
        onClose={() => setCreateOpen(false)}
        onCreated={(collectionId) => router.push(`/knowledge/collections/${collectionId}`)}
        open={createOpen}
      />
    </div>
  );
}

function KnowledgeCollectionCreateDialog({
  onClose,
  onCreated,
  open,
}: {
  onClose: () => void;
  onCreated: (collectionId: string) => void;
  open: boolean;
}) {
  const titleRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  const trimmedTitle = title.trim();

  const close = () => {
    if (submitting) return;
    setTitle("");
    setDescription("");
    setError(undefined);
    onClose();
  };

  const createCollection = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!trimmedTitle || submitting) {
      titleRef.current?.focus();
      return;
    }
    setSubmitting(true);
    setError(undefined);
    try {
      const collection = await createKnowledgeCollection({
        title: trimmedTitle,
        description,
      });
      setTitle("");
      setDescription("");
      onClose();
      onCreated(collection.id);
    } catch (cause) {
      setError(messageFrom(cause, "Could not create this collection."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      className="knowledge-create-dialog"
      footer={
        <>
          <button className="knowledge-dialog__secondary-action" disabled={submitting} onClick={close} type="button">Cancel</button>
          <button className="knowledge-dialog__primary-action" disabled={!trimmedTitle || submitting} form="knowledge-create-form" type="submit">
            {submitting ? <LoaderCircle aria-hidden="true" className="animate-spin" size={15} /> : <Plus aria-hidden="true" size={15} />}
            Create collection
          </button>
        </>
      }
      initialFocusRef={titleRef}
      onClose={close}
      open={open}
      title="Create collection"
    >
      <form className="knowledge-create-form" id="knowledge-create-form" onSubmit={(event) => void createCollection(event)}>
        <p>Start a governed space for a team, topic, or trusted source. You can add content as soon as it is created.</p>
        {error && <KnowledgeInlineError detail={error} id="knowledge-collection-error" />}
        <label htmlFor="knowledge-collection-title">Name <span aria-hidden="true">*</span></label>
        <input
          aria-describedby={error ? "knowledge-collection-error" : undefined}
          autoComplete="off"
          id="knowledge-collection-title"
          maxLength={255}
          onChange={(event) => {
            setTitle(event.target.value);
            if (error) setError(undefined);
          }}
          placeholder="Product handbook"
          ref={titleRef}
          required
          value={title}
        />
        <label htmlFor="knowledge-collection-description">Description <small>Optional</small></label>
        <textarea
          id="knowledge-collection-description"
          maxLength={2_000}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Guides, policies, and operating knowledge for your team."
          rows={3}
          value={description}
        />
      </form>
    </Dialog>
  );
}

function CollectionWorkspace({
  collectionId,
  onCollectionChanged,
}: {
  collectionId: string;
  onCollectionChanged: () => void;
}) {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [workspace, setWorkspace] = useState<KnowledgeCollectionWorkspace>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>();
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string>();

  const loadWorkspace = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(undefined);
    try {
      const next = await getKnowledgeCollectionWorkspace(collectionId, {
        search: activeQuery,
        signal,
      });
      setWorkspace(next);
      setSelectedDocumentId((current) => (
        next.documents.some((document) => document.id === current)
          ? current
          : next.documents[0]?.id
      ));
    } catch (cause) {
      if (!signal?.aborted) setError(messageFrom(cause, "Could not open this collection."));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [activeQuery, collectionId]);

  useEffect(() => {
    const controller = new AbortController();
    void loadWorkspace(controller.signal);
    return () => controller.abort();
  }, [loadWorkspace]);

  const onUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    setUploading(true);
    setUploadError(undefined);
    try {
      for (const file of files) await uploadKnowledgeCollectionDocument(collectionId, file);
      await loadWorkspace();
      onCollectionChanged();
    } catch (cause) {
      setUploadError(messageFrom(cause, "Could not add that content to this collection."));
    } finally {
      setUploading(false);
    }
  };

  if (loading) return <KnowledgeLoading label="Opening collection" />;
  if (error || !workspace) return <KnowledgeFailure detail={error || "Collection not found."} onRetry={() => void loadWorkspace()} />;

  const selectedDocument = workspace.documents.find((document) => document.id === selectedDocumentId);
  return (
    <div className="knowledge-page knowledge-collection-page">
      <header className="knowledge-header knowledge-header--collection">
        <div>
          <nav aria-label="Breadcrumb" className="knowledge-breadcrumb"><Link href="/knowledge">Knowledge</Link><ChevronRight aria-hidden="true" size={13} /><span>{workspace.collection.title}</span></nav>
          <h1>{workspace.collection.title}</h1>
          <p>{workspace.collection.description || "A governed collection of trusted knowledge."}</p>
          <span className="knowledge-header__meta">{workspace.collection.document_count} {pluralize(workspace.collection.document_count, "document")} · {workspace.collection.source_count} {pluralize(workspace.collection.source_count, "connected source")}</span>
        </div>
        <div className="knowledge-header__actions">
          <Link className="knowledge-header__subtle-action" href={`/app?collection=${encodeURIComponent(collectionId)}&message=${encodeURIComponent(`Help me understand the knowledge in ${workspace.collection.title}.`)}`}>
            <Sparkles aria-hidden="true" size={15} />Ask with this knowledge
          </Link>
          <button className="knowledge-header__action" disabled={uploading} onClick={() => fileInputRef.current?.click()} type="button">
            {uploading ? <LoaderCircle aria-hidden="true" className="animate-spin" size={15} /> : <Plus aria-hidden="true" size={15} />}
            Add content
          </button>
          <input accept=".avif,.bmp,.csv,.docx,.gif,.htm,.html,.jpeg,.jpg,.json,.jsonl,.log,.markdown,.md,.pdf,.png,.pptx,.rst,.sql,.tif,.tiff,.tsv,.txt,.webp,.xlsx,.xml,.yaml,.yml" hidden multiple onChange={(event) => void onUpload(event)} ref={fileInputRef} type="file" />
        </div>
      </header>

      {uploadError && <KnowledgeInlineError detail={uploadError} />}
      <div className="knowledge-collection-layout">
        <aside className="knowledge-collection-tree">
          <div className="knowledge-collection-tree__heading"><span>Collection structure</span><span aria-label="Items appear only when you can access them" className="knowledge-information-icon" title="Items appear only when you can access them"><CircleHelp aria-hidden="true" size={14} /></span></div>
          <span className="knowledge-tree-item is-current"><LibraryBig aria-hidden="true" size={15} /><span>{workspace.collection.title}</span></span>
          {workspace.child_collections.map((child) => (
            <Link className="knowledge-tree-item knowledge-tree-item--child" href={`/knowledge/collections/${child.id}`} key={child.id}><ChevronRight aria-hidden="true" size={13} /><FolderKanban aria-hidden="true" size={14} /><span>{child.title}</span></Link>
          ))}
          <div className="knowledge-collection-tree__sources">
            <span>Connected sources</span>
            <SourceList documents={workspace.documents} />
          </div>
        </aside>

        <section aria-label="Collection documents" className="knowledge-document-panel">
          <div className="knowledge-document-panel__topline">
            <div><p>All content</p><span>{activeQuery ? `Results for “${activeQuery}”` : `${workspace.total} ${pluralize(workspace.total, "document")}`}</span></div>
            <form className="knowledge-inline-search" onSubmit={(event) => { event.preventDefault(); setActiveQuery(query.trim()); }}>
              <Search aria-hidden="true" size={14} />
              <input aria-label="Filter documents in this collection" onChange={(event) => setQuery(event.target.value)} placeholder="Filter documents…" type="search" value={query} />
              {query && <button aria-label="Clear document filter" onClick={() => { setQuery(""); setActiveQuery(""); }} type="button"><X aria-hidden="true" size={13} /></button>}
            </form>
          </div>
          <div className="knowledge-document-columns" aria-hidden="true"><span>Document</span><span>Source</span><span>Updated</span></div>
          {workspace.documents.length ? (
            <div className="knowledge-document-list" role="listbox" aria-label="Documents in this collection">
              {workspace.documents.map((document) => (
                <button
                  aria-selected={selectedDocument?.id === document.id}
                  className={clsx("knowledge-document-row", selectedDocument?.id === document.id && "is-selected")}
                  key={document.id}
                  onClick={() => setSelectedDocumentId(document.id)}
                  role="option"
                  type="button"
                >
                  <DocumentTypeIcon contentType={document.content_type} />
                  <span className="knowledge-document-row__name"><strong>{document.title}</strong><small>{document.document_type ? displayDocumentType(document.document_type) : "Document"} · <StatusLabel status={document.status} /></small></span>
                  <span className="knowledge-document-row__source">{document.source?.display_name || "Uploaded content"}</span>
                  <time dateTime={document.updated_at}>{relativeTime(document.updated_at)}</time>
                </button>
              ))}
            </div>
          ) : <KnowledgeEmpty title={activeQuery ? "No documents match this filter" : "This collection is empty"} detail={activeQuery ? "Try a different title or clear the filter." : "Add a supported file or connect an approved source to start building this collection."} />}
        </section>

        <aside aria-label="Selected document details" className="knowledge-document-inspector">
          {selectedDocument ? <DocumentInspector document={selectedDocument} onOpen={() => router.push(`/knowledge/items/${selectedDocument.id}`)} /> : <KnowledgeEmpty compact title="Select a document" detail="Choose a document to inspect its source, lifecycle, and content." />}
        </aside>
      </div>
    </div>
  );
}

function DocumentInspector({ document, onOpen }: { document: KnowledgeDocumentSummary; onOpen: () => void }) {
  return (
    <div className="knowledge-inspector-card">
      <div className="knowledge-inspector-card__title"><DocumentTypeIcon contentType={document.content_type} /><div><strong>{document.title}</strong><span><StatusLabel status={document.status} /></span></div></div>
      <button className="knowledge-inspector-card__open" onClick={onOpen} type="button"><FileText aria-hidden="true" size={15} />Open document</button>
      <dl>
        <div><dt>Source</dt><dd>{document.source?.display_name || "Native upload"}</dd></div>
        <div><dt>Type</dt><dd>{document.document_type ? displayDocumentType(document.document_type) : document.content_type || "Document"}</dd></div>
        <div><dt>Updated</dt><dd>{formatDate(document.updated_at)}</dd></div>
        {document.source?.source_url && <div><dt>Origin</dt><dd><a href={document.source.source_url} rel="noopener noreferrer" target="_blank">Open source <ArrowRight aria-hidden="true" size={12} /></a></dd></div>}
      </dl>
      <div className="knowledge-inspector-card__notice"><ShieldCheck aria-hidden="true" size={15} /><span>Source access is checked again when you open or cite this document.</span></div>
    </div>
  );
}

function SourceList({ documents }: { documents: KnowledgeDocumentSummary[] }) {
  const sources = [...new Map(
    documents
      .filter((document) => document.source)
      .map((document) => [document.source!.display_name, document.source!]),
  ).values()];
  if (!sources.length) return <span className="knowledge-collection-tree__empty">No external sources in this collection.</span>;
  return <div>{sources.map((source) => <span className="knowledge-source-row" key={source.display_name}><Database aria-hidden="true" size={13} />{source.display_name}</span>)}</div>;
}

function DocumentCompactRow({ document }: { document: KnowledgeDocumentSummary }) {
  return (
    <Link className="knowledge-compact-document" href={`/knowledge/items/${document.id}`}>
      <DocumentTypeIcon contentType={document.content_type} />
      <span><strong>{document.title}</strong><small>{document.source?.display_name || "Uploaded content"} · {relativeTime(document.updated_at)}</small></span>
      <ChevronRight aria-hidden="true" size={15} />
    </Link>
  );
}

function DocumentTypeIcon({ contentType }: { contentType?: string | null }) {
  const normalized = contentType?.toLowerCase() || "";
  const Icon = normalized.includes("spreadsheet") || normalized.includes("csv") ? FileSpreadsheet
    : normalized.startsWith("image/") ? FileImage
    : normalized.includes("json") || normalized.includes("xml") || normalized.includes("markdown") ? FileCode2
    : normalized.includes("pdf") || normalized.includes("word") || normalized.includes("presentation") ? FileText
    : File;
  return <span aria-hidden="true" className="knowledge-document-icon"><Icon size={17} /></span>;
}

function StatusLabel({ status }: { status: KnowledgeDocumentSummary["status"] }) {
  const label = status === "ready" ? "Ready" : status === "processing" ? "Processing" : status === "pending" ? "Pending" : status === "failed" ? "Needs attention" : "Unsupported";
  return <span className={clsx("knowledge-status", `knowledge-status--${status}`)}>{label}</span>;
}

function KnowledgeLoading({ label }: { label: string }) {
  return <div aria-busy="true" className="knowledge-state" role="status"><LoaderCircle aria-hidden="true" className="animate-spin" size={20} /><strong>{label}</strong><span>Checking your workspace permissions and source availability.</span></div>;
}

function KnowledgeFailure({ detail, onRetry }: { detail: string; onRetry: () => void }) {
  return <div className="knowledge-state knowledge-state--error" role="alert"><ShieldCheck aria-hidden="true" size={20} /><strong>Knowledge workspace unavailable</strong><span>{detail}</span><button onClick={onRetry} type="button">Try again</button></div>;
}

function KnowledgeInlineError({ detail, id }: { detail: string; id?: string }) {
  return <div className="knowledge-inline-error" id={id} role="alert"><CircleHelp aria-hidden="true" size={15} /><span>{detail}</span></div>;
}

function KnowledgeEmpty({ compact = false, detail, title }: { compact?: boolean; detail: string; title: string }) {
  return <div className={clsx("knowledge-empty", compact && "knowledge-empty--compact")}><LibraryBig aria-hidden="true" size={compact ? 17 : 22} /><strong>{title}</strong><p>{detail}</p></div>;
}

function pluralize(value: number, singular: string) {
  return `${singular}${value === 1 ? "" : "s"}`;
}

function messageFrom(cause: unknown, fallback: string) {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

function relativeTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recently";
  const difference = Date.now() - date.getTime();
  if (difference < 60_000) return "Just now";
  if (difference < 3_600_000) return `${Math.floor(difference / 60_000)}m ago`;
  if (difference < 86_400_000) return `${Math.floor(difference / 3_600_000)}h ago`;
  if (difference < 7 * 86_400_000) return `${Math.floor(difference / 86_400_000)}d ago`;
  return formatDate(value);
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" }).format(date);
}

function displayDocumentType(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
