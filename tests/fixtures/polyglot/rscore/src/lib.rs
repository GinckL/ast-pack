pub mod billing;

pub use billing::invoice::Invoice;

/// Library version.
pub const VERSION: &str = "0.1.0";

pub fn banner() -> String {
    format!("rs-core {}", VERSION)
}
