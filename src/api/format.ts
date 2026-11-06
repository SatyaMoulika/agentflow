export function date(value: string | null) {
  return value ? new Date(value).toLocaleString() : '—';
}
export function elapsed(start: string | null, end: string | null) {
  return start && end
    ? `${Math.max(0, new Date(end).getTime() - new Date(start).getTime()).toLocaleString()} ms`
    : '—';
}
