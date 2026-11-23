/** The Decisions page with one decision selected (list filters stay as they are). The proposal id is the `d` parameter the queue reads. */
export const decisionHref = (proposalId: string): string => `/?d=${encodeURIComponent(proposalId)}`;

/** The full page of one decision. */
export const decisionPageHref = (proposalId: string): string =>
  `/decisions/${encodeURIComponent(proposalId)}`;
