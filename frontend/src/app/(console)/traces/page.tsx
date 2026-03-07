import { EmptyState } from "@/components/ui/primitives";

export default function TracesPage() {
  return (
    <main id="main-content" className="flex min-h-0 flex-1 flex-col p-3">
      <section className="panel-shell flex min-h-0 flex-1 items-center justify-center p-6">
        <EmptyState
          title="Trace Explorer Pending Backend Read APIs"
          description="The dedicated trace explorer depends on persisted run and audit read endpoints. This placeholder keeps the route and navigation stable while that work lands."
        />
      </section>
    </main>
  );
}
