//! `cell_<x>_<y>.kcell`: what a producer (KnoxMap) hands the compiler for one cell.
//!
//! Little-endian. Names carry their length instead of a newline so any text fits.
//!
//! ```text
//! "KCEL"  u32 version (1)  u32 cell_x  u32 cell_y     the 256-tile cell, as in 83_2
//! u32 min_z  u32 levels
//! u32 names, then each: u16 length, UTF-8 bytes        tile names, any order, no repeats
//! u32 rooms, then each: u16 length + name, u32 z, u32 rects, rects*(x y w h),
//!                       u32 objects, objects*(a b c)   cell tile coordinates
//! u32 buildings, then each: u32 k, k * u32             indexes into the rooms
//! u8 zombie_flag; if 1, 1024 bytes of zombie intensity (else taken from the spawn map)
//! the squares of every level, level by level, row by row (y, then x within a row),
//! as records until levels * 256 * 256 squares are covered:
//!     u32 0xFFFFFFFF, u32 count        `count` empty squares
//!     u32 n (1..), then n * u32        one square: a room value (0xFFFFFFFF for
//!                                      none), then n-1 indexes into the names table,
//!                                      bottom tile first
//! ```
//! The scan order (rows of x) is the natural one for a picture-like array; the
//! compiler does the reordering into chunks.

use crate::cell::{Cell, Square, SIDE};
use crate::header::{Room, CHUNK_VALUES};
use crate::{put_u32, Reader};

pub const MAGIC: &[u8; 4] = b"KCEL";
const NONE: u32 = 0xFFFF_FFFF;

#[derive(Debug, Clone, PartialEq)]
pub struct KCell {
    pub cell_x: u32,
    pub cell_y: u32,
    pub min_z: u32,
    pub rooms: Vec<Room>,
    pub buildings: Vec<Vec<u32>>,
    pub zombie: Option<Vec<u8>>,
    pub squares: Cell,
}

fn put_str(o: &mut Vec<u8>, s: &str) -> Result<(), String> {
    let n = u16::try_from(s.len()).map_err(|_| format!("a name is {} bytes, the most is 65535", s.len()))?;
    o.extend_from_slice(&n.to_le_bytes());
    o.extend_from_slice(s.as_bytes());
    Ok(())
}

fn get_str(r: &mut Reader) -> Result<String, String> {
    let b = r.bytes(2)?;
    let n = u16::from_le_bytes([b[0], b[1]]) as usize;
    String::from_utf8(r.bytes(n)?.to_vec()).map_err(|_| "a name is not text".to_string())
}

impl KCell {
    pub fn write(&self) -> Result<Vec<u8>, String> {
        let mut o = Vec::new();
        o.extend_from_slice(MAGIC);
        for v in [1, self.cell_x, self.cell_y, self.min_z, self.squares.levels as u32] {
            put_u32(&mut o, v);
        }
        put_u32(&mut o, self.squares.names.len() as u32);
        for n in &self.squares.names {
            put_str(&mut o, n)?;
        }
        put_u32(&mut o, self.rooms.len() as u32);
        for room in &self.rooms {
            put_str(&mut o, &room.name)?;
            put_u32(&mut o, room.z);
            put_u32(&mut o, room.rects.len() as u32);
            room.rects.iter().flatten().for_each(|&v| put_u32(&mut o, v));
            put_u32(&mut o, room.objects.len() as u32);
            room.objects.iter().flatten().for_each(|&v| put_u32(&mut o, v));
        }
        put_u32(&mut o, self.buildings.len() as u32);
        for b in &self.buildings {
            put_u32(&mut o, b.len() as u32);
            b.iter().for_each(|&v| put_u32(&mut o, v));
        }
        match &self.zombie {
            Some(z) if z.len() == CHUNK_VALUES => {
                o.push(1);
                o.extend_from_slice(z);
            }
            Some(_) => return Err("zombie intensity must be 1024 bytes".into()),
            None => o.push(0),
        }
        // Squares, level by level, row by row.
        let mut run = 0u32;
        let flush = |o: &mut Vec<u8>, run: &mut u32| {
            if *run > 0 {
                put_u32(o, NONE);
                put_u32(o, *run);
                *run = 0;
            }
        };
        for z in 0..self.squares.levels {
            for y in 0..SIDE {
                for x in 0..SIDE {
                    match self.squares.get(z, x, y) {
                        None => run += 1,
                        Some(sq) => {
                            flush(&mut o, &mut run);
                            put_u32(&mut o, 1 + sq.tiles.len() as u32);
                            put_u32(&mut o, sq.room);
                            sq.tiles.iter().for_each(|&t| put_u32(&mut o, t));
                        }
                    }
                }
            }
        }
        flush(&mut o, &mut run);
        Ok(o)
    }

    pub fn parse(data: &[u8]) -> Result<KCell, String> {
        let mut r = Reader::new(data);
        if r.bytes(4)? != MAGIC {
            return Err("not a cell source file".into());
        }
        let version = r.u32()?;
        if version != 1 {
            return Err(format!("cell source version {version} is not known"));
        }
        let (cell_x, cell_y, min_z, levels) = (r.u32()?, r.u32()?, r.u32()?, r.u32()? as usize);
        if levels == 0 || levels > 64 {
            return Err(format!("{levels} levels"));
        }
        let n = r.u32()? as usize;
        let mut names = Vec::with_capacity(n.min(1 << 20));
        for _ in 0..n {
            names.push(get_str(&mut r)?);
        }
        let nr = r.u32()? as usize;
        let mut rooms = Vec::with_capacity(nr.min(1 << 20));
        for _ in 0..nr {
            let name = get_str(&mut r)?;
            let z = r.u32()?;
            let nrect = r.u32()? as usize;
            let mut rects = Vec::with_capacity(nrect.min(1 << 16));
            for _ in 0..nrect {
                rects.push([r.u32()?, r.u32()?, r.u32()?, r.u32()?]);
            }
            let nobj = r.u32()? as usize;
            let mut objects = Vec::with_capacity(nobj.min(1 << 16));
            for _ in 0..nobj {
                objects.push([r.u32()?, r.u32()?, r.u32()?]);
            }
            rooms.push(Room { name, z, rects, objects });
        }
        let nb = r.u32()? as usize;
        let mut buildings = Vec::with_capacity(nb.min(1 << 20));
        for _ in 0..nb {
            let k = r.u32()? as usize;
            let mut b = Vec::with_capacity(k.min(1 << 16));
            for _ in 0..k {
                let room = r.u32()?;
                if room as usize >= rooms.len() {
                    return Err(format!("a building names room {room} of {}", rooms.len()));
                }
                b.push(room);
            }
            buildings.push(b);
        }
        let zombie = match r.bytes(1)?[0] {
            0 => None,
            1 => Some(r.bytes(CHUNK_VALUES)?.to_vec()),
            f => return Err(format!("zombie flag {f}")),
        };
        let total = levels * SIDE * SIDE;
        let mut squares = Cell { levels, names, squares: vec![None; total] };
        let mut at = 0usize; // position in the scan order (z, y, x)
        while at < total {
            let n = r.u32()?;
            if n == NONE {
                let c = r.u32()? as usize;
                if c == 0 || c > total - at {
                    return Err(format!("a run of {c} empty squares at {at} of {total}"));
                }
                at += c;
            } else {
                let n = n as usize;
                if n == 0 || n * 4 > r.left() {
                    return Err("a square runs past the end of the file".into());
                }
                let room = r.u32()?;
                let mut tiles = Vec::with_capacity(n - 1);
                for _ in 1..n {
                    let t = r.u32()?;
                    if t as usize >= squares.names.len() {
                        return Err(format!("tile {t} is not in the table of {}", squares.names.len()));
                    }
                    tiles.push(t);
                }
                let (z, rest) = (at / (SIDE * SIDE), at % (SIDE * SIDE));
                let (y, x) = (rest / SIDE, rest % SIDE);
                squares.set(z, x, y, Some(Square { room, tiles }));
                at += 1;
            }
        }
        if r.left() != 0 {
            return Err(format!("{} bytes after the squares", r.left()));
        }
        Ok(KCell { cell_x, cell_y, min_z, rooms, buildings, zombie, squares })
    }
}
