//! `chunkdata_<x>_<y>.bin`
//!
//! ```text
//! 2 bytes (seen as 00 01)
//! 1024 bytes, one per chunk of the cell
//! then any number of 64-byte blocks (0 in most files)
//! ```
//! What the blocks and the per-chunk values mean is not known yet; they are kept
//! exactly as read.

pub const HEAD: usize = 2;
pub const GRID: usize = 1024;
pub const BLOCK: usize = 64;

#[derive(Debug, Clone, PartialEq)]
pub struct ChunkData {
    pub head: [u8; 2],
    pub grid: Vec<u8>,
    pub blocks: Vec<[u8; BLOCK]>,
}

impl ChunkData {
    pub fn parse(data: &[u8]) -> Result<ChunkData, String> {
        if data.len() < HEAD + GRID || (data.len() - HEAD - GRID) % BLOCK != 0 {
            return Err(format!("{} bytes is not 2 + 1024 + 64k", data.len()));
        }
        let grid = data[HEAD..HEAD + GRID].to_vec();
        let blocks = data[HEAD + GRID..]
            .chunks_exact(BLOCK)
            .map(|b| {
                let mut a = [0u8; BLOCK];
                a.copy_from_slice(b);
                a
            })
            .collect();
        Ok(ChunkData { head: [data[0], data[1]], grid, blocks })
    }

    pub fn write(&self) -> Vec<u8> {
        let mut o = Vec::with_capacity(HEAD + GRID + BLOCK * self.blocks.len());
        o.extend_from_slice(&self.head);
        o.extend_from_slice(&self.grid);
        for b in &self.blocks {
            o.extend_from_slice(b);
        }
        o
    }
}
