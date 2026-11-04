from ast_pack.tokens import TokenCounter, approx_count


def test_approx_counter_is_deterministic_and_reasonable():
    text = "def process_payment(req: PaymentRequest) -> Receipt:\n    return gateway.charge(req)\n"
    n = approx_count(text)
    assert n == approx_count(text)
    assert 12 <= n <= 40


def test_counter_falls_back_to_approx():
    c = TokenCounter("approx")
    assert c.name == "approx" and not c.exact
    assert c.count("hello world") > 0 and c.count("") == 0
