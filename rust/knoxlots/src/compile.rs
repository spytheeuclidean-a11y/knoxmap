//! From a cell source (`.kcell`) to the lot files, and back for checking.

use crate::bmp::GreyImage;
use crate::cell::CHUNKS;
use crate::chunkdata::ChunkData;
use crate::header::{Header, CHUNK_VALUES};
use crate::kcell::KCell;
use crate::pack::Pack;
use crate::spawn;

/// The world-wide settings in `source.txt`.
///
/// ```text
/// format = knoxlots-source 1
/// origin_x = 21000        # tile x of the world's west edge, in lot-file coordinates (70 * 300)
/// origin_y = 0
/// spawn_map = Worthville_ZombieSpawnMap.bmp    # optional, path relative to this file
/// field_a = 8             # optional; two header values that have always been 8
/// field_b = 8
/// ```
#[derive(Debug, Clone, PartialEq)]
pub struct Manifest {
    pub origin_x: i64,
    pub origin_y: i64,
    pub spawn_map: Option<String>,
    pub field_a: u32,
    pub field_b: u32,
}

impl Default for Manifest {
    fn default() -> Self {
        Manifest { origin_x: 0, origin_y: 0, spawn_map: None, field_a: 8, field_b: 8 }
    }
}

impl Manifest {
    pub fn parse(text: &str) -> Result<Manifest, String> {
        let mut m = Manifest::default();
        let mut format_seen = false;
        for (n, raw) in text.lines().enumerate() {
            let line = raw.split('#').next().unwrap_or("").trim();
            if line.is_empty() {
                continue;
            }
            let (k, v) = line.split_once('=').ok_or_else(|| format!("line {}: no '='", n + 1))?;
            let (k, v) = (k.trim(), v.trim());
            let num = |what: &str| v.parse::<i64>().map_err(|_| format!("line {}: {what} is not a number", n + 1));
            match k {
                "format" => {
                    if v != "knoxlots-source 1" {
                        return Err(format!("format \"{v}\" is not known"));
                    }
                    format_seen = true;
                }
                "origin_x" => m.origin_x = num("origin_x")?,
                "origin_y" => m.origin_y = num("origin_y")?,
                "spawn_map" => m.spawn_map = Some(v.to_string()),
                "field_a" => m.field_a = num("field_a")? as u32,
                "field_b" => m.field_b = num("field_b")? as u32,
                _ => return Err(format!("line {}: \"{k}\" is not a known setting", n + 1)),
            }
        }
        if !format_seen {
            return Err("the first setting must be: format = knoxlots-source 1".into());
        }
        if m.origin_x % 8 != 0 || m.origin_y % 8 != 0 {
            return Err("origin_x and origin_y must be multiples of 8 (a chunk)".into());
        }
        Ok(m)
    }

    pub fn write(&self) -> String {
        let mut s = String::from("format = knoxlots-source 1\n");
        s += &format!("origin_x = {}\norigin_y = {}\n", self.origin_x, self.origin_y);
        if let Some(p) = &self.spawn_map {
            s += &format!("spawn_map = {p}\n");
        }
        s += &format!("field_a = {}\nfield_b = {}\n", self.field_a, self.field_b);
        s
    }
}

/// The three files of one cell.
pub struct CellFiles {
    pub header: Vec<u8>,
    pub pack: Vec<u8>,
    pub chunkdata: Vec<u8>,
}

/// The zombie bytes for a cell: its own if it carries them, else from the spawn map,
/// else none.
pub fn zombie_bytes(k: &KCell, m: &Manifest, spawn_map: Option<&GreyImage>) -> Vec<u8> {
    if let Some(z) = &k.zombie {
        return z.clone();
    }
    let Some(img) = spawn_map else { return vec![0; CHUNK_VALUES] };
    let grey = img.view();
    // The cell's west and north edges in chunks from the picture's corner.
    let base_x = (k.cell_x as i64 * 256 - m.origin_x) / 8;
    let base_y = (k.cell_y as i64 * 256 - m.origin_y) / 8;
    let mut out = vec![0u8; CHUNK_VALUES];
    for cx in 0..CHUNKS {
        for cy in 0..CHUNKS {
            out[spawn::index(cx, cy)] = grey.chunk_intensity(base_x + cx as i64, base_y + cy as i64);
        }
    }
    out
}

pub fn compile_cell(k: &KCell, m: &Manifest, spawn_map: Option<&GreyImage>) -> CellFiles {
    let (tiles, pack) = k.squares.to_pack();
    let header = Header {
        version: 1,
        tiles,
        field_a: m.field_a,
        field_b: m.field_b,
        min_z: k.min_z,
        max_z: k.min_z + k.squares.levels as u32 - 1,
        rooms: k.rooms.clone(),
        buildings: k.buildings.clone(),
        chunk_values: zombie_bytes(k, m, spawn_map),
    };
    CellFiles {
        header: header.write(),
        pack: pack_bytes(&pack),
        chunkdata: ChunkData { head: [0, 1], grid: vec![0; 1024], blocks: vec![] }.write(),
    }
}

fn pack_bytes(p: &Pack) -> Vec<u8> {
    p.write()
}

/// A cell source made from existing lot files (to check the compiler, or to move a
/// map made elsewhere). `keep_zombie` stores the header's bytes; without it they are
/// left for the spawn map.
pub fn export_cell(cell_x: u32, cell_y: u32, header: &Header, pack: &Pack, keep_zombie: bool) -> Result<KCell, String> {
    let levels = (header.max_z - header.min_z + 1) as usize;
    let squares = crate::cell::Cell::from_pack(&header.tiles, pack, levels)?;
    Ok(KCell {
        cell_x,
        cell_y,
        min_z: header.min_z,
        rooms: header.rooms.clone(),
        buildings: header.buildings.clone(),
        zombie: keep_zombie.then(|| header.chunk_values.clone()),
        squares,
    })
}
