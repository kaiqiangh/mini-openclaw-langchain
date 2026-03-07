import { EmptyState } from "@/components/ui/primitives";

export default function RunsPage() {
  return (
    <main id="main-content" className="flex min-h-0 flex-1 flex-col p-3">
      <section className="panel-shell flex min-h-0 flex-1 items-center justify-center p-6">
        <EmptyState
          title="Runs Ledger Coming Next"
          description="This route will unify chat, cron, heartbeat, and usage-linked run inspection behind one dense operator view."
        />
      </section>
    </main>
  );
}
