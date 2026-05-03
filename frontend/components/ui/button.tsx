import * as React from "react"

type ButtonVariant = "default" | "outline" | "ghost" | "destructive"
type ButtonSize = "default" | "sm" | "lg" | "icon"

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
}

const variantClasses: Record<ButtonVariant, string> = {
  default: "bg-tide-high text-white hover:opacity-90",
  outline: "border border-stone-300 bg-transparent hover:bg-stone-100",
  ghost: "bg-transparent hover:bg-stone-100",
  destructive: "bg-tide-low text-white hover:opacity-90",
}

const sizeClasses: Record<ButtonSize, string> = {
  default: "h-10 px-4 py-2 text-sm",
  sm: "h-8 px-3 text-xs",
  lg: "h-12 px-6 text-base",
  icon: "h-10 w-10",
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className = "", variant = "default", size = "default", ...props }, ref) => {
    const cls = [
      "inline-flex items-center justify-center rounded-md font-medium transition-colors",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-tide-high",
      "disabled:pointer-events-none disabled:opacity-50",
      variantClasses[variant],
      sizeClasses[size],
      className,
    ].join(" ")
    return <button ref={ref} className={cls} {...props} />
  },
)
Button.displayName = "Button"

export { Button }
export default Button
