export interface SequencedStreamEvent {
  sequence_number?: number;
}

export class StreamEventDeduplicator {
  private highestSequence = 0;

  shouldAccept(event: SequencedStreamEvent): boolean {
    if (
      event.sequence_number !== undefined
      && event.sequence_number <= this.highestSequence
    ) return false;
    if (event.sequence_number !== undefined) this.highestSequence = event.sequence_number;
    return true;
  }
}
