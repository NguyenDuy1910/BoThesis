export interface SequencedStreamEvent {
  event_id?: string;
  sequence?: number;
}

export class StreamEventDeduplicator {
  private readonly seenEventIds = new Set<string>();
  private highestSequence = 0;

  shouldAccept(event: SequencedStreamEvent): boolean {
    if (event.event_id && this.seenEventIds.has(event.event_id)) return false;
    if (event.sequence !== undefined && event.sequence <= this.highestSequence) return false;
    if (event.event_id) this.seenEventIds.add(event.event_id);
    if (event.sequence !== undefined) this.highestSequence = event.sequence;
    return true;
  }
}
