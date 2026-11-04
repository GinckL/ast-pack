import { Cart, Status } from "./types";
import { subtotal, withTax } from "./money";

const BASE_URL = "/api";

export class ApiClient {
  private status: Status = Status.Idle;

  constructor(private readonly token: string) {}

  async checkout(cart: Cart): Promise<string> {
    this.status = Status.Pending;
    const total = withTax(subtotal(cart));
    const res = await this.post("/checkout", { cartId: cart.id, total });
    this.status = Status.Done;
    return res.id;
  }

  private async post(path: string, body: unknown): Promise<{ id: string }> {
    const r = await fetch(BASE_URL + path, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.token}` },
      body: JSON.stringify(body),
    });
    return r.json();
  }

  async logout(): Promise<void> {
    await this.post("/logout", {});
  }
}
