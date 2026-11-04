use crate::billing::tax::{tax_for, Region};
use std::fmt;

/// A line on an invoice.
#[derive(Debug, Clone)]
pub struct Line {
    pub description: String,
    pub cents: u64,
}

/// An invoice for one customer.
#[derive(Debug, Default)]
pub struct Invoice {
    pub customer: String,
    pub lines: Vec<Line>,
}

impl Invoice {
    pub fn new(customer: &str) -> Self {
        Self { customer: customer.to_string(), lines: Vec::new() }
    }

    pub fn add(&mut self, description: &str, cents: u64) {
        self.lines.push(Line { description: description.into(), cents });
    }

    pub fn subtotal(&self) -> u64 {
        self.lines.iter().map(|l| l.cents).sum()
    }

    pub fn total(&self, region: Region) -> u64 {
        let sub = self.subtotal();
        sub + tax_for(sub, region)
    }

    pub fn clear(&mut self) {
        self.lines.clear();
    }
}

impl fmt::Display for Invoice {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Invoice for {} ({} lines)", self.customer, self.lines.len())
    }
}
