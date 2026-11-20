import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'
import { AlertCircle, Check, ChevronDown, Info, LoaderCircle, X } from 'lucide-react'
import type { ToastMessage } from '../../types'
import { cn } from '../../utils/cn'

export function GlassCard({ children, className = '', ...props }: React.HTMLAttributes<HTMLDivElement>) { return <div className={cn('glass-card', className)} {...props}>{children}</div> }
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; size?: 'sm' | 'md'; loading?: boolean }
export function Button({ variant = 'secondary', size = 'md', className = '', loading = false, disabled, children, ...props }: ButtonProps) { return <button className={cn('button', `button-${variant}`, `button-${size}`, className)} {...props} disabled={loading || disabled} aria-busy={loading || undefined}>{loading && <LoaderCircle className="button-loading-spinner" size={15} aria-hidden="true"/>}{children}</button> }
export function Input({ className = '', ...props }: InputHTMLAttributes<HTMLInputElement>) { return <input className={cn('input', className)} {...props} /> }
export function Select({ className = '', children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) { return <span className="select-wrap"><select className={cn('input select', className)} {...props}>{children}</select><ChevronDown size={15} /></span> }
export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) { return <span className={`badge badge-${tone}`}>{children}</span> }
export function StatusBadge({ status }: { status: string }) { const tone = /active|ready|complete/i.test(status) ? 'green' : /error|failed/i.test(status) ? 'red' : 'neutral'; return <Badge tone={tone}>{status}</Badge> }
export function Avatar({ initials = 'LS', size = 'md' }: { initials?: string; size?: 'sm' | 'md' | 'lg' }) { return <span className={`avatar avatar-${size}`} aria-label="User profile">{initials}</span> }
export function Tooltip({ label, children }: { label: string; children: ReactNode }) { return <span className="tooltip-wrap">{children}<span role="tooltip" className="tooltip">{label}</span></span> }
export function Dropdown({ label, children }: { label: ReactNode; children: ReactNode }) { const [open, setOpen] = useState(false); return <div className="dropdown-wrap"><button className="dropdown-trigger" aria-expanded={open} onClick={() => setOpen(!open)}>{label}</button>{open && <div className="dropdown-panel" onClick={() => setOpen(false)}>{children}</div>}</div> }
export function Modal({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) { useEffect(() => { if (!open) return; const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey) }, [open, onClose]); if (!open) return null; return <div className="modal-backdrop" onMouseDown={onClose}><section className="modal glass-card" role="dialog" aria-modal="true" aria-labelledby="modal-title" onMouseDown={e => e.stopPropagation()}><header><h2 id="modal-title">{title}</h2><Button variant="ghost" size="sm" aria-label="Close dialog" onClick={onClose}><X size={17} /></Button></header>{children}</section></div> }
export function SearchInput({ value, onChange, placeholder = 'Search' }: { value?: string; onChange?: (value: string) => void; placeholder?: string }) { return <label className="search-input"><span className="search-icon" aria-hidden="true">⌕</span><input aria-label={placeholder} value={value} onChange={e => onChange?.(e.target.value)} placeholder={placeholder} /><kbd>⌘ K</kbd></label> }
export function EmptyState({ icon: Icon = Info, title, description, action }: { icon?: typeof Info; title: string; description: string; action?: ReactNode }) { return <div className="empty-state"><span className="empty-icon"><Icon size={20} /></span><h3>{title}</h3><p>{description}</p>{action}</div> }
export function LoadingState({ label = 'Loading workspace' }: { label?: string }) { return <div className="state-inline"><LoaderCircle className="spin" size={17} />{label}</div> }
export function ErrorState({ message = 'Something went wrong.' }: { message?: string }) { return <div className="state-inline error-text"><AlertCircle size={17} />{message}</div> }
export function Skeleton({ className = '' }: { className?: string }) { return <span className={cn('skeleton', className)} aria-hidden="true" /> }
const ToastContext = createContext<{ push: (toast: Omit<ToastMessage, 'id'>) => void }>({ push: () => undefined })
export function useToast() { return useContext(ToastContext) }
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastMessage[]>([])
  const push = useCallback((toast: Omit<ToastMessage, 'id'>) => {
    const id = crypto.randomUUID()
    setItems(current => [...current, { ...toast, id }])
    window.setTimeout(() => setItems(current => current.filter(item => item.id !== id)), 3600)
  }, [])
  const value = useMemo(() => ({ push }), [push])
  return <ToastContext.Provider value={value}>{children}<div className="toast-stack" aria-live="polite">{items.map(item => <div key={item.id} className="toast glass-card"><span className={`toast-icon ${item.tone ?? 'info'}`}>{item.tone === 'success' ? <Check size={16} /> : item.tone === 'error' ? <AlertCircle size={16} /> : <Info size={16} />}</span><div><strong>{item.title}</strong>{item.description && <small>{item.description}</small>}</div><button aria-label="Dismiss notification" onClick={() => setItems(current => current.filter(entry => entry.id !== item.id))}><X size={15} /></button></div>)}</div></ToastContext.Provider>
}
