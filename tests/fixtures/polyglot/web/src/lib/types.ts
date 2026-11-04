export type Currency = "USD" | "EUR";

export interface CartItem {
  sku: string;
  price: number;
  qty: number;
}

export interface Cart {
  id: string;
  items: CartItem[];
  currency: Currency;
}

export enum Status {
  Idle,
  Pending,
  Done,
}

export interface User {
  id: string;
  email: string;
}
