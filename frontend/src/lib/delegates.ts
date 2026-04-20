import { type DelegateDetail, type DelegateSummary } from "@/lib/api";

export type DelegateViewModel = DelegateSummary & {
  detail?: DelegateDetail;
};

export function shouldPollDelegates(args: {
  isStreaming: boolean;
  delegates: DelegateSummary[];
  detailById: Record<string, DelegateDetail>;
  hydrated: boolean;
}): boolean {
  if (args.isStreaming) return true;
  if (!args.hydrated) return true;
  if (args.delegates.some((delegate) => delegate.status === "running")) {
    return true;
  }
  return args.delegates.some(
    (delegate) =>
      delegate.status !== "running" &&
      !args.detailById[delegate.delegate_id],
  );
}

export function buildDelegateViewModels(
  delegates: DelegateSummary[],
  detailById: Record<string, DelegateDetail>,
): DelegateViewModel[] {
  return delegates.map((delegate) => ({
    ...delegate,
    detail: detailById[delegate.delegate_id],
  }));
}
