# rust/knoxlots/src/chunkdata.rs

- HEAD · constant · L11-L11 — pub const HEAD: usize = 2;
- GRID · constant · L12-L12 — pub const GRID: usize = 1024;
- BLOCK · constant · L13-L13 — pub const BLOCK: usize = 64;
- ChunkData · struct · L16-L20 — pub struct ChunkData
- parse · function · L23-L37 — pub fn parse(data: &[u8]) -> Result<ChunkData, String>
- write · function · L39-L47 — pub fn write(&self) -> Vec<u8>
