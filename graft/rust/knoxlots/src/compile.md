# rust/knoxlots/src/compile.rs

- Manifest · struct · L22-L28 — pub struct Manifest
- default · function · L31-L33 — fn default() -> Self
- parse · function · L37-L70 — pub fn parse(text: &str) -> Result<Manifest, String>
- write · function · L72-L80 — pub fn write(&self) -> String
- CellFiles · struct · L84-L88 — pub struct CellFiles
- zombie_bytes · function · L92-L108 — pub fn zombie_bytes(k: &KCell, m: &Manifest, spawn_map: Option<&GreyImage>) -> Vec<u8>
- compile_cell · function · L110-L128 — pub fn compile_cell(k: &KCell, m: &Manifest, spawn_map: Option<&GreyImage>) -> CellFiles
- pack_bytes · function · L130-L132 — fn pack_bytes(p: &Pack) -> Vec<u8>
- export_cell · function · L137-L149 — pub fn export_cell(cell_x: u32, cell_y: u32, header: &Header, pack: &Pack, keep_zombie: bool) -> Result<KCell, String>
