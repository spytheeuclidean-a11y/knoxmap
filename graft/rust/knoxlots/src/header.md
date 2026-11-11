# rust/knoxlots/src/header.rs

- MAGIC · constant · L14-L14 — pub const MAGIC: &[u8; 4] = b"LOTH";
- CHUNK_VALUES · constant · L15-L15 — pub const CHUNK_VALUES: usize = 1024;
- Room · struct · L18-L24 — pub struct Room
- Header · struct · L27-L37 — pub struct Header
- parse · function · L40-L84 — pub fn parse(data: &[u8]) -> Result<Header, String>
- write · function · L86-L119 — pub fn write(&self) -> Vec<u8>
