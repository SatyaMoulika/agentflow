import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { formatDistanceToNow } from 'date-fns';
export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));
export const uid = (prefix = 'id') => `${prefix}_${crypto.randomUUID().slice(0, 8)}`;
export const relativeTime = (date: string) =>
  formatDistanceToNow(new Date(date), { addSuffix: true });
export const formatDuration = (ms: number) =>
  ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`;
export const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
