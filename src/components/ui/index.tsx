import { forwardRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Slot } from '@radix-ui/react-slot';
import * as Dialog from '@radix-ui/react-dialog';
import { cva } from 'class-variance-authority';
import { Check, CheckCircle2, CircleAlert, Copy, Inbox, Loader2, Search, X } from 'lucide-react';
import { cn } from '../../lib/utils';
const buttonVariants = cva('button', {
  variants: {
    variant: {
      primary: 'button-primary',
      secondary: 'button-secondary',
      ghost: 'button-ghost',
      danger: 'button-danger',
    },
    size: { sm: 'button-sm', md: '' },
  },
  defaultVariants: { variant: 'secondary', size: 'md' },
});
interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md';
  loading?: boolean;
  asChild?: boolean;
}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = 'secondary', size = 'md', loading, children, asChild, ...props },
  ref,
) {
  const Comp = asChild ? Slot : 'button';
  return (
    <Comp
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
      disabled={asChild ? undefined : loading || props.disabled}
      aria-disabled={loading || props.disabled || undefined}
      onClick={loading || props.disabled ? (event) => event.preventDefault() : props.onClick}
    >
      {asChild ? (
        children
      ) : (
        <>
          {loading && <Loader2 size={15} className="spin" />}
          {children}
        </>
      )}
    </Comp>
  );
});
const statusLabels: Record<string, string> = {
  waiting_approval: 'Awaiting approval',
  succeeded: 'Succeeded',
  active: 'Active',
  draft: 'Draft',
  paused: 'Paused',
  failed: 'Failed',
  running: 'Running',
  queued: 'Queued',
  cancelled: 'Cancelled',
  approved: 'Approved',
  rejected: 'Rejected',
  pending: 'Pending',
  archived: 'Archived',
  expired: 'Expired',
  skipped: 'Skipped',
  connected: 'Connected',
  disconnected: 'Not connected',
};
export function Badge({
  status,
  children,
  className,
}: {
  status: string;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <span className={cn('badge', `badge-${status}`, className)}>
      <span className="status-dot" />
      {children || statusLabels[status] || status.replaceAll('_', ' ')}
    </span>
  );
}
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}
export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon || <Inbox size={28} />}</div>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content className="modal-content" aria-describedby={undefined}>
          <div className="modal-heading">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close asChild>
              <button className="icon-button" aria-label="Close dialog">
                <X size={18} />
              </button>
            </Dialog.Close>
          </div>
          <div className="modal-body">{children}</div>
          {footer && <div className="modal-footer">{footer}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = 'Confirm',
  danger = false,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: string;
  confirmLabel?: string;
  danger?: boolean;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant={danger ? 'danger' : 'primary'}
            onClick={() => {
              onConfirm();
              onClose();
            }}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="muted">{description}</p>
    </Modal>
  );
}
export function SearchInput({
  value,
  onChange,
  placeholder = 'Search…',
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="search-input">
      <Search size={16} />
      <input
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {value && (
        <button aria-label="Clear search" onClick={() => onChange('')}>
          <X size={14} />
        </button>
      )}
    </div>
  );
}
export function JsonViewer({ data }: { data: unknown }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2) ?? 'null');
      setCopied(true);
      setCopyError(false);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopyError(true);
    }
  };
  return (
    <div className="json-viewer">
      <button className="json-copy icon-button" aria-label="Copy JSON" onClick={copy}>
        {copied ? <Check size={15} /> : <Copy size={15} />}
      </button>
      <pre>{data === null ? 'Output is not available yet.' : JSON.stringify(data, null, 2)}</pre>
      {copyError && (
        <p className="copy-error" role="status">
          Clipboard access is unavailable. Select the JSON text to copy it.
        </p>
      )}
    </div>
  );
}
export function LoadingSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-label="Loading" className="skeleton-stack">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" />
      ))}
    </div>
  );
}
export function ErrorState({
  title = 'Unable to load this view',
  description,
  action,
}: {
  title?: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <EmptyState icon={<CircleAlert />} title={title} description={description} action={action} />
  );
}
export function UserAvatar({
  name = 'Moulika',
  size = 'md',
}: {
  name?: string;
  size?: 'sm' | 'md';
}) {
  return (
    <span className={cn('avatar', size === 'sm' && 'avatar-sm')}>
      {name
        .split(' ')
        .map((n) => n[0])
        .join('')
        .slice(0, 2)
        .toUpperCase()}
    </span>
  );
}
export function Toasts({
  toasts,
  dismiss,
}: {
  toasts: { id: string; message: string; type: string }[];
  dismiss: (id: string) => void;
}) {
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((t) => (
        <div className={cn('toast', `toast-${t.type}`)} key={t.id}>
          {t.type === 'success' ? (
            <CheckCircle2 size={18} />
          ) : t.type === 'error' ? (
            <CircleAlert size={18} />
          ) : (
            <Inbox size={18} />
          )}
          <span>{t.message}</span>
          <button
            className="icon-button"
            aria-label="Dismiss notification"
            onClick={() => dismiss(t.id)}
          >
            <X size={15} />
          </button>
        </div>
      ))}
    </div>
  );
}
