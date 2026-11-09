// shadcn/ui Tooltip (Radix), mapped onto this app's theme colours.
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import * as React from 'react'
import { cn } from '../../lib/utils'

function TooltipProvider({ delayDuration = 300, ...props }: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return <TooltipPrimitive.Provider data-slot="tooltip-provider" delayDuration={delayDuration} {...props} />
}

function Tooltip(props: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  return <TooltipPrimitive.Root data-slot="tooltip" {...props} />
}

function TooltipTrigger(props: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />
}

function TooltipContent({ className, sideOffset = 6, children, ...props }: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        data-slot="tooltip-content"
        sideOffset={sideOffset}
        collisionPadding={6}
        className={cn(
          'z-50 max-w-72 rounded-md bg-fg px-2.5 py-1.5 font-sans text-xs leading-snug font-normal tracking-normal text-paper normal-case shadow-sm',
          className,
        )}
        {...props}
      >
        {children}
        <TooltipPrimitive.Arrow className="fill-fg" />
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  )
}

/** A label with a dotted underline that shows `tip` on hover or keyboard focus. */
function Tip({ tip, children, className }: { tip: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className={cn(
            'cursor-help underline decoration-current/40 decoration-dotted underline-offset-[3px] focus:outline-none focus-visible:rounded-sm focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-muted focus-visible:outline-dotted',
            className,
          )}
        >
          {children}
        </span>
      </TooltipTrigger>
      <TooltipContent>{tip}</TooltipContent>
    </Tooltip>
  )
}

export { Tip, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger }
