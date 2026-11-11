# rust/knoxlots/src/cell.rs

- SIDE · constant · L14-L14 — pub const SIDE: usize = 256;
- CHUNKS · constant · L15-L15 — pub const CHUNKS: usize = 32;
- CHUNK · constant · L16-L16 — pub const CHUNK: usize = 8;
- SQUARES_PER_CHUNK_LEVEL · constant · L17-L17 — const SQUARES_PER_CHUNK_LEVEL: usize = CHUNK * CHUNK;
- Square · struct · L22-L25 — pub struct Square
- Cell · struct · L28-L34 — pub struct Cell
- at · function · L36-L38 — fn at(z: usize, x: usize, y: usize) -> usize
- empty · function · L41-L43 — pub fn empty(levels: usize) -> Cell
- get · function · L45-L47 — pub fn get(&self, z: usize, x: usize, y: usize) -> Option<&Square>
- set · function · L49-L51 — pub fn set(&mut self, z: usize, x: usize, y: usize, sq: Option<Square>)
- name_index · function · L54-L60 — pub fn name_index(&mut self, name: &str) -> u32
- from_pack · function · L64-L91 — pub fn from_pack(tiles: &[String], pack: &Pack, levels: usize) -> Result<Cell, String>
- to_pack · function · L94-L129 — pub fn to_pack(&self) -> (Vec<String>, Pack)
