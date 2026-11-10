import { describe, expect, it } from 'vitest';
import { EventCursor } from '../src/api/eventStream';

describe('event stream cursor', () => {
  it('handles split frames, heartbeats, duplicates and reconnect cursors', () => {
    const cursor = new EventCursor('3');
    expect(cursor.push(': heartbeat\n\nid: ')).toBe(false);
    expect(cursor.push('4\nevent: execution\ndata: {}\n')).toBe(false);
    expect(cursor.push('\nid: 4\ndata: {}\n\nid: 5\ndata: {}\n\n')).toBe(true);
    expect(cursor.id).toBe('5');
    const reconnect = new EventCursor(cursor.id);
    expect(reconnect.push('id: 5\ndata: {}\n\n')).toBe(false);
    expect(reconnect.push('id: 6\ndata: {}\n\n')).toBe(true);
    expect(reconnect.id).toBe('6');
  });

  it('ignores malformed or out-of-range IDs and bounds incomplete frames', () => {
    const cursor = new EventCursor('0');
    expect(cursor.push('id: secret\ndata: {}\n\nid: 9223372036854775808\ndata: {}\n\n')).toBe(false);
    expect(cursor.id).toBe('0');
    expect(() => cursor.push('x'.repeat(262145))).toThrow('frame too large');
  });
});
