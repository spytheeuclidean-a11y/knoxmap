//! A cell as a plain grid of squares, and the rules for turning it into files.
//!
//! Layout rules, each found by experiment or by checking every file of five maps:
//!
//! - A cell is 256 x 256 squares, in 32 x 32 chunks of 8 x 8, on `levels` levels.
//! - The pack lists chunks as `chunk_x * 32 + chunk_y`.
//! - Within a chunk the squares run level by level, and on a level `x * 8 + y`
//!   (a house's wall tiles span exactly the house's footprint only in this order).
//! - The header's tile table holds exactly the tiles the cell uses, once each,
//!   sorted by name.

use crate::pack::{encode, expand, Pack, Rec};

pub const SIDE: usize = 256;
pub const CHUNKS: usize = 32;
pub const CHUNK: usize = 8;
const SQUARES_PER_CHUNK_LEVEL: usize = CHUNK * CHUNK;

/// One square: the room value (0xFFFFFFFF for none) and its tiles, bottom first,
/// as indexes into [`Cell::names`].
#[derive(Debug, Clone, PartialEq)]
pub struct Square {
    pub room: u32,
    pub tiles: Vec<u32>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Cell {
    pub levels: usize,
    /// Tile names; the squares refer to these by position. Any order.
    pub names: Vec<String>,
    /// `levels * 256 * 256` squares, index `(z * 256 + x) * 256 + y`.
    pub squares: Vec<Option<Square>>,
}

fn at(z: usize, x: usize, y: usize) -> usize {
    (z * SIDE + x) * SIDE + y
}

impl Cell {
    pub fn empty(levels: usize) -> Cell {
        Cell { levels, names: Vec::new(), squares: vec![None; levels * SIDE * SIDE] }
    }

    pub fn get(&self, z: usize, x: usize, y: usize) -> Option<&Square> {
        self.squares[at(z, x, y)].as_ref()
    }

    pub fn set(&mut self, z: usize, x: usize, y: usize, sq: Option<Square>) {
        self.squares[at(z, x, y)] = sq;
    }

    /// The name's index, adding it if it is new.
    pub fn name_index(&mut self, name: &str) -> u32 {
        if let Some(i) = self.names.iter().position(|n| n == name) {
            return i as u32;
        }
        self.names.push(name.to_string());
        (self.names.len() - 1) as u32
    }

    /// Read a cell from a header's tile table and a pack. `levels` is how many
    /// levels the header says it has.
    pub fn from_pack(tiles: &[String], pack: &Pack, levels: usize) -> Result<Cell, String> {
        if pack.chunks.len() != CHUNKS * CHUNKS {
            return Err(format!("{} chunks, expected {}", pack.chunks.len(), CHUNKS * CHUNKS));
        }
        let mut cell = Cell { levels, names: tiles.to_vec(), squares: vec![None; levels * SIDE * SIDE] };
        for (i, recs) in pack.chunks.iter().enumerate() {
            let (cx, cy) = (i / CHUNKS, i % CHUNKS);
            let grid = expand(recs);
            if grid.len() != levels * SQUARES_PER_CHUNK_LEVEL {
                return Err(format!("chunk {i} has {} squares, expected {}", grid.len(),
                                   levels * SQUARES_PER_CHUNK_LEVEL));
            }
            for (k, sq) in grid.into_iter().enumerate() {
                let Some(v) = sq else { continue };
                if v.is_empty() {
                    return Err(format!("chunk {i}: a square with no room value"));
                }
                if v[1..].iter().any(|&t| t as usize >= tiles.len()) {
                    return Err(format!("chunk {i}: a tile number past the table"));
                }
                let z = k / SQUARES_PER_CHUNK_LEVEL;
                let r = k % SQUARES_PER_CHUNK_LEVEL;
                let (x, y) = (cx * CHUNK + r / CHUNK, cy * CHUNK + r % CHUNK);
                cell.squares[at(z, x, y)] = Some(Square { room: v[0], tiles: v[1..].to_vec() });
            }
        }
        Ok(cell)
    }

    /// The header's tile table (used tiles, sorted by name) and the pack.
    pub fn to_pack(&self) -> (Vec<String>, Pack) {
        let mut used = vec![false; self.names.len()];
        for sq in self.squares.iter().flatten() {
            for &t in &sq.tiles {
                used[t as usize] = true;
            }
        }
        let mut table: Vec<String> = (0..self.names.len()).filter(|&i| used[i]).map(|i| self.names[i].clone()).collect();
        table.sort();
        table.dedup();
        let mut number = vec![0u32; self.names.len()];
        for (i, n) in self.names.iter().enumerate() {
            if used[i] {
                number[i] = table.binary_search(n).expect("a used name is in the table") as u32;
            }
        }
        let mut chunks: Vec<Vec<Rec>> = Vec::with_capacity(CHUNKS * CHUNKS);
        let mut grid: Vec<Option<Vec<u32>>> = Vec::with_capacity(self.levels * SQUARES_PER_CHUNK_LEVEL);
        for i in 0..CHUNKS * CHUNKS {
            let (cx, cy) = (i / CHUNKS, i % CHUNKS);
            grid.clear();
            for z in 0..self.levels {
                for r in 0..SQUARES_PER_CHUNK_LEVEL {
                    let (x, y) = (cx * CHUNK + r / CHUNK, cy * CHUNK + r % CHUNK);
                    grid.push(self.squares[at(z, x, y)].as_ref().map(|sq| {
                        let mut v = Vec::with_capacity(1 + sq.tiles.len());
                        v.push(sq.room);
                        v.extend(sq.tiles.iter().map(|&t| number[t as usize]));
                        v
                    }));
                }
            }
            chunks.push(encode(&grid));
        }
        (table, Pack { version: 1, chunks })
    }
}
