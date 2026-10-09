//! `<x>_<y>.lotheader`
//!
//! ```text
//! "LOTH"  u32 version (1)
//! u32 n   then n tile names, each followed by '\n'
//! u32 field_a (8)  u32 field_b (8)  u32 min_z  u32 max_z
//! u32 rooms, then each: name '\n', u32 z, u32 rects, rects*(x y w h), u32 objects, objects*(a b c)
//! u32 buildings, then each: u32 k, k * u32 (indexes into the rooms)
//! 1024 bytes, one per 8x8 chunk of the 32x32 chunks in a cell
//! ```

use crate::{put_u32, Reader};

pub const MAGIC: &[u8; 4] = b"LOTH";
pub const CHUNK_VALUES: usize = 1024;

#[derive(Debug, Clone, PartialEq)]
pub struct Room {
    pub name: String,
    pub z: u32,
    pub rects: Vec<[u32; 4]>,
    /// Seen as (kind, x, y); kept as read.
    pub objects: Vec<[u32; 3]>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Header {
    pub version: u32,
    pub tiles: Vec<String>,
    pub field_a: u32,
    pub field_b: u32,
    pub min_z: u32,
    pub max_z: u32,
    pub rooms: Vec<Room>,
    pub buildings: Vec<Vec<u32>>,
    pub chunk_values: Vec<u8>,
}

impl Header {
    pub fn parse(data: &[u8]) -> Result<Header, String> {
        let mut r = Reader::new(data);
        if r.bytes(4)? != MAGIC {
            return Err("not a lot header".into());
        }
        let version = r.u32()?;
        let n = r.u32()? as usize;
        let mut tiles = Vec::with_capacity(n.min(1 << 20));
        for _ in 0..n {
            tiles.push(r.line()?);
        }
        let (field_a, field_b, min_z, max_z) = (r.u32()?, r.u32()?, r.u32()?, r.u32()?);
        let nr = r.u32()? as usize;
        let mut rooms = Vec::with_capacity(nr.min(1 << 20));
        for _ in 0..nr {
            let name = r.line()?;
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
                b.push(r.u32()?);
            }
            buildings.push(b);
        }
        if r.left() != CHUNK_VALUES {
            return Err(format!("{} bytes after the buildings, expected {CHUNK_VALUES}", r.left()));
        }
        let chunk_values = r.bytes(CHUNK_VALUES)?.to_vec();
        Ok(Header { version, tiles, field_a, field_b, min_z, max_z, rooms, buildings, chunk_values })
    }

    pub fn write(&self) -> Vec<u8> {
        let mut o = Vec::new();
        o.extend_from_slice(MAGIC);
        put_u32(&mut o, self.version);
        put_u32(&mut o, self.tiles.len() as u32);
        for t in &self.tiles {
            o.extend_from_slice(t.as_bytes());
            o.push(b'\n');
        }
        for v in [self.field_a, self.field_b, self.min_z, self.max_z] {
            put_u32(&mut o, v);
        }
        put_u32(&mut o, self.rooms.len() as u32);
        for room in &self.rooms {
            o.extend_from_slice(room.name.as_bytes());
            o.push(b'\n');
            put_u32(&mut o, room.z);
            put_u32(&mut o, room.rects.len() as u32);
            for rect in &room.rects {
                rect.iter().for_each(|&v| put_u32(&mut o, v));
            }
            put_u32(&mut o, room.objects.len() as u32);
            for obj in &room.objects {
                obj.iter().for_each(|&v| put_u32(&mut o, v));
            }
        }
        put_u32(&mut o, self.buildings.len() as u32);
        for b in &self.buildings {
            put_u32(&mut o, b.len() as u32);
            b.iter().for_each(|&v| put_u32(&mut o, v));
        }
        o.extend_from_slice(&self.chunk_values);
        o
    }
}
