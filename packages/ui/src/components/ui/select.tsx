// shadcn/ui Select (Radix), mapped onto this app's theme colours.
import * as SelectPrimitive from '@radix-ui/react-select'
import * as React from 'react'
import { cn } from '../../lib/utils'

function Select(props: React.ComponentProps<typeof SelectPrimitive.Root>) {
  return <SelectPrimitive.Root data-slot="select" {...props} />
}

function SelectGroup(props: React.ComponentProps<typeof SelectPrimitive.Group>) {
  return <SelectPrimitive.Group data-slot="select-group" {...props} />
}

function SelectValue(props: React.ComponentProps<typeof SelectPrimitive.Value>) {
  return <SelectPrimitive.Value data-slot="select-value" {...props} />
}

function Chevron({ className }: { className?: string }) {
  return (
    <svg width="10" height="6" viewBox="0 0 10 6" aria-hidden className={className}>
      <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}

function SelectTrigger({ className, children, ...props }: React.ComponentProps<typeof SelectPrimitive.Trigger>) {
  return (
    <SelectPrimitive.Trigger
      data-slot="select-trigger"
      className={cn(
        'flex h-8 min-w-0 items-center justify-between gap-2 rounded-sm border border-line bg-paper px-2.5 font-sans text-sm text-fg hover:border-muted',
        'focus:outline-none focus-visible:border-fg data-[placeholder]:text-muted disabled:cursor-not-allowed disabled:opacity-40',
        '[&>span]:truncate',
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <Chevron className="shrink-0 text-muted" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  )
}

function SelectContent({ className, children, position = 'popper', ...props }: React.ComponentProps<typeof SelectPrimitive.Content>) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        data-slot="select-content"
        position={position}
        sideOffset={4}
        collisionPadding={8}
        className={cn(
          'z-50 max-h-(--radix-select-content-available-height) min-w-(--radix-select-trigger-width) overflow-hidden rounded-sm border border-fg bg-paper font-sans text-sm text-fg shadow-lg',
          className,
        )}
        {...props}
      >
        <SelectPrimitive.Viewport className="p-1">{children}</SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  )
}

function SelectLabel({ className, ...props }: React.ComponentProps<typeof SelectPrimitive.Label>) {
  return (
    <SelectPrimitive.Label
      data-slot="select-label"
      className={cn('px-2 pt-1.5 pb-1 text-[10px] font-semibold tracking-wider text-muted uppercase', className)}
      {...props}
    />
  )
}

function SelectItem({ className, children, hint, ...props }: React.ComponentProps<typeof SelectPrimitive.Item> & { hint?: React.ReactNode }) {
  return (
    <SelectPrimitive.Item
      data-slot="select-item"
      className={cn(
        'relative flex cursor-pointer items-center gap-2 rounded-sm py-1.5 pr-3 pl-6 outline-none select-none',
        'data-[disabled]:pointer-events-none data-[disabled]:opacity-40 data-[highlighted]:bg-paper-2',
        className,
      )}
      {...props}
    >
      <span className="absolute left-1.5 flex w-3 justify-center">
        <SelectPrimitive.ItemIndicator>
          <svg width="10" height="8" viewBox="0 0 10 8" aria-hidden><path d="M1 4l3 3 5-6" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
        </SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
      {hint && <span className="ml-auto pl-3 font-mono text-[11px] text-muted">{hint}</span>}
    </SelectPrimitive.Item>
  )
}

function SelectSeparator({ className, ...props }: React.ComponentProps<typeof SelectPrimitive.Separator>) {
  return <SelectPrimitive.Separator data-slot="select-separator" className={cn('-mx-1 my-1 h-px bg-line', className)} {...props} />
}

export { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue }
