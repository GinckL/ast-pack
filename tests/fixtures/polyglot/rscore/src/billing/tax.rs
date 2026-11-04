/// Standard VAT rate in basis points.
pub const VAT_BPS: u64 = 2000;

#[derive(Debug, Clone, Copy)]
pub enum Region {
    Eu,
    Us,
}

pub fn tax_for(amount: u64, region: Region) -> u64 {
    match region {
        Region::Eu => amount * VAT_BPS / 10_000,
        Region::Us => 0,
    }
}

pub fn round_cents(amount: u64) -> u64 {
    (amount + 50) / 100 * 100
}
