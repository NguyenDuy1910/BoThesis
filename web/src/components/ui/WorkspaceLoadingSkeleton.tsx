export function WorkspaceLoadingSkeleton() {
  return (
    <section
      aria-busy="true"
      aria-label="Loading workspace"
      className="workspace-loading"
      role="status"
    >
      <span className="sr-only">Loading workspace</span>
      <div className="workspace-loading__inner">
        <div className="workspace-loading__topbar" aria-hidden="true">
          <span className="workspace-loading__line workspace-loading__line--eyebrow" />
          <span className="workspace-loading__line workspace-loading__line--title" />
        </div>
        <div className="workspace-loading__transcript" aria-hidden="true">
          <div className="workspace-loading__user">
            <span className="workspace-loading__line workspace-loading__line--user" />
            <span className="workspace-loading__line workspace-loading__line--user-short" />
          </div>
          <div className="workspace-loading__assistant">
            <span className="workspace-loading__line workspace-loading__line--assistant" />
            <span className="workspace-loading__line workspace-loading__line--assistant" />
            <span className="workspace-loading__line workspace-loading__line--assistant-short" />
          </div>
        </div>
        <div className="workspace-loading__composer" aria-hidden="true">
          <span className="workspace-loading__line workspace-loading__line--composer" />
          <div className="workspace-loading__composer-footer">
            <span className="workspace-loading__line workspace-loading__line--control" />
            <span className="workspace-loading__line workspace-loading__line--control-wide" />
            <span className="workspace-loading__line workspace-loading__line--send" />
          </div>
        </div>
      </div>
    </section>
  );
}
