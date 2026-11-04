import type { Cart, CartItem } from "./types";

export const TAX_RATE = 0.2;

export function lineTotal(item: CartItem): number {
  return item.price * item.qty;
}

export function subtotal(cart: Cart): number {
  return cart.items.reduce((sum, item) => sum + lineTotal(item), 0);
}

export function withTax(amount: number): number {
  return Math.round(amount * (1 + TAX_RATE) * 100) / 100;
}

export function formatMoney(amount: number, currency: string): string {
  return `${currency} ${amount.toFixed(2)}`;
}
