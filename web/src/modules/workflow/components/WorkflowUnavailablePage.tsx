import Link from "next/link";
import { Workflow } from "lucide-react";

export function WorkflowUnavailablePage() {
  return (
    <main className="min-h-dvh bg-slate-50 p-6 text-slate-900">
      <section className="mx-auto flex w-full max-w-3xl flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-slate-200 bg-white px-8 py-24 text-center">
        <Workflow className="h-9 w-9 text-slate-300" />
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Workflows are not connected yet</h1>
          <p className="mt-2 max-w-xl text-sm leading-6 text-slate-500">
            The current BoThesis backend does not expose workflow authoring or execution APIs. This route stays available without creating local mock workflows.
          </p>
        </div>
        <Link className="inline-flex h-9 items-center rounded-md bg-teal-700 px-3 text-sm font-medium text-white hover:bg-teal-800" href="/app">
          Return to knowledge chat
        </Link>
      </section>
    </main>
  );
}
