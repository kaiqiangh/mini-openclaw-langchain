import { EmptyState } from "@/components/ui/primitives";

export default function SessionsPage() {
  return (
    <main id="main-content" className="flex min-h-0 flex-1 flex-col p-3">
      <section className="panel-shell flex min-h-0 flex-1 items-center justify-center p-6">
        <EmptyState
          title="Sessions Console Coming Next"
          description="Session search, filters, and transcript review will land in this route as the first dedicated operator workflow."
        />
      </section>
    </main>
  );
}
