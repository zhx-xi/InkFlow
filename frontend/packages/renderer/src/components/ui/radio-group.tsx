/** shadcn 风格 RadioGroup（Radix RadioGroup 封装，spec §5.2.2）：自绘圆点选中态，样式走 tokens.css */
import * as RadioGroupPrimitives from '@radix-ui/react-radio-group';
import * as React from 'react';
import { cn } from '../../lib/cn';

const RadioGroup = React.forwardRef<
  React.ElementRef<typeof RadioGroupPrimitives.Root>,
  React.ComponentPropsWithoutRef<typeof RadioGroupPrimitives.Root>
>(({ className, ...props }, ref) => (
  <RadioGroupPrimitives.Root className={cn('grid gap-2', className)} {...props} ref={ref} />
));
RadioGroup.displayName = RadioGroupPrimitives.Root.displayName;

const RadioGroupItem = React.forwardRef<
  React.ElementRef<typeof RadioGroupPrimitives.Item>,
  React.ComponentPropsWithoutRef<typeof RadioGroupPrimitives.Item>
>(({ className, ...props }, ref) => (
  <RadioGroupPrimitives.Item
    ref={ref}
    className={cn(
      'aspect-square h-4 w-4 rounded-full border border-ink-3 bg-surface text-accent',
      'transition-colors data-[state=checked]:border-accent',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
      'disabled:cursor-not-allowed disabled:opacity-50',
      className,
    )}
    {...props}
  >
    <RadioGroupPrimitives.Indicator className="flex items-center justify-center">
      <span className="h-2 w-2 rounded-full bg-accent" />
    </RadioGroupPrimitives.Indicator>
  </RadioGroupPrimitives.Item>
));
RadioGroupItem.displayName = RadioGroupPrimitives.Item.displayName;

export { RadioGroup, RadioGroupItem };
