import React, { useState } from "react";
import { Client, formatMoney, subtotal } from "@/lib";
import type { Cart } from "@/lib/types";

interface Props {
  cart: Cart;
  onDone: (id: string) => void;
}

export function CheckoutButton({ cart, onDone }: Props) {
  const [busy, setBusy] = useState(false);
  const client = new Client("token");

  async function handleClick() {
    setBusy(true);
    const id = await client.checkout(cart);
    setBusy(false);
    onDone(id);
  }

  return (
    <button disabled={busy} onClick={handleClick}>
      Pay {formatMoney(subtotal(cart), cart.currency)}
    </button>
  );
}

export function Spinner() {
  return <div className="spinner" />;
}
