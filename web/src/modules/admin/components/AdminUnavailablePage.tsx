import { DatabaseZap } from "lucide-react";

export function AdminUnavailablePage() {
  return (
    <section className="mx-auto flex min-h-full w-full max-w-3xl flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-slate-200 bg-white px-8 py-24 text-center">
      <DatabaseZap className="h-9 w-9 text-slate-300" />
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Administration is not connected yet</h1>
        <p className="mt-2 max-w-xl text-sm leading-6 text-slate-500">
          BoThesis does not yet expose administration APIs for connectors, documents, permissions, or audit data. These routes remain inactive until those backend contracts are available.
        </p>
      </div>
    </section>
  );
}
