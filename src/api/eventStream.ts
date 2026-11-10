/** Read SSE sequence IDs across chunk boundaries without interpreting event payloads. */
export class EventCursor {
  private buffer = '';
  constructor(public id = '0') {}

  push(chunk: string): boolean {
    this.buffer += chunk;
    if (this.buffer.length > 262144) throw new Error('Event stream frame too large');
    let received = false;
    let boundary = this.buffer.indexOf('\n\n');
    while (boundary >= 0) {
      const frame = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const id = frame
        .split('\n')
        .find((line) => line.startsWith('id: '))
        ?.slice(4);
      if (
        id &&
        /^\d{1,19}$/.test(id) &&
        BigInt(id) <= 9223372036854775807n &&
        BigInt(id) > BigInt(this.id)
      ) {
        this.id = id;
        received = true;
      }
      boundary = this.buffer.indexOf('\n\n');
    }
    return received;
  }
}
