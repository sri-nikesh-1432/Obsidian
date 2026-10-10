/** Razorpay Checkout helper.
 *
 * The server creates the order and verifies the payment signature; the browser
 * only ever holds the publishable key id and an order id. The checkout script
 * is loaded from index.html.
 */

export interface RazorpayResponse {
  razorpay_order_id: string
  razorpay_payment_id: string
  razorpay_signature: string
}

export interface RazorpayOptions {
  key: string
  amount: number
  currency: string
  name: string
  description?: string
  order_id: string
  prefill?: { name?: string; email?: string }
  theme?: { color?: string }
  handler: (response: RazorpayResponse) => void
  modal?: { ondismiss?: () => void }
}

interface RazorpayConstructor {
  new (options: RazorpayOptions): { open: () => void; on: (event: string, cb: (...a: any[]) => void) => void }
}

declare global {
  interface Window {
    Razorpay?: RazorpayConstructor
  }
}

export function razorpayAvailable(): boolean {
  return typeof window !== 'undefined' && typeof window.Razorpay === 'function'
}

export function openCheckout(options: RazorpayOptions): boolean {
  if (!razorpayAvailable()) return false
  const checkout = new window.Razorpay!(options)
  checkout.on('payment.failed', () => {
    /* surfaced by the page through the verify step */
  })
  checkout.open()
  return true
}
