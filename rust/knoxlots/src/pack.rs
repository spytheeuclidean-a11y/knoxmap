//! `world_<x>_<y>.lotpack`
//!
//! ```text
//! "LOTP"  u32 version (1)  u32 chunks (1024)
//! chunks * u64 offset of each chunk's bytes, from the start of the file
//! the chunks, each a run of records until its bytes end:
//!     u32 n == 0xFFFFFFFF, u32 count     `count` squares with nothing in them
//!     u32 n, then n * u32                one square: the first value is its room
//!                                        (0xFFFFFFFF for none), the rest tile numbers
//!                                        (indexes into the header's tile names)
//! ```
//! A chunk is 8 x 8 squares on each level, so its records cover 64 * levels squares.

use crate::{put_u32, Reader};

pub const MAGIC: &[u8; 4] = b"LOTP";
pub const SQUARES_PER_LEVEL: usize = 64;
const SKIP: u32 = 0xFFFF_FFFF;

#[derive(Debug, Clone, PartialEq)]
pub enum Rec {
    Skip(u32),
    /// room, then tile numbers
    Square(Vec<u32>),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Pack {
    pub version: u32,
    pub chunks: Vec<Vec<Rec>>,
}

fn parse_chunk(bytes: &[u8]) -> Result<Vec<Rec>, String> {
    let mut r = Reader::new(bytes);
    let mut recs = Vec::new();
    while r.left() > 0 {
        let n = r.u32()?;
        if n == SKIP {
            recs.push(Rec::Skip(r.u32()?));
        } else {
            let n = n as usize;
            if n * 4 > r.left() {
                return Err("a square runs past its chunk".into());
            }
            let mut v = Vec::with_capacity(n);
            for _ in 0..n {
                v.push(r.u32()?);
            }
            recs.push(Rec::Square(v));
        }
    }
    Ok(recs)
}

fn write_chunk(recs: &[Rec], out: &mut Vec<u8>) {
    for rec in recs {
        match rec {
            Rec::Skip(c) => {
                put_u32(out, SKIP);
                put_u32(out, *c);
            }
            Rec::Square(v) => {
                put_u32(out, v.len() as u32);
                v.iter().for_each(|&x| put_u32(out, x));
            }
        }
    }
}

impl Pack {
    pub fn parse(data: &[u8]) -> Result<Pack, String> {
        let mut r = Reader::new(data);
        if r.bytes(4)? != MAGIC {
            return Err("not a lot pack".into());
        }
        let version = r.u32()?;
        let count = r.u32()? as usize;
        let mut offs = Vec::with_capacity(count + 1);
        for _ in 0..count {
            offs.push(r.u64()? as usize);
        }
        offs.push(data.len());
        let mut chunks = Vec::with_capacity(count);
        for i in 0..count {
            let (a, b) = (offs[i], offs[i + 1]);
            if a > b || b > data.len() {
                return Err(format!("chunk {i} has offsets {a}..{b}"));
            }
            chunks.push(parse_chunk(&data[a..b]).map_err(|e| format!("chunk {i}: {e}"))?);
        }
        Ok(Pack { version, chunks })
    }

    pub fn write(&self) -> Vec<u8> {
        let mut body = Vec::new();
        let mut offs = Vec::with_capacity(self.chunks.len());
        let start = 12 + 8 * self.chunks.len();
        for c in &self.chunks {
            offs.push((start + body.len()) as u64);
            write_chunk(c, &mut body);
        }
        let mut o = Vec::with_capacity(start + body.len());
        o.extend_from_slice(MAGIC);
        put_u32(&mut o, self.version);
        put_u32(&mut o, self.chunks.len() as u32);
        for off in offs {
            o.extend_from_slice(&off.to_le_bytes());
        }
        o.extend_from_slice(&body);
        o
    }
}

/// One chunk as a grid: `levels * 64` squares, `None` where nothing is.
pub fn expand(recs: &[Rec]) -> Vec<Option<Vec<u32>>> {
    let mut grid = Vec::new();
    for rec in recs {
        match rec {
            Rec::Skip(c) => grid.extend((0..*c).map(|_| None)),
            Rec::Square(v) => grid.push(Some(v.clone())),
        }
    }
    grid
}

/// The records for a grid, with every run of empty squares as long as it can be.
pub fn encode(grid: &[Option<Vec<u32>>]) -> Vec<Rec> {
    let mut recs = Vec::new();
    let mut run = 0u32;
    for sq in grid {
        match sq {
            None => run += 1,
            Some(v) => {
                if run > 0 {
                    recs.push(Rec::Skip(run));
                    run = 0;
                }
                recs.push(Rec::Square(v.clone()));
            }
        }
    }
    if run > 0 {
        recs.push(Rec::Skip(run));
    }
    recs
}
